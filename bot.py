"""Telegram bot that downloads short videos.

Supported: TikTok (without watermark), YouTube Shorts and Instagram
Reels. The bot works inline in any chat, in private chats and in
groups.

Usage in any chat::

    @your_bot https://vm.tiktok.com/xxxx

Inline flow:

1. ``inline_query`` -- instantly return a placeholder with an inline
   keyboard (without a keyboard Telegram won't provide
   ``inline_message_id``).
2. ``chosen_inline_result`` -- download the video with yt-dlp and
   upload it to a private storage channel to obtain a ``file_id``.
3. ``edit_message_media`` -- replace the placeholder with the video.

Repeated requests for the same link are served from the ``file_id``
cache. TikTok photo slideshows are sent as a photo album in private
chats and groups. In inline mode they are rendered into an mp4
(images + original music) with ffmpeg, because an inline message can
hold only one media item, not an album.
"""

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import threading
from typing import Any, Awaitable, Callable

import httpx
import yt_dlp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatMemberStatus, ChatType, ParseMode
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNetworkError,
)
from aiogram.filters import (
    JOIN_TRANSITION,
    LEAVE_TRANSITION,
    ChatMemberUpdatedFilter,
    Command,
    CommandStart,
)
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    CallbackQuery,
    ChatMemberUpdated,
    ChosenInlineResult,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InlineQuery,
    InlineQueryResultArticle,
    InlineQueryResultCachedVideo,
    InputMediaPhoto,
    InputMediaVideo,
    InputTextMessageContent,
    Message,
    User,
)
from aiogram.utils.chat_action import ChatActionSender
from dotenv import load_dotenv

from texts import DEFAULT_LANG, LANG_NAMES, TEXTS, detect_lang, t

# ---------- configuration ----------

load_dotenv()
BOT_TOKEN = os.environ["BOT_TOKEN"]
# Private channel where the bot is an admin, id like -100...
STORAGE_CHAT_ID = int(os.environ["STORAGE_CHAT_ID"])

MAX_BYTES = 50 * 1024 * 1024  # Bot API upload limit
ALBUM_LIMIT = 10  # max photos in one Telegram album
ERROR_TTL = 15  # seconds before error messages in groups are deleted
SLOW_AFTER = 20  # seconds before "taking longer than usual"
DOWNLOAD_TIMEOUT = 120  # seconds before a download is given up
# Seconds to upload a file to Telegram. aiogram's default of 60 is too
# short for a 1080p video of tens of megabytes on a home connection.
UPLOAD_TIMEOUT = 300
SLIDE_SECONDS = 2.5  # how long each slideshow image is shown
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)

PLATFORM_PATTERNS = {
    "tiktok": r"https?://(?:[\w-]+\.)?tiktok\.com/\S+",
    # Only Shorts: regular YouTube videos rarely fit into 50 MB.
    "youtube": r"https?://(?:www\.|m\.)?youtube\.com/shorts/[\w-]+\S*",
    # Reels and video posts. Links may include the username:
    # instagram.com/<user>/reel/<id>
    "instagram": (
        r"https?://(?:www\.)?instagram\.com/"
        r"(?:[\w.]+/)?(?:reels?|p)/[\w-]+\S*"
    ),
}
LINK_RE = re.compile(
    "|".join(f"(?:{p})" for p in PLATFORM_PATTERNS.values()), re.I
)

# Optional cookies (Netscape cookies.txt format) for platforms that
# block anonymous access. Keep this folder out of git: cookies are as
# secret as a password.
COOKIES_DIR = "cookies"

# Persistent state that survives restarts. Keep it out of git: it is
# runtime data, not code.
STATE_FILE = "state.json"

ALLOWED_UPDATES = [
    "message",
    "inline_query",
    "chosen_inline_result",
    "callback_query",
    "my_chat_member",
]

logging.basicConfig(level=logging.INFO)
router = Router()

# ---------- runtime state ----------

# url -> Telegram file_id of the video (in memory)
cache: dict[str, str] = {}
# url -> Telegram file_ids of slideshow photos (in memory)
album_cache: dict[str, list[str]] = {}
# short url -> full url after redirects (in memory)
resolved: dict[str, str] = {}
# Prevents downloading the same link twice in parallel.
locks: dict[str, asyncio.Lock] = {}
# Running delayed deletions (kept so they aren't garbage-collected).
background_tasks: set[asyncio.Task] = set()
# Saved to STATE_FILE:
#   users: str(user_id) -> per-user settings, e.g. {"lang": "et"}
#   chats: str(chat_id) -> per-group settings set by admins
#   groups: str(chat_id) -> language of the group
#   restart_notices: str(chat_id) -> message_id of the notice
state: dict[str, dict[str, Any]] = {
    "users": {},
    "chats": {},
    "groups": {},
    "restart_notices": {},
}


