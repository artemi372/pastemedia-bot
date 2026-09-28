"""
Inline Telegram bot that downloads TikTok videos without watermark.

Usage in any chat:  @your_bot https://vm.tiktok.com/xxxx

Flow:
1. inline_query          -> instantly return a placeholder with an inline keyboard
                            (without a keyboard Telegram won't provide inline_message_id)
2. chosen_inline_result  -> download the video via yt-dlp (non-watermarked format),
                            upload it to a private storage channel to obtain a file_id
3. edit_message_media    -> replace the placeholder with the video
Repeated requests for the same link are served instantly from the file_id cache.

Photo slideshows are rendered into an mp4 (images + original music) with ffmpeg,
because an inline message can hold only one media item, not an album.
"""
import asyncio
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile

import httpx
import yt_dlp
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, Router
from aiogram.types import (
    CallbackQuery,
    ChosenInlineResult,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InlineQueryResultCachedVideo,
    InputMediaVideo,
    InputTextMessageContent,
)

load_dotenv()
BOT_TOKEN = os.environ["BOT_TOKEN"]
STORAGE_CHAT_ID = int(os.environ["STORAGE_CHAT_ID"])  # private channel where the bot is an admin, id like -100...
MAX_BYTES = 50 * 1024 * 1024  # Bot API upload limit
SLIDE_SECONDS = 2.5           # how long each slideshow image is shown
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)

TT_RE = re.compile(r"https?://(?:[\w-]+\.)?tiktok\.com/\S+", re.I)

logging.basicConfig(level=logging.INFO)
router = Router()

cache: dict[str, str] = {}              # url -> file_id (use sqlite/redis in production)
locks: dict[str, asyncio.Lock] = {}     # prevents downloading the same link twice in parallel


def rid(url: str) -> str:
    """Build a short stable inline result id from a URL (Telegram limit: 64 bytes)."""
    return hashlib.sha1(url.encode()).hexdigest()[:32]


# ---------- downloading ----------

def _pick_clean_format(info: dict) -> dict:
    """Pick the best non-watermarked video format, preferring H.264."""
    fmts = [
        f for f in info.get("formats", [])
        if f.get("vcodec") != "none"
        and "watermark" not in (f.get("format_note") or "").lower()
        and f.get("format_id") != "download"   # TikTok's "download" format is the watermarked one
    ]
    if not fmts:
        raise RuntimeError("no clean format found (photo post, or TikTok changed something again)")

    def score(f):
        vc = (f.get("vcodec") or "").lower()
        h264 = vc.startswith(("h264", "avc"))  # HEVC doesn't play on some Telegram clients
        return (h264, f.get("height") or 0, f.get("tbr") or 0)

    return max(fmts, key=score)


def _http() -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": UA, "Referer": "https://www.tiktok.com/"},
        follow_redirects=True,
        timeout=20,
    )


def resolve_url(url: str) -> str:
    """Follow short links (vm.tiktok.com/...) to the full post URL."""
    with _http() as c:
        return str(c.get(url).url)


