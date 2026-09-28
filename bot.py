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
import threading

import httpx
import yt_dlp
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatMemberStatus, ChatType, ParseMode
from aiogram.filters import JOIN_TRANSITION, ChatMemberUpdatedFilter, Command, CommandStart
from aiogram.utils.chat_action import ChatActionSender
from aiogram.types import (
    BotCommand,
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
    ChatMemberUpdated,
    Message,
    User,
)

from texts import DEFAULT_LANG, LANG_NAMES, TEXTS, detect_lang, t

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


user_langs: dict[int, str] = {}         # user_id -> language chosen via /language (in memory)


class TooBigError(RuntimeError):
    """The file exceeds the Bot API upload limit."""


def lang_of(user: User | None) -> str:
    """Language for a user: manual choice from /language, otherwise their Telegram app language."""
    if user is None:
        return DEFAULT_LANG
    return user_langs.get(user.id) or detect_lang(user.language_code)


def error_text(lang: str, e: Exception) -> str:
    """Turn an exception into a friendly message. Details go to the log, not to the user."""
    return t(lang, "too_big" if isinstance(e, TooBigError) else "failed")


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
        raise TooBigError("rendered slideshow is larger than 50 MB")
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
        raise TooBigError("video is larger than 50 MB, Bot API can't upload it")
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
                parse_mode=None,  # URLs may contain "&", which would break HTML parsing
            )
        cache[url] = msg.video.file_id
        return cache[url]


# ---------- handlers: private chat ----------

private = F.chat.type == ChatType.PRIVATE


@router.message(CommandStart(), private)
async def on_start(msg: Message, bot: Bot):
    """Greet the user and explain how to use the bot."""
    lang = lang_of(msg.from_user)
    me = await bot.me()
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        # Opens the chat picker with "@bot " already typed in
        InlineKeyboardButton(text=t(lang, "try_button"), switch_inline_query=""),
    ]])
    await msg.answer(t(lang, "start", bot=me.username), reply_markup=kb)


@router.message(Command("language"), private)
async def on_language(msg: Message):
    """Show language picker buttons."""
    lang = lang_of(msg.from_user)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=name, callback_data=f"lang:{code}")]
        for code, name in LANG_NAMES.items()
    ])
    await msg.answer(t(lang, "choose_lang"), reply_markup=kb)


@router.callback_query(F.data.startswith("lang:"))
async def on_language_chosen(c: CallbackQuery):
    """Save the chosen language and confirm it."""
    code = c.data.split(":", 1)[1]
    if code not in TEXTS:
        await c.answer()
        return
    user_langs[c.from_user.id] = code
    await c.message.edit_text(t(code, "lang_set"))
    await c.answer()


@router.message(F.text.regexp(TT_RE, mode="search"), private)
async def on_link(msg: Message, bot: Bot):
    """A TikTok link sent directly to the bot: download and reply with the video."""
    lang = lang_of(msg.from_user)
    url = TT_RE.search(msg.text).group(0)
    status = await msg.reply(t(lang, "downloading"))
    try:
        file_id = await get_file_id(bot, url)
        await msg.reply_video(file_id, supports_streaming=True)
    except Exception as e:
        logging.exception("download failed: %s", url)
        await status.edit_text(error_text(lang, e))
        return
    try:
        await status.delete()  # the video is already sent; failing to clean up isn't an error
    except Exception:
        logging.warning("couldn't delete status message")


@router.message(private)
async def on_other(msg: Message):
    """Anything else in private chat: hint that a link is expected."""
    await msg.answer(t(lang_of(msg.from_user), "no_link"))


# ---------- handlers: groups ----------

group = F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP})


@router.message(
    F.text.regexp(TT_RE, mode="search"),
    group,
    F.via_bot.is_(None),  # ignore messages sent through inline mode (they're already handled)
)
async def on_group_link(msg: Message, bot: Bot):
    """A TikTok link posted in a group: reply to that message with the video.

    No "Downloading…" text here to keep the chat clean; the "sending video…" status
    at the top of the chat shows that the bot is working.
    """
    url = TT_RE.search(msg.text).group(0)
    try:
        async with ChatActionSender.upload_video(bot=bot, chat_id=msg.chat.id):
            file_id = await get_file_id(bot, url)
        await msg.reply_video(file_id, supports_streaming=True)
    except Exception as e:
        logging.exception("download failed: %s", url)
        await msg.reply(error_text(lang_of(msg.from_user), e))