class TooBigError(RuntimeError):
    """The file exceeds the Bot API upload limit."""


class DownloadTimeoutError(RuntimeError):
    """The download took longer than DOWNLOAD_TIMEOUT."""


def load_state():
    """Load the persistent state from STATE_FILE, if it exists."""
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            data = json.load(f)
        for key in state:
            state[key] = data.get(key, {})
    except FileNotFoundError:
        pass
    except Exception:
        logging.exception(
            "couldn't read %s, starting with empty state", STATE_FILE
        )


def save_state():
    """Save the persistent state to STATE_FILE atomically.

    The data is written to a temporary file first and then moved into
    place, so a crash in the middle never leaves a broken file.
    """
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)


def remember_group(chat_id: int, lang: str):
    """Add a group to the persistent list, if it isn't there yet."""
    if str(chat_id) not in state["groups"]:
        state["groups"][str(chat_id)] = lang
        save_state()


def user_settings(user_id: int) -> dict[str, Any]:
    """Return the saved settings of a user (empty if none)."""
    return state["users"].get(str(user_id), {})


def set_user_setting(user_id: int, key: str, value: Any):
    """Save one setting of a user to the persistent state."""
    state["users"].setdefault(str(user_id), {})[key] = value
    save_state()


def set_chat_setting(chat_id: int, key: str, value: Any):
    """Save one setting of a group to the persistent state."""
    state["chats"].setdefault(str(chat_id), {})[key] = value
    save_state()


def forget_group(chat_id: int):
    """Remove a group from the persistent list."""
    if state["groups"].pop(str(chat_id), None) is not None:
        save_state()


# ---------- helpers ----------


def lang_of(user: User | None) -> str:
    """Return the language to talk to a user in.

    A manual choice from /language wins; otherwise the language of the
    user's Telegram app is used.
    """
    if user is None:
        return DEFAULT_LANG
    saved = user_settings(user.id).get("lang")
    return saved if saved in TEXTS else detect_lang(user.language_code)


def group_lang(chat_id: int, user: User | None) -> str:
    """Return the language to talk in inside a group.

    A language set by the group admins wins; otherwise the language of
    the user the bot is answering is used.
    """
    saved = state["chats"].get(str(chat_id), {}).get("lang")
    return saved if saved in TEXTS else lang_of(user)


def delete_later(bot: Bot, chat_id: int, message_id: int):
    """Delete a message after ERROR_TTL seconds, in the background."""

    async def worker():
        """Wait, then delete; the message may already be gone."""
        await asyncio.sleep(ERROR_TTL)
        try:
            await bot.delete_message(chat_id, message_id)
        except Exception as e:
            logging.warning("couldn't delete message %s: %s", message_id, e)

    task = asyncio.create_task(worker())
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)


def error_text(lang: str, e: Exception) -> str:
    """Turn an exception into a friendly message for the user.

    Technical details go to the log, not to the chat.
    """
    if isinstance(e, TooBigError):
        return t(lang, "too_big")
    # A network error while uploading is almost always a timeout.
    if isinstance(e, (DownloadTimeoutError, TelegramNetworkError)):
        return t(lang, "timeout")
    return t(lang, "failed")


@contextlib.asynccontextmanager
async def slow_notice(action: Callable[[], Awaitable[Any]]):
    """Run `action` if the wrapped block takes longer than SLOW_AFTER.

    Used to change "Downloading..." into "taking longer than usual".
    The action is cancelled as soon as the block finishes.
    """

    async def worker():
        """Wait, then run the action; failures only get logged."""
        await asyncio.sleep(SLOW_AFTER)
        try:
            await action()
        except Exception as e:
            logging.warning("couldn't show the slow notice: %s", e)

    task = asyncio.create_task(worker())
    try:
        yield
    finally:
        task.cancel()


async def run_with_timeout(func: Callable, *args: Any) -> Any:
    """Run a blocking function in a thread, with DOWNLOAD_TIMEOUT.

    Python can't stop a running thread, so on timeout the work keeps
    going in the background, but the caller gets an answer right away.
    """
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(func, *args), DOWNLOAD_TIMEOUT
        )
    except asyncio.TimeoutError as e:
        raise DownloadTimeoutError(f"{func.__name__} timed out") from e


def platform_of(url: str) -> str:
    """Return the platform of a link: tiktok, youtube or instagram."""
    for name, pattern in PLATFORM_PATTERNS.items():
        if re.match(pattern, url, re.I):
            return name
    raise ValueError(f"unsupported link: {url}")


def cookies_for(platform: str) -> str | None:
    """Return the path to cookies/<platform>.txt, if it exists."""
    path = os.path.join(COOKIES_DIR, f"{platform}.txt")
    return path if os.path.isfile(path) else None