def make_slideshow(url: str, outdir: str) -> tuple[str, dict]:
    """Download slideshow images + music and render them into an mp4 with ffmpeg."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is not installed, slideshows can't be rendered")

    with _http() as c:
        html = c.get(url).text
        m = re.search(
            r'<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__"[^>]*>(.*?)</script>', html, re.S
        )
        if not m:
            raise RuntimeError("couldn't find post data on the page")
        data = json.loads(m.group(1))
        try:
            item = data["__DEFAULT_SCOPE__"]["webapp.video-detail"]["itemInfo"]["itemStruct"]
            images = item["imagePost"]["images"]
        except (KeyError, TypeError):
            raise RuntimeError("unexpected page structure (TikTok changed something)")

        # Download images and normalize them to PNG: TikTok mixes jpeg/webp,
        # and ffmpeg's concat demuxer can't handle mixed formats in one list.
        img_paths = []
        for i, img in enumerate(images):
            urls = img["imageURL"]["urlList"]
            src = next((u for u in urls if "jpeg" in u or ".jpg" in u), urls[0])
            raw = os.path.join(outdir, f"{i:03}.raw")
            with open(raw, "wb") as f:
                f.write(c.get(src).content)
            png = os.path.join(outdir, f"{i:03}.png")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", raw, png], check=True)
            img_paths.append(png)

        audio = None
        music_url = (item.get("music") or {}).get("playUrl")
        if music_url:
            audio = os.path.join(outdir, "audio.mp3")
            with open(audio, "wb") as f:
                f.write(c.get(music_url).content)

    # ffmpeg concat list: each image shown SLIDE_SECONDS; last one repeated (concat quirk)
    list_path = os.path.join(outdir, "list.txt")
    with open(list_path, "w", encoding="utf-8") as f:
        for p in img_paths:
            f.write(f"file '{p}'\nduration {SLIDE_SECONDS}\n")
        f.write(f"file '{img_paths[-1]}'\n")

    out = os.path.join(outdir, "slideshow.mp4")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", list_path]
    if audio:
        cmd += ["-stream_loop", "-1", "-i", audio]  # loop music if slides are longer
    cmd += [
        "-vf", "scale=1080:1920:force_original_aspect_ratio=decrease,"
               "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black,fps=30,format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
    ]
    if audio:
        cmd += ["-c:a", "aac", "-b:a", "128k", "-shortest"]
    cmd += ["-movflags", "+faststart", out]
    subprocess.run(cmd, check=True)

    if os.path.getsize(out) > MAX_BYTES:
        raise RuntimeError("rendered slideshow is larger than 50 MB")
    duration = len(img_paths) * SLIDE_SECONDS
    return out, {"width": 1080, "height": 1920, "duration": duration}


def download(url: str, outdir: str) -> tuple[str, dict]:
    """Download a TikTok video (or render a slideshow) into outdir. Returns (file path, info dict)."""
    full_url = resolve_url(url)
    if "/photo/" in full_url:
        return make_slideshow(full_url, outdir)

    base = {"quiet": True, "noplaylist": True, "no_warnings": True}
    with yt_dlp.YoutubeDL(base) as ydl:
        info = ydl.extract_info(url, download=False)

    fmt = _pick_clean_format(info)
    opts = base | {
        "format": fmt["format_id"],
        "outtmpl": os.path.join(outdir, "%(id)s.%(ext)s"),
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        path = ydl.prepare_filename(info)

    if os.path.getsize(path) > MAX_BYTES:
        raise RuntimeError("video is larger than 50 MB, Bot API can't upload it")
    return path, info


async def get_file_id(bot: Bot, url: str) -> str:
    """Return a Telegram file_id for the video, downloading and uploading it if not cached."""
    if url in cache:
        return cache[url]
    lock = locks.setdefault(url, asyncio.Lock())
    async with lock:
        if url in cache:
            return cache[url]
        with tempfile.TemporaryDirectory() as tmp:
            path, info = await asyncio.to_thread(download, url, tmp)
            msg = await bot.send_video(
                STORAGE_CHAT_ID,
                FSInputFile(path),
                width=info.get("width"),
                height=info.get("height"),
                duration=int(info.get("duration") or 0) or None,
                supports_streaming=True,
                caption=url,
            )
        cache[url] = msg.video.file_id
        return cache[url]


# ---------- handlers ----------

@router.inline_query()
async def on_inline(q: InlineQuery):
    """Answer an inline query: cached video if available, otherwise a placeholder."""
    m = TT_RE.search(q.query)
    if not m:
        await q.answer([], cache_time=1, is_personal=True)
        return
    url = m.group(0)

    if url in cache:  # already downloaded, send the video right away
        await q.answer(
            [InlineQueryResultCachedVideo(id="c" + rid(url), video_file_id=cache[url], title="🎬 TikTok without watermark")],
            cache_time=300,
        )
        return

    await q.answer(
        [
            InlineQueryResultArticle(
                id=rid(url),
                title="📥 Download TikTok without watermark",
                description=url,
                input_message_content=InputTextMessageContent(message_text="⏳ Downloading video…"),
                # The keyboard is REQUIRED, otherwise chosen_inline_result has no inline_message_id
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[[InlineKeyboardButton(text="⏳ loading…", callback_data="noop")]]
                ),
            )
        ],
        cache_time=1,
        is_personal=True,
    )


@router.chosen_inline_result()
async def on_chosen(r: ChosenInlineResult, bot: Bot):
    """Once the placeholder is sent, download the video and swap it in."""
    if not r.inline_message_id or r.result_id.startswith("c"):
        return
    m = TT_RE.search(r.query)
    if not m:
        return
    try:
        file_id = await get_file_id(bot, m.group(0))
        await bot.edit_message_media(
            inline_message_id=r.inline_message_id,
            media=InputMediaVideo(media=file_id, supports_streaming=True),
        )
    except Exception as e:
        logging.exception("download failed")
        await bot.edit_message_text(inline_message_id=r.inline_message_id, text=f"❌ Failed: {e}")


@router.callback_query(lambda c: c.data == "noop")
async def noop(c: CallbackQuery):
    """Handle taps on the placeholder button."""
    await c.answer("Hang on, downloading 🙂")


async def main():
    bot = Bot(BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    await dp.start_polling(bot, allowed_updates=["inline_query", "chosen_inline_result", "callback_query"])


if __name__ == "__main__":
    asyncio.run(main())