@router.my_chat_member(
    group,
    ChatMemberUpdatedFilter(member_status_changed=JOIN_TRANSITION),
)
async def on_added_to_group(event: ChatMemberUpdated, bot: Bot):
    """Say hi when added to a group, and warn if the bot can't see regular messages."""
    lang = lang_of(event.from_user)  # the person who added the bot
    me = await bot.get_me()  # fresh, not cached: privacy mode may have been changed while running
    is_admin = event.new_chat_member.status == ChatMemberStatus.ADMINISTRATOR
    text = t(lang, "group_hello")
    if not me.can_read_all_group_messages and not is_admin:
        text += t(lang, "group_need_access")
    await bot.send_message(event.chat.id, text)


# ---------- handlers: inline mode ----------

@router.inline_query()
async def on_inline(q: InlineQuery):
    """Answer an inline query: cached video if available, otherwise a placeholder."""
    lang = lang_of(q.from_user)
    m = TT_RE.search(q.query)
    if not m:
        await q.answer([], cache_time=1, is_personal=True)
        return
    url = m.group(0)

    if url in cache:  # already downloaded, send the video right away
        await q.answer(
            [InlineQueryResultCachedVideo(
                id="c" + rid(url), video_file_id=cache[url], title=t(lang, "cached_title"),
            )],
            cache_time=1,
            is_personal=True,
        )
        return

    await q.answer(
        [
            InlineQueryResultArticle(
                id=rid(url),
                title=t(lang, "inline_title"),
                description=url,
                input_message_content=InputTextMessageContent(message_text=t(lang, "downloading")),
                # The keyboard is REQUIRED, otherwise chosen_inline_result has no inline_message_id
                reply_markup=InlineKeyboardMarkup(
                    inline_keyboard=[[InlineKeyboardButton(text=t(lang, "loading_button"), callback_data="noop")]]
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
    lang = lang_of(r.from_user)
    try:
        file_id = await get_file_id(bot, m.group(0))
        await bot.edit_message_media(
            inline_message_id=r.inline_message_id,
            media=InputMediaVideo(media=file_id, supports_streaming=True),
        )
    except Exception as e:
        logging.exception("download failed: %s", m.group(0))
        await bot.edit_message_text(inline_message_id=r.inline_message_id, text=error_text(lang, e))


@router.callback_query(F.data == "noop")
async def noop(c: CallbackQuery):
    """Handle taps on the placeholder button."""
    await c.answer(t(lang_of(c.from_user), "hang_on"))


async def set_commands(bot: Bot):
    """Register the command menu in every supported language (Telegram picks by app language)."""
    for code in TEXTS:
        commands = [
            BotCommand(command="start", description=t(code, "cmd_start")),
            BotCommand(command="language", description=t(code, "cmd_language")),
        ]
        # The default language is also registered without language_code, as a fallback for everyone else
        await bot.set_my_commands(commands, language_code=None if code == DEFAULT_LANG else code)


def start_console(dp: Dispatcher, loop: asyncio.AbstractEventLoop):
    """Read commands from the terminal in a daemon thread. Type 'stop' to shut the bot down.

    A daemon thread is used so a blocked input() never keeps the process alive after Ctrl+C.
    """
    def worker():
        while True:
            try:
                cmd = input().strip().lower()
            except (EOFError, KeyboardInterrupt):
                return  # no interactive terminal (e.g. running as a service) — just ignore
            if cmd in ("stop", "exit", "quit"):
                logging.info("stopping bot...")
                asyncio.run_coroutine_threadsafe(dp.stop_polling(), loop)
                return
            if cmd:
                print("Unknown command. Available: stop")

    threading.Thread(target=worker, daemon=True).start()


async def main():
    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    print("Bot is running. Type 'stop' to shut it down.")
    start_console(dp, asyncio.get_running_loop())
    try:
        await set_commands(bot)
        await dp.start_polling(
            bot,
            allowed_updates=["message", "inline_query", "chosen_inline_result", "callback_query", "my_chat_member"],
        )
    finally:
        await bot.session.close()
        logging.info("bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