def result_id(url: str) -> str:
    """Build a short stable inline result id from a URL.

    Telegram limits inline result ids to 64 bytes.
    """
    return hashlib.sha1(url.encode()).hexdigest()[:32]


# ---------- downloading ----------


def _pick_clean_format(info: dict) -> dict:
    """Pick the best non-watermarked TikTok format, preferring H.264."""
    fmts = [
        f
        for f in info.get("formats", [])
        if f.get("vcodec") != "none"
        and "watermark" not in (f.get("format_note") or "").lower()
        # TikTok's "download" format is the watermarked one.
        and f.get("format_id") != "download"
    ]
    if not fmts:
        raise RuntimeError(
            "no clean format found (photo post, or TikTok changed "
            "something again)"
        )

    def score(f):
        """Rank a format: H.264 first, then height, then bitrate."""
        vcodec = (f.get("vcodec") or "").lower()
        # HEVC doesn't play on some Telegram clients.
        h264 = vcodec.startswith(("h264", "avc"))
        return h264, f.get("height") or 0, f.get("tbr") or 0

    return max(fmts, key=score)


def _http() -> httpx.Client:
    """Create an HTTP client that looks like a regular browser."""
    return httpx.Client(
        headers={
            "User-Agent": USER_AGENT,
            "Referer": "https://www.tiktok.com/",
        },
        follow_redirects=True,
        timeout=20,
    )


def resolve_url(url: str) -> str:
    """Follow short links (vm.tiktok.com/...) to the full post URL."""
    if url not in resolved:
        with _http() as c:
            resolved[url] = str(c.get(url).url)
    return resolved[url]


def is_slideshow(url: str) -> bool:
    """Check whether a link points to a TikTok photo slideshow."""
    return platform_of(url) == "tiktok" and "/photo/" in resolve_url(url)


def _page_json(html: str) -> list[dict]:
    """Extract the JSON data blobs embedded in a TikTok page.

    TikTok has used several formats over time, so all known ones are
    collected.
    """
    blobs = []
    for script_id in (
        "__UNIVERSAL_DATA_FOR_REHYDRATION__",
        "SIGI_STATE",
        "__NEXT_DATA__",
    ):
        m = re.search(
            rf'<script[^>]*id="{script_id}"[^>]*>(.*?)</script>', html, re.S
        )
        if m:
            try:
                blobs.append(json.loads(m.group(1)))
            except json.JSONDecodeError:
                logging.warning("couldn't parse %s JSON", script_id)
    return blobs


def _find_slideshows(obj: Any) -> list[dict]:
    """Find every post with slideshow images anywhere in the JSON.

    Searching the whole tree instead of a fixed path survives TikTok
    moving the data under a different key.
    """
    found = []
    stack = [obj]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            images = (node.get("imagePost") or {}).get("images")
            if isinstance(images, list) and images:
                found.append(node)
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return found


def _fetch_slideshow_item(c: httpx.Client, url: str) -> dict:
    """Return the post data of a TikTok photo slideshow.

    Try the /photo/ page first, then the same post as /video/: TikTok
    often serves slideshow data on the video page in the older format.
    The page may also list related posts, so the one whose id matches
    the link wins.
    """
    m = re.search(r"/(?:photo|video)/(\d+)", url)
    post_id = m.group(1) if m else None
    candidates = [url]
    if "/photo/" in url:
        candidates.append(url.replace("/photo/", "/video/", 1))

    seen_keys = []
    for page_url in candidates:
        for blob in _page_json(c.get(page_url).text):
            scope = blob.get("__DEFAULT_SCOPE__", blob)
            if isinstance(scope, dict):
                seen_keys.extend(scope.keys())
            posts = _find_slideshows(blob)
            for post in posts:
                if post_id is None or str(post.get("id")) == post_id:
                    return post
            if posts and post_id is None:
                return posts[0]

    # Log what the page did contain, so the next fix is quick.
    logging.warning(
        "no slideshow data for %s; page keys: %s",
        url,
        sorted(set(map(str, seen_keys))),
    )
    raise RuntimeError("couldn't find slideshow data on the page")


def _download_images(
    c: httpx.Client, item: dict, outdir: str, ext: str
) -> list[str]:
    """Download the slideshow images and convert them to one format.

    TikTok mixes jpeg and webp, so every image is converted with
    ffmpeg into the given format (e.g. "jpg" or "png").
    """
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is not installed")
    paths = []
    for i, img in enumerate(item["imagePost"]["images"]):
        urls = img["imageURL"]["urlList"]
        src = next((u for u in urls if "jpeg" in u or ".jpg" in u), urls[0])
        raw = os.path.join(outdir, f"{i:03}.raw")
        with open(raw, "wb") as f:
            f.write(c.get(src).content)
        out = os.path.join(outdir, f"{i:03}.{ext}")
        # -q:v 2 is high JPEG quality; ignored for PNG.
        subprocess.run(
            ["ffmpeg", "-y", "-loglevel", "error", "-i", raw]
            + ["-q:v", "2", out],
            check=True,
            timeout=DOWNLOAD_TIMEOUT,
        )
        paths.append(out)
    return paths


