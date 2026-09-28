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
"""
import asyncio
import hashlib
import logging
import os
import re
import tempfile

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


def download(url: str, outdir: str) -> tuple[str, dict]:
    """Download a TikTok video into outdir. Returns (file path, yt-dlp info dict)."""
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