def download_slideshow_images(url: str, outdir: str) -> list[str]:
    """Download a TikTok slideshow as a list of JPEG files."""
    with _http() as c:
        item = _fetch_slideshow_item(c, resolve_url(url))
        return _download_images(c, item, outdir, "jpg")


def make_slideshow(url: str, outdir: str) -> tuple[str, dict]:
    """Render a TikTok photo slideshow into an mp4 with music.

    Return the path to the video and a dict with its width, height
    and duration.
    """
    if not shutil.which("ffmpeg"):
        raise RuntimeError(
            "ffmpeg is not installed, slideshows can't be rendered"
        )

    with _http() as c:
        item = _fetch_slideshow_item(c, url)
        # PNG: ffmpeg's concat demuxer can't handle mixed formats.
        img_paths = _download_images(c, item, outdir, "png")

        audio = None
        music_url = (item.get("music") or {}).get("playUrl")
        if music_url:
            audio = os.path.join(outdir, "audio.mp3")
            with open(audio, "wb") as f:
                f.write(c.get(music_url).content)

    # Each image becomes its own input, looped for SLIDE_SECONDS. Every
    # clip is scaled and padded to the same 1080x1920 frame and the
    # clips are joined with the concat filter. (The concat demuxer is
    # not used: with images of different sizes it shows only the last
    # one.)
    total = len(img_paths) * SLIDE_SECONDS
    cmd = ["ffmpeg", "-y", "-loglevel", "error"]
    for p in img_paths:
        cmd += ["-loop", "1", "-t", str(SLIDE_SECONDS), "-i", p]
    if audio:
        # Loop the music if the slides are longer than the track.
        cmd += ["-stream_loop", "-1", "-i", audio]

    frame = (
        "scale=1080:1920:force_original_aspect_ratio=decrease,"
        "pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black,"
        "setsar=1,fps=30,format=yuv420p"
    )
    parts = [f"[{i}:v]{frame}[v{i}]" for i in range(len(img_paths))]
    joined = "".join(f"[v{i}]" for i in range(len(img_paths)))
    parts.append(f"{joined}concat=n={len(img_paths)}:v=1:a=0[video]")
    cmd += ["-filter_complex", ";".join(parts), "-map", "[video]"]
    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"]
    if audio:
        audio_input = len(img_paths)
        cmd += ["-map", f"{audio_input}:a", "-c:a", "aac", "-b:a", "128k"]
    # An explicit length: the looped music would otherwise never end.
    out = os.path.join(outdir, "slideshow.mp4")
    cmd += ["-t", str(total), "-movflags", "+faststart", out]
    subprocess.run(cmd, check=True, timeout=DOWNLOAD_TIMEOUT)

    if os.path.getsize(out) > MAX_BYTES:
        raise TooBigError("rendered slideshow is larger than 50 MB")
    return out, {"width": 1080, "height": 1920, "duration": total}


def download(url: str, outdir: str) -> tuple[str, dict]:
    """Download a video from any supported platform into outdir.

    Return the path to the file and the info dict with its metadata.
    """
    platform = platform_of(url)
    if platform == "tiktok":
        return download_tiktok(url, outdir)
    return download_generic(url, outdir, platform)


def generic_opts(outdir: str, platform: str) -> dict:
    """Return yt-dlp options for YouTube Shorts and Instagram Reels."""
    opts = {
        "quiet": True,
        "noplaylist": True,
        "no_warnings": True,
        # "quiet" doesn't hide the progress bar, which floods the log.
        "noprogress": True,
        # Don't wait forever on a stalled connection.
        "socket_timeout": 30,
        "outtmpl": os.path.join(outdir, "%(id)s.%(ext)s"),
        "format": "bv*+ba/b",
        # Prefer H.264 + AAC: HEVC, AV1 and VP9 don't play on some
        # Telegram clients.
        "format_sort": ["vcodec:h264", "res:1080", "acodec:aac"],
        "merge_output_format": "mp4",
        # yt-dlp skips files that are known to be too big.
        "max_filesize": MAX_BYTES,
    }
    cookiefile = cookies_for(platform)
    if cookiefile:
        opts["cookiefile"] = cookiefile
    return opts


def download_generic(url: str, outdir: str, platform: str) -> tuple[str, dict]:
    """Download a YouTube Short or an Instagram Reel.

    Take the best H.264 mp4 up to 1080p, merged with the audio track.
    """
    with yt_dlp.YoutubeDL(generic_opts(outdir, platform)) as ydl:
        info = ydl.extract_info(url, download=True)
        downloads = info.get("requested_downloads") or [{}]
        path = downloads[0].get("filepath") or ydl.prepare_filename(info)

    # The file is missing if yt-dlp skipped it because of max_filesize.
    if not os.path.isfile(path):
        raise TooBigError("video is larger than 50 MB")
    if os.path.getsize(path) > MAX_BYTES:
        raise TooBigError(
            "video is larger than 50 MB, Bot API can't upload it"
        )
    return path, info


def download_tiktok(url: str, outdir: str) -> tuple[str, dict]:
    """Download a TikTok video without watermark.

    Photo slideshows are rendered into a video instead.
    """
    full_url = resolve_url(url)
    if "/photo/" in full_url:
        return make_slideshow(full_url, outdir)

    base = {
        "quiet": True,
        "noplaylist": True,
        "no_warnings": True,
        "noprogress": True,
        "socket_timeout": 30,
    }
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
        raise TooBigError(
            "video is larger than 50 MB, Bot API can't upload it"
        )
    return path, info


async def get_file_id(bot: Bot, url: str) -> str:
    """Return a Telegram file_id for the video behind a link.

    On a cache miss, download the video and upload it to the storage
    channel first.
    """
    if url in cache:
        return cache[url]
    lock = locks.setdefault(url, asyncio.Lock())
    async with lock:
        if url in cache:
            return cache[url]
        # A timed-out download may still hold its files open.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path, info = await run_with_timeout(download, url, tmp)
            msg = await bot.send_video(
                STORAGE_CHAT_ID,
                FSInputFile(path),
                width=info.get("width"),
                height=info.get("height"),
                duration=int(info.get("duration") or 0) or None,
                supports_streaming=True,
                caption=url,
                # URLs may contain "&", which would break HTML parsing.
                parse_mode=None,
                request_timeout=UPLOAD_TIMEOUT,
            )
        if msg.video is None:
            raise RuntimeError("Telegram didn't return the uploaded video")
        cache[url] = msg.video.file_id
        return cache[url]


def chunks(items: list, size: int = ALBUM_LIMIT) -> list[list]:
    """Split a list into parts of at most `size` items."""
    return [items[i : i + size] for i in range(0, len(items), size)]


async def get_album_ids(bot: Bot, url: str) -> list[str]:
    """Return Telegram file_ids for the photos of a slideshow.

    On a cache miss, download the images and upload them to the
    storage channel first.
    """
    if url in album_cache:
        return album_cache[url]
    lock = locks.setdefault("album:" + url, asyncio.Lock())
    async with lock:
        if url in album_cache:
            return album_cache[url]
        file_ids = []
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            paths = await run_with_timeout(download_slideshow_images, url, tmp)
            for part in chunks(paths):
                # A caption on the first item is shown under the whole
                # album. parse_mode=None: URLs may contain "&".
                media = [
                    InputMediaPhoto(
                        media=FSInputFile(p),
                        caption=url if i == 0 else None,
                        parse_mode=None,
                    )
                    for i, p in enumerate(part)
                ]
                sent = await bot.send_media_group(
                    STORAGE_CHAT_ID, media, request_timeout=UPLOAD_TIMEOUT
                )
                # The last PhotoSize is the largest one.
                file_ids += [m.photo[-1].file_id for m in sent if m.photo]
        if not file_ids:
            raise RuntimeError("Telegram didn't return the uploaded photos")
        album_cache[url] = file_ids
        return file_ids


async def reply_with_media(bot: Bot, msg: Message, url: str):
    """Reply to a message with the media behind a link.

    Slideshows come as photo albums (without sound), everything else
    as a video.
    """
    if await asyncio.to_thread(is_slideshow, url):
        for part in chunks(await get_album_ids(bot, url)):
            if len(part) == 1:
                await msg.reply_photo(part[0])
            else:
                await msg.reply_media_group(
                    [InputMediaPhoto(media=file_id) for file_id in part]
                )
        return
    file_id = await get_file_id(bot, url)
    await msg.reply_video(file_id, supports_streaming=True)


# ---------- handlers: private chat ----------

private = F.chat.type == ChatType.PRIVATE


@router.message(CommandStart(), private)
async def on_start(msg: Message, bot: Bot):
    """Greet the user and explain how to use the bot."""
    lang = lang_of(msg.from_user)
    me = await bot.me()
    # The button opens the chat picker with "@bot " already typed in.
    try_button = InlineKeyboardButton(
        text=t(lang, "try_button"), switch_inline_query=""
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[try_button]])
    await msg.answer(t(lang, "start", bot=me.username), reply_markup=kb)


@router.message(Command("language"), private)
async def on_language(msg: Message):
    """Show the language picker."""
    lang = lang_of(msg.from_user)
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=name, callback_data=f"lang:{code}")]
            for code, name in LANG_NAMES.items()
        ]
    )
    await msg.answer(t(lang, "choose_lang"), reply_markup=kb)


@router.callback_query(F.data.startswith("lang:"))
async def on_language_chosen(c: CallbackQuery):
    """Save the chosen language and confirm it."""
    code = (c.data or "").split(":", 1)[-1]
    if code not in TEXTS:
        await c.answer()
        return
    set_user_setting(c.from_user.id, "lang", code)
    # Messages older than 48 hours come as InaccessibleMessage and
    # can't be edited; confirm with a popup instead.
    if isinstance(c.message, Message):
        await c.message.edit_text(t(code, "lang_set"))
        await c.answer()
    else:
        await c.answer(t(code, "lang_set"))


@router.message(F.text.regexp(LINK_RE, mode="search"), private)
async def on_link(msg: Message, bot: Bot):
    """Reply with the media to a link sent directly to the bot."""
    lang = lang_of(msg.from_user)
    url = LINK_RE.search(msg.text).group(0)
    status = await msg.reply(t(lang, "downloading"))
    try:
        async with slow_notice(lambda: status.edit_text(t(lang, "slow"))):
            await reply_with_media(bot, msg, url)
    except Exception as e:
        logging.exception("download failed: %s", url)
        # In private chats the error stays, so the user can see what
        # happened with their link.
        await status.edit_text(error_text(lang, e))
        return
    # The video is already sent, so failing to clean up isn't an error.
    try:
        await status.delete()
    except Exception:
        logging.warning("couldn't delete status message")


@router.message(private)
async def on_other(msg: Message):
    """Hint that a link is expected in private chat."""
    await msg.answer(t(lang_of(msg.from_user), "no_link"))


# ---------- handlers: groups ----------

group = F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP})


@router.message.outer_middleware()
async def track_groups(
    handler: Callable[[Message, dict], Awaitable[Any]],
    msg: Message,
    data: dict,
) -> Any:
    """Remember every group the bot sees messages from.

    This also covers groups the bot joined before group tracking
    existed.
    """
    if msg.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        remember_group(msg.chat.id, lang_of(msg.from_user))
    return await handler(msg, data)


@router.message(
    F.text.regexp(LINK_RE, mode="search"),
    group,
    # Messages sent through inline mode are already handled.
    F.via_bot.is_(None),
)
async def on_group_link(msg: Message, bot: Bot):
    """Reply with the media to a link posted in a group.

    No "Downloading..." text here to keep the chat clean: the "sending
    video..." status at the top of the chat shows that the bot works.
    """
    url = LINK_RE.search(msg.text).group(0)
    try:
        async with ChatActionSender.upload_video(bot=bot, chat_id=msg.chat.id):
            await reply_with_media(bot, msg, url)
    except Exception as e:
        logging.exception("download failed: %s", url)
        lang = group_lang(msg.chat.id, msg.from_user)
        error = await msg.reply(error_text(lang, e))
        delete_later(bot, error.chat.id, error.message_id)


async def is_group_admin(bot: Bot, chat_id: int, user: User | None) -> bool:
    """Check whether a user is an owner or admin of a group."""
    if user is None:
        return False
    member = await bot.get_chat_member(chat_id, user.id)
    return member.status in (
        ChatMemberStatus.CREATOR,
        ChatMemberStatus.ADMINISTRATOR,
    )


async def is_admin_message(bot: Bot, msg: Message) -> bool:
    """Check whether a group message comes from an admin.

    Anonymous admins post on behalf of the group itself.
    """
    if msg.sender_chat is not None and msg.sender_chat.id == msg.chat.id:
        return True
    return await is_group_admin(bot, msg.chat.id, msg.from_user)


@router.message(Command("language"), group)
async def on_group_language(msg: Message, bot: Bot):
    """Show the group language picker to admins."""
    lang = group_lang(msg.chat.id, msg.from_user)
    if not await is_admin_message(bot, msg):
        reply = await msg.reply(t(lang, "admins_only"))
        delete_later(bot, reply.chat.id, reply.message_id)
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=name, callback_data=f"glang:{code}")]
            for code, name in LANG_NAMES.items()
        ]
    )
    await msg.reply(t(lang, "choose_group_lang"), reply_markup=kb)


@router.callback_query(F.data.startswith("glang:"))
async def on_group_language_chosen(c: CallbackQuery, bot: Bot):
    """Save the group language if an admin pressed the button."""
    code = (c.data or "").split(":", 1)[-1]
    if code not in TEXTS or not isinstance(c.message, Message):
        await c.answer()
        return
    chat_id = c.message.chat.id
    # Anyone in the group can press the buttons, so check again.
    if not await is_group_admin(bot, chat_id, c.from_user):
        await c.answer(t(lang_of(c.from_user), "admins_only"), show_alert=True)
        return
    set_chat_setting(chat_id, "lang", code)
    # Restart notices use the group language too.
    state["groups"][str(chat_id)] = code
    save_state()
    await c.message.edit_text(t(code, "group_lang_set"))
    await c.answer()


@router.my_chat_member(
    group,
    ChatMemberUpdatedFilter(member_status_changed=JOIN_TRANSITION),
)
async def on_added_to_group(event: ChatMemberUpdated, bot: Bot):
    """Say hi when added to a group.

    Also warn if the bot can't see regular messages there.
    """
    # The group language, or that of the person who added the bot.
    lang = group_lang(event.chat.id, event.from_user)
    remember_group(event.chat.id, lang)
    # Fresh data, not bot.me(): privacy mode may have been changed
    # while the bot was running.
    me = await bot.get_me()
    is_admin = event.new_chat_member.status == ChatMemberStatus.ADMINISTRATOR
    text = t(lang, "group_hello") + t(lang, "group_lang_hint")
    if not me.can_read_all_group_messages and not is_admin:
        text += t(lang, "group_need_access")
    await bot.send_message(event.chat.id, text)


@router.my_chat_member(
    group,
    ChatMemberUpdatedFilter(member_status_changed=LEAVE_TRANSITION),
)
async def on_removed_from_group(event: ChatMemberUpdated):
    """Stop sending restart notices to a group the bot has left."""
    forget_group(event.chat.id)


# ---------- handlers: inline mode ----------


@router.inline_query()
async def on_inline(q: InlineQuery):
    """Answer an inline query with the video or a placeholder.

    A cached video is sent right away; otherwise a placeholder is
    returned and replaced once the user sends it.
    """
    lang = lang_of(q.from_user)
    m = LINK_RE.search(q.query)
    if not m:
        await q.answer([], cache_time=1, is_personal=True)
        return
    url = m.group(0)

    if url in cache:
        cached = InlineQueryResultCachedVideo(
            id="c" + result_id(url),
            video_file_id=cache[url],
            title=t(lang, "cached_title"),
        )
        await q.answer([cached], cache_time=1, is_personal=True)
        return

    placeholder = InlineQueryResultArticle(
        id=result_id(url),
        title=t(lang, "inline_title"),
        description=url,
        input_message_content=InputTextMessageContent(
            message_text=t(lang, "downloading")
        ),
        # The keyboard is required: without it chosen_inline_result
        # has no inline_message_id.
        reply_markup=loading_keyboard(lang),
    )
    await q.answer([placeholder], cache_time=1, is_personal=True)


def loading_keyboard(lang: str) -> InlineKeyboardMarkup:
    """Build the "loading..." button shown on the inline placeholder."""
    button = InlineKeyboardButton(
        text=t(lang, "loading_button"), callback_data="noop"
    )
    return InlineKeyboardMarkup(inline_keyboard=[[button]])


@router.chosen_inline_result()
async def on_chosen(r: ChosenInlineResult, bot: Bot):
    """Swap the placeholder for the video once it is sent."""
    if not r.inline_message_id or r.result_id.startswith("c"):
        return
    m = LINK_RE.search(r.query)
    if not m:
        return
    lang = lang_of(r.from_user)

    def show_slow():
        """Replace "Downloading..." with "taking longer than usual"."""
        return bot.edit_message_text(
            inline_message_id=r.inline_message_id,
            text=t(lang, "slow"),
            reply_markup=loading_keyboard(lang),
        )

    try:
        async with slow_notice(show_slow):
            file_id = await get_file_id(bot, m.group(0))
        await bot.edit_message_media(
            inline_message_id=r.inline_message_id,
            media=InputMediaVideo(media=file_id, supports_streaming=True),
        )
    except Exception as e:
        logging.exception("download failed: %s", m.group(0))
        await bot.edit_message_text(
            inline_message_id=r.inline_message_id, text=error_text(lang, e)
        )


@router.callback_query(F.data == "noop")
async def on_placeholder_tap(c: CallbackQuery):
    """Handle taps on the placeholder button."""
    await c.answer(t(lang_of(c.from_user), "hang_on"))


# ---------- startup and shutdown ----------


async def post_restart_notices(bot: Bot):
    """Tell every group that the bot is restarting.

    The message ids are saved so the next run can delete them.
    """
    for chat_id, lang in list(state["groups"].items()):
        try:
            msg = await bot.send_message(int(chat_id), t(lang, "restarting"))
            state["restart_notices"][chat_id] = msg.message_id
        except (TelegramForbiddenError, TelegramBadRequest) as e:
            # Kicked, group deleted, or no right to write: no point
            # in trying again.
            logging.warning("dropping group %s: %s", chat_id, e)
            state["groups"].pop(chat_id, None)
        except Exception:
            logging.exception("couldn't post restart notice to %s", chat_id)
        # Stay well under Telegram's rate limits.
        await asyncio.sleep(0.05)
    save_state()


async def delete_restart_notices(bot: Bot):
    """Delete the "restarting" messages left by the previous run."""
    for chat_id, message_id in list(state["restart_notices"].items()):
        try:
            await bot.delete_message(int(chat_id), message_id)
        except Exception as e:
            logging.warning(
                "couldn't delete restart notice in %s: %s", chat_id, e
            )
    state["restart_notices"] = {}
    save_state()


async def setup_bot_profile(bot: Bot):
    """Set the command menu in every language.

    Telegram shows the version matching the user's app language. The
    default language is registered without language_code, as a
    fallback for everyone else.
    """
    for code in TEXTS:
        lang_code = None if code == DEFAULT_LANG else code
        commands = [
            BotCommand(command="start", description=t(code, "cmd_start")),
            BotCommand(
                command="language", description=t(code, "cmd_language")
            ),
        ]
        await bot.set_my_commands(commands, language_code=lang_code)
        # In groups only /language makes sense.
        await bot.set_my_commands(
            [
                BotCommand(
                    command="language",
                    description=t(code, "cmd_group_language"),
                )
            ],
            scope=BotCommandScopeAllGroupChats(),
            language_code=lang_code,
        )


def fit(text: str, limit: int) -> str:
    """Cut a text to a Telegram length limit, adding "..." if needed.

    Telegram counts UTF-16 code units, so an emoji takes two.
    """

    def size(s: str) -> int:
        """Return the length of a text in UTF-16 code units."""
        return len(s.encode("utf-16-le")) // 2

    if size(text) <= limit:
        return text
    while size(text + "…") > limit:
        text = text[:-1]
    return text.rstrip() + "…"


async def set_profile_status(bot: Bot, online: bool):
    """Show whether the bot is running in its profile texts.

    The status goes in front of the short description (bot profile,
    share links) and the description (empty chat before Start). A hard
    crash skips the update, so the profile may still say "online".
    Errors are only logged: a failed update must never stop the bot.
    """
    status_key = "status_online" if online else "status_offline"
    try:
        me = await bot.me()
        for code in TEXTS:
            lang_code = None if code == DEFAULT_LANG else code
            status = t(code, status_key)
            description = t(code, "bot_description", bot=me.username)
            await bot.set_my_description(
                fit(status + "\n\n" + description, 512),
                language_code=lang_code,
            )
            short = t(code, "bot_short_description")
            await bot.set_my_short_description(
                fit(status + " · " + short, 120), language_code=lang_code
            )
    except Exception:
        logging.exception("couldn't update the profile status")


async def on_startup(bot: Bot):
    """Clean up after the previous run and show the bot as online."""
    await delete_restart_notices(bot)
    await set_profile_status(bot, online=True)


async def on_shutdown(bot: Bot):
    """Warn the groups and show the bot as offline."""
    await post_restart_notices(bot)
    await set_profile_status(bot, online=False)


def start_console(dp: Dispatcher, loop: asyncio.AbstractEventLoop):
    """Read commands from the terminal in a background thread.

    Typing "stop" shuts the bot down gracefully. A daemon thread is
    used so that a blocked input() never keeps the process alive after
    Ctrl+C.
    """

    def worker():
        """Wait for commands until "stop" or the end of input."""
        while True:
            try:
                cmd = input().strip().lower()
            except (EOFError, KeyboardInterrupt):
                # No interactive terminal (e.g. running as a service).
                return
            if cmd in ("stop", "exit", "quit"):
                logging.info("stopping bot...")
                asyncio.run_coroutine_threadsafe(dp.stop_polling(), loop)
                return
            if cmd:
                print("Unknown command. Available: stop")

    threading.Thread(target=worker, daemon=True).start()


async def main():
    """Start the bot and run it until it is stopped."""
    bot = Bot(
        BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher()
    dp.include_router(router)
    load_state()
    dp.startup.register(on_startup)
    # Runs on "stop", Ctrl+C and normal exit, but not on a hard crash.
    dp.shutdown.register(on_shutdown)
    print("Bot is running. Type 'stop' to shut it down.")
    start_console(dp, asyncio.get_running_loop())
    try:
        await setup_bot_profile(bot)
        await dp.start_polling(bot, allowed_updates=ALLOWED_UPDATES)
    finally:
        await bot.session.close()
        logging.info("bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
