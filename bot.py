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
import html
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from typing import Any, Awaitable, Callable

import httpx
import yt_dlp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatMemberStatus, ChatType, ParseMode
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramMigrateToChat,
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
    Chat,
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
    LinkPreviewOptions,
    Message,
    ReactionTypeEmoji,
    ReplyParameters,
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

REPO_URL = "https://github.com/artemi372/pastemedia-bot"
MAX_BYTES = 50 * 1024 * 1024  # Bot API upload limit
ALBUM_LIMIT = 10  # max photos in one Telegram album
# Reactions on the message with a link. Bots can only use Telegram's
# standard reaction emoji.
REACTION_WORKING = "👀"
REACTION_FAILED = "🤷"
# What to do with a group message that has a link, set by admins with
# /cleanup. Only "keep" replies to it; the others delete it and send
# the media as a separate message with an optional caption.
CLEANUP_MODES = ("keep", "link_user", "user", "none")
ERROR_TTL = 15  # seconds before error messages in groups are deleted
SLOW_AFTER = 20  # seconds before "taking longer than usual"
DOWNLOAD_TIMEOUT = 120  # seconds before a download is given up
# Seconds to upload a file to Telegram. aiogram's default of 60 is too
# short for a 1080p video of tens of megabytes on a home connection.
UPLOAD_TIMEOUT = 300
# If a video that is among the last RECENT_LIMIT ones in a group, and
# not older than RECENT_MAX_AGE seconds, is posted again, the bot
# points to the earlier message instead of sending it once more.
RECENT_LIMIT = 50
RECENT_MAX_AGE = 7 * 24 * 60 * 60

# How the bot is being stopped: "shutdown" (off for a while, the
# default, also for Ctrl+C) or "restart" (back in a few seconds).
stop_mode = "shutdown"
# True after "stop quiet" / "restart quiet": no messages in groups.
quiet_stop = False
# Exit code that asks the supervisor to start the bot again.
RESTART_EXIT_CODE = 3
# Set in the bot process started by the supervisor.
CHILD_ENV = "PASTEMEDIA_BOT_CHILD"
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
# url -> album items as (kind, file_id), kind is "photo" or "video"
album_cache: dict[str, list[tuple[str, str]]] = {}
# Instagram post url -> its files as listed by gallery-dl (in memory)
instagram_posts: dict[str, list[dict]] = {}
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
    # chat id -> {media key: [message id, unix time]}, oldest first.
    "recent": {},
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


def cleanup_mode(chat_id: int | str) -> str:
    """Return the /cleanup mode of a group ("keep" by default)."""
    mode = state["chats"].get(str(chat_id), {}).get("cleanup", "keep")
    return mode if mode in CLEANUP_MODES else "keep"


def notices_enabled(chat_id: int | str) -> bool:
    """Tell whether a group wants restart and shutdown notices.

    They are on by default; group admins can turn them off with
    /notices.
    """
    return state["chats"].get(str(chat_id), {}).get("notices", True)


def forget_group(chat_id: int):
    """Remove a group from the persistent list."""
    if state["groups"].pop(str(chat_id), None) is not None:
        save_state()


def move_chat(old_id: int | str, new_id: int | str):
    """Carry a group's data over to its new id.

    When a group becomes a supergroup (for example, after an admin
    changes some of its settings), Telegram gives it a new id, and
    everything saved under the old one would be lost.
    """
    old_id, new_id = str(old_id), str(new_id)
    changed = False
    for key in ("chats", "groups", "recent", "restart_notices"):
        old = state[key].pop(old_id, None)
        if old is None:
            continue
        changed = True
        if key == "restart_notices":
            continue  # that message stays in the old chat
        new = state[key].get(new_id)
        if isinstance(old, dict) and isinstance(new, dict):
            # Settings made in the new chat win.
            state[key][new_id] = {**old, **new}
        elif new is None:
            state[key][new_id] = old
    if changed:
        logging.info("group %s is now %s, settings moved", old_id, new_id)
        save_state()


def earlier_post(chat_id: int, key: str) -> int | None:
    """Return the id of a recent message with the same media, if any."""
    entry = state["recent"].get(str(chat_id), {}).get(key)
    if entry and time.time() - entry[1] < RECENT_MAX_AGE:
        return entry[0]
    return None


def remember_post(chat_id: int, key: str, message_id: int):
    """Save the message with some media as the latest one in a chat."""
    recent = state["recent"].setdefault(str(chat_id), {})
    recent.pop(key, None)  # move it to the end, as the newest
    recent[key] = [message_id, int(time.time())]
    while len(recent) > RECENT_LIMIT:
        del recent[next(iter(recent))]
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


def is_instagram_post(url: str) -> bool:
    """Check whether a link is an Instagram post (/p/), not a Reel.

    Posts can be carousels of photos and videos; Reels are single
    videos and go through yt-dlp like YouTube Shorts.
    """
    return platform_of(url) == "instagram" and "/p/" in url


def is_album(url: str) -> bool:
    """Check whether a link should be sent as an album.

    That's a TikTok photo slideshow or an Instagram post (a carousel,
    or a single photo or video, which is just an album of one).
    """
    platform = platform_of(url)
    if platform == "tiktok":
        return "/photo/" in resolve_url(url)
    return is_instagram_post(url)


def media_key(url: str) -> str:
    """Return a key that is the same for every link to one post.

    For example, a vm.tiktok.com short link and the full link it
    leads to, or an Instagram /reel/ and /p/ link with the same code,
    give the same key.
    """
    platform = platform_of(url)
    full = url
    if platform == "tiktok":
        with contextlib.suppress(Exception):
            full = resolve_url(url)
    m = re.search(r"/(?:video|photo|shorts|reels?|p)/([\w-]+)", full)
    if m:
        return f"{platform}:{m.group(1)}"
    return full.split("?")[0].rstrip("/")


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


def convert_image(raw: str, out: str):
    """Convert an image of any format (jpeg, webp...) with ffmpeg.

    The output format comes from the extension of `out`.
    """
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is not installed")
    # -q:v 2 is high JPEG quality; ignored for PNG.
    subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", raw] + ["-q:v", "2", out],
        check=True,
        timeout=DOWNLOAD_TIMEOUT,
    )


def _download_images(
    c: httpx.Client, item: dict, outdir: str, ext: str
) -> list[str]:
    """Download the slideshow images and convert them to one format.

    TikTok mixes jpeg and webp, so every image is converted with
    ffmpeg into the given format (e.g. "jpg" or "png").
    """
    paths = []
    for i, img in enumerate(item["imagePost"]["images"]):
        urls = img["imageURL"]["urlList"]
        src = next((u for u in urls if "jpeg" in u or ".jpg" in u), urls[0])
        raw = os.path.join(outdir, f"{i:03}.raw")
        with open(raw, "wb") as f:
            f.write(c.get(src).content)
        out = os.path.join(outdir, f"{i:03}.{ext}")
        convert_image(raw, out)
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
    return render_slideshow(img_paths, audio, outdir)


def render_slideshow(
    img_paths: list[str], audio: str | None, outdir: str
) -> tuple[str, dict]:
    """Render images (and optional music) into a 1080x1920 mp4.

    Each image is shown SLIDE_SECONDS. Return the path to the video and
    a dict with its width, height and duration.
    """
    if not shutil.which("ffmpeg"):
        raise RuntimeError(
            "ffmpeg is not installed, slideshows can't be rendered"
        )
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


def probe_video(path: str) -> dict:
    """Return the width, height and duration of a video via ffprobe.

    Telegram shows a video with wrong proportions without them. An
    empty dict is returned if ffprobe is missing or fails.
    """
    if not shutil.which("ffprobe"):
        return {}
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0"]
            + ["-show_entries", "stream=width,height:format=duration"]
            + ["-of", "json", path],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        ).stdout
        data = json.loads(out)
        stream = (data.get("streams") or [{}])[0]
        return {
            "width": stream.get("width"),
            "height": stream.get("height"),
            # Telegram wants whole seconds.
            "duration": round(float(data["format"]["duration"])),
        }
    except Exception:
        logging.warning("couldn't probe %s", path)
        return {}


def parse_gallery_dl(data: list) -> list[dict]:
    """Turn gallery-dl's JSON output (-j) into a list of post files.

    Each file is {"url", "video"}; the order is the carousel order.
    """
    files = []
    for message in data:
        if message and message[0] == -1:  # an error
            info = message[-1] if isinstance(message[-1], dict) else {}
            raise RuntimeError(f"gallery-dl: {info.get('message', info)}")
        if len(message) >= 3 and message[0] == 3:  # a file
            url, meta = message[1], message[2]
            is_video = bool(meta.get("video_url"))
            # A "ytdl:" pseudo URL can't be fetched directly; the real
            # video URL is in the metadata.
            if url.startswith("ytdl:"):
                url = meta.get("video_url") or url
            files.append({"url": url, "video": is_video})
    if not files:
        raise RuntimeError("gallery-dl found no files in the post")
    return files


def instagram_files(url: str) -> list[dict]:
    """List the photos and videos of an Instagram post with gallery-dl.

    The result is cached, so a post is only listed once.
    """
    if url in instagram_posts:
        return instagram_posts[url]
    cmd = [sys.executable, "-m", "gallery_dl", "--dump-json"]
    # "merged": plain mp4 video URLs instead of DASH manifests.
    cmd += ["-o", "videos=merged"]
    cookiefile = cookies_for("instagram")
    if cookiefile:
        cmd += ["--cookies", cookiefile]
    result = subprocess.run(
        [*cmd, url],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=DOWNLOAD_TIMEOUT,
    )
    try:
        data = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"gallery-dl failed: {result.stderr.strip()[-300:]}"
        ) from e
    instagram_posts[url] = parse_gallery_dl(data)
    return instagram_posts[url]


def fetch_file(c: httpx.Client, url: str, path: str):
    """Download a file, refusing anything above the Bot API limit."""
    size = 0
    with c.stream("GET", url) as response:
        response.raise_for_status()
        with open(path, "wb") as f:
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > MAX_BYTES:
                    raise TooBigError("file is larger than 50 MB")
                f.write(chunk)


def download_instagram_post(url: str, outdir: str) -> list[tuple[str, str]]:
    """Download all files of an Instagram post, in carousel order.

    Return a list of (kind, path), kind is "photo" or "video". Photos
    are converted to JPEG (Instagram also serves webp and heic).
    """
    items = []
    with _http() as c:
        for i, file in enumerate(instagram_files(url)):
            if file["video"]:
                path = os.path.join(outdir, f"{i:03}.mp4")
                fetch_file(c, file["url"], path)
                items.append(("video", path))
            else:
                raw = os.path.join(outdir, f"{i:03}.raw")
                fetch_file(c, file["url"], raw)
                path = os.path.join(outdir, f"{i:03}.jpg")
                convert_image(raw, path)
                items.append(("photo", path))
    return items


def download_instagram_single(url: str, outdir: str) -> tuple[str, dict]:
    """Turn an Instagram post into one video, for inline mode.

    An inline message holds only one media item: the first video of
    the post is used, and a post of photos only becomes a slideshow.
    """
    files = instagram_files(url)
    with _http() as c:
        for file in files:
            if file["video"]:
                path = os.path.join(outdir, "video.mp4")
                fetch_file(c, file["url"], path)
                return path, probe_video(path)
        img_paths = []
        for i, file in enumerate(files):
            raw = os.path.join(outdir, f"{i:03}.raw")
            fetch_file(c, file["url"], raw)
            # PNG for the slideshow renderer, like TikTok slideshows.
            png = os.path.join(outdir, f"{i:03}.png")
            convert_image(raw, png)
            img_paths.append(png)
    return render_slideshow(img_paths, None, outdir)


def download_album(url: str, outdir: str) -> list[tuple[str, str]]:
    """Download the items of an album link as a list of (kind, path)."""
    if is_instagram_post(url):
        return download_instagram_post(url, outdir)
    return [("photo", p) for p in download_slideshow_images(url, outdir)]


def download(url: str, outdir: str) -> tuple[str, dict]:
    """Download a video from any supported platform into outdir.

    Return the path to the file and the info dict with its metadata.
    """
    platform = platform_of(url)
    if platform == "tiktok":
        return download_tiktok(url, outdir)
    if is_instagram_post(url):
        return download_instagram_single(url, outdir)
    if platform == "instagram":
        return download_instagram_reel(url, outdir)
    return download_generic(url, outdir, platform)


def download_instagram_reel(url: str, outdir: str) -> tuple[str, dict]:
    """Download an Instagram Reel: yt-dlp first, gallery-dl as a backup.

    The two tools talk to Instagram differently, so when Instagram
    changes something, one of them often still works. A too big video
    is not retried: gallery-dl would get the same file.
    """
    try:
        return download_generic(url, outdir, "instagram")
    except TooBigError:
        raise
    except Exception as e:
        logging.warning("yt-dlp failed on %s (%s), trying gallery-dl", url, e)
    return download_instagram_single(url, outdir)


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
                disable_notification=True,
                request_timeout=UPLOAD_TIMEOUT,
            )
        if msg.video is None:
            raise RuntimeError("Telegram didn't return the uploaded video")
        cache[url] = msg.video.file_id
        return cache[url]


def chunks(items: list, size: int = ALBUM_LIMIT) -> list[list]:
    """Split a list into parts of at most `size` items."""
    parts = []
    for start in range(0, len(items), size):
        end = start + size
        parts.append(items[start:end])
    return parts


def album_input(
    kind: str,
    media: str | FSInputFile,
    caption: str | None = None,
    parse_mode: str | None = None,
    **extra,
) -> InputMediaPhoto | InputMediaVideo:
    """Build one album item: a photo or a video.

    `media` is a file to upload or a file_id. parse_mode is None by
    default: storage captions are raw URLs, and "&" in them would break
    HTML parsing.
    """
    if kind == "video":
        return InputMediaVideo(
            media=media,
            caption=caption,
            parse_mode=parse_mode,
            supports_streaming=True,
            **extra,
        )
    return InputMediaPhoto(media=media, caption=caption, parse_mode=parse_mode)


def sent_item(msg: Message) -> tuple[str, str] | None:
    """Return (kind, file_id) of a sent photo or video message."""
    if msg.photo:
        # The last PhotoSize is the largest one.
        return "photo", msg.photo[-1].file_id
    if msg.video:
        return "video", msg.video.file_id
    return None


async def upload_album_part(
    bot: Bot, part: list[tuple[str, str]], caption: str
) -> list[Message]:
    """Upload up to 10 files to the storage channel.

    Telegram albums need at least 2 items, so a single file is sent as
    a plain photo or video instead.
    """
    common = {
        "disable_notification": True,
        "request_timeout": UPLOAD_TIMEOUT,
    }
    if len(part) == 1:
        kind, path = part[0]
        if kind == "video":
            msg = await bot.send_video(
                STORAGE_CHAT_ID,
                FSInputFile(path),
                caption=caption,
                parse_mode=None,
                supports_streaming=True,
                **probe_video(path),
                **common,
            )
        else:
            msg = await bot.send_photo(
                STORAGE_CHAT_ID,
                FSInputFile(path),
                caption=caption,
                parse_mode=None,
                **common,
            )
        return [msg]
    # A caption on the first item is shown under the whole album.
    media = [
        album_input(
            kind,
            FSInputFile(path),
            caption if i == 0 else None,
            **(probe_video(path) if kind == "video" else {}),
        )
        for i, (kind, path) in enumerate(part)
    ]
    return await bot.send_media_group(STORAGE_CHAT_ID, media, **common)


async def get_album_items(bot: Bot, url: str) -> list[tuple[str, str]]:
    """Return (kind, file_id) for every photo and video of an album.

    On a cache miss, download the files and upload them to the storage
    channel first.
    """
    if url in album_cache:
        return album_cache[url]
    lock = locks.setdefault("album:" + url, asyncio.Lock())
    async with lock:
        if url in album_cache:
            return album_cache[url]
        items = []
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            files = await run_with_timeout(download_album, url, tmp)
            for part in chunks(files):
                for msg in await upload_album_part(bot, part, url):
                    if item := sent_item(msg):
                        items.append(item)
        if not items:
            raise RuntimeError("Telegram didn't return the uploaded files")
        album_cache[url] = items
        return items


async def react(bot: Bot, msg: Message, emoji: str | None):
    """Set a reaction on a message, or remove it with emoji=None.

    Group admins can restrict reactions, so a refused reaction is only
    logged: the download goes on without it.
    """
    reaction = [ReactionTypeEmoji(emoji=emoji)] if emoji else []
    try:
        await bot.set_message_reaction(
            msg.chat.id, msg.message_id, reaction=reaction
        )
    except Exception as e:
        logging.info("couldn't set reaction %r: %s", emoji, e)


def is_silent(chat: Chat) -> bool:
    """Tell whether messages to a chat should come without a sound.

    Groups get silent messages so the bot doesn't buzz everyone's
    phone; in private chats the user is waiting, so a sound helps.
    """
    return chat.type != ChatType.PRIVATE


def sender_mention(user: User | None) -> str:
    """Return an HTML mention: @username, or a clickable name."""
    if user is None:
        return "?"
    if user.username:
        return f"@{user.username}"
    name = html.escape(user.full_name or str(user.id))
    return f'<a href="tg://user?id={user.id}">{name}</a>'


def cleanup_caption(mode: str, lang: str, url: str, user: User | None):
    """Build the caption for a /cleanup mode, or None if it has none."""
    parts = []
    if mode == "link_user":
        parts.append(t(lang, "link_line", link=html.escape(url)))
    if mode in ("link_user", "user"):
        parts.append(t(lang, "sent_by", user=sender_mention(user)))
    return "\n".join(parts) or None


async def reply_with_media(
    bot: Bot, msg: Message, url: str, as_reply: bool = True, caption=None
):
    """Send the media behind a link to the chat of a message.

    TikTok slideshows and Instagram posts come as albums (photos and
    videos, up to 10 per album), everything else as a video. By default
    the media replies to the message; with as_reply=False it's sent as
    a separate message, with `caption` (HTML) under it or under the
    first album. In groups it comes without a notification. Returns the
    id of the first message sent.
    """
    options = {"disable_notification": is_silent(msg.chat)}
    if as_reply:
        options["reply_parameters"] = ReplyParameters(
            message_id=msg.message_id
        )
    if await asyncio.to_thread(is_album, url):
        items = await get_album_items(bot, url)
    else:
        items = [("video", await get_file_id(bot, url))]
    first_id = None
    for n, part in enumerate(chunks(items)):
        # Only the first message or album gets the caption.
        text = caption if n == 0 else None
        if len(part) == 1:
            kind, file_id = part[0]
            send = msg.answer_video if kind == "video" else msg.answer_photo
            extra = {"supports_streaming": True} if kind == "video" else {}
            sent = [
                await send(
                    file_id,
                    caption=text,
                    parse_mode=ParseMode.HTML,
                    **extra,
                    **options,
                )
            ]
        else:
            media = [
                album_input(
                    kind,
                    file_id,
                    text if i == 0 else None,
                    parse_mode=ParseMode.HTML,
                )
                for i, (kind, file_id) in enumerate(part)
            ]
            sent = await msg.answer_media_group(media, **options)
        if first_id is None and sent:
            first_id = sent[0].message_id
    return first_id


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
    text = t(lang, "start", bot=me.username) + t(
        lang, "source_line", repo=REPO_URL
    )
    # No big GitHub preview card under the greeting.
    await msg.answer(
        text,
        reply_markup=kb,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


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
    await react(bot, msg, REACTION_WORKING)
    status = await msg.reply(t(lang, "downloading"))
    try:
        async with slow_notice(lambda: status.edit_text(t(lang, "slow"))):
            await reply_with_media(bot, msg, url)
    except Exception as e:
        logging.exception("download failed: %s", url)
        await react(bot, msg, REACTION_FAILED)
        # In private chats the error stays, so the user can see what
        # happened with their link.
        await status.edit_text(error_text(lang, e))
        return
    await react(bot, msg, None)
    # The video is already sent, so failing to clean up isn't an error.
    try:
        await status.delete()
    except Exception:
        logging.warning("couldn't delete status message")


@router.message(Command("help"))
async def on_help(msg: Message, bot: Bot):
    """Explain how to use the bot and who can run which command."""
    if msg.chat.type == ChatType.PRIVATE:
        lang = lang_of(msg.from_user)
    else:
        lang = group_lang(msg.chat.id, msg.from_user)
    me = await bot.me()
    await msg.answer(
        t(lang, "help", bot=me.username),
        disable_notification=is_silent(msg.chat),
    )


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

    No "Downloading..." text here to keep the chat clean: a 👀 reaction
    on the link and the "sending video..." status show that the bot
    works.
    """
    url = LINK_RE.search(msg.text).group(0)
    mode = cleanup_mode(msg.chat.id)
    lang = group_lang(msg.chat.id, msg.from_user)
    logging.info(
        "group %s: %s link, cleanup=%s", msg.chat.id, platform_of(url), mode
    )
    key = await asyncio.to_thread(media_key, url)
    earlier = earlier_post(msg.chat.id, key)
    if earlier and await point_to_earlier(bot, msg, earlier, mode, lang):
        return
    await react(bot, msg, REACTION_WORKING)
    try:
        async with ChatActionSender.upload_video(bot=bot, chat_id=msg.chat.id):
            sent_id = await reply_with_media(
                bot,
                msg,
                url,
                as_reply=mode == "keep",
                caption=cleanup_caption(mode, lang, url, msg.from_user),
            )
    except Exception as e:
        logging.exception("download failed: %s", url)
        # The original stays on failure, so the link isn't lost.
        await react(bot, msg, REACTION_FAILED)
        error = await msg.reply(error_text(lang, e), disable_notification=True)
        delete_later(bot, error.chat.id, error.message_id)
        return
    if sent_id is not None:
        remember_post(msg.chat.id, key, sent_id)
    if mode == "keep":
        await react(bot, msg, None)
        return
    # The media is sent, so the original message can go. Without the
    # "Delete messages" right this fails, and the message just stays.
    try:
        await msg.delete()
        logging.info("deleted the link message in %s", msg.chat.id)
    except Exception as e:
        logging.warning("couldn't delete the link message: %s", e)
        await react(bot, msg, None)


async def point_to_earlier(
    bot: Bot, msg: Message, earlier: int, mode: str, lang: str
) -> bool:
    """Answer a repeated link by replying to the earlier media.

    In the modes that delete links, the repeated one is deleted too.
    Returns False if the earlier message is gone (deleted by someone),
    so the media has to be sent again.
    """
    if mode == "none":
        text = t(lang, "already_posted_anon")
    else:
        text = t(lang, "already_posted", user=sender_mention(msg.from_user))
    try:
        await msg.answer(
            text,
            reply_parameters=ReplyParameters(
                message_id=earlier, allow_sending_without_reply=False
            ),
            disable_notification=True,
        )
    except TelegramBadRequest as e:
        logging.info("earlier post %s is gone: %s", earlier, e)
        return False
    logging.info(
        "group %s: repeated link, pointed to %s", msg.chat.id, earlier
    )
    if mode != "keep":
        try:
            await msg.delete()
        except Exception as e:
            logging.warning("couldn't delete the repeated link: %s", e)
    return True


@router.message(F.migrate_to_chat_id, group)
async def on_migrated(msg: Message):
    """Move the settings when a group becomes a supergroup.

    This message comes in the old group.
    """
    move_chat(msg.chat.id, msg.migrate_to_chat_id)


@router.message(F.migrate_from_chat_id, group)
async def on_migrated_from(msg: Message):
    """Move the settings when a group becomes a supergroup.

    This message comes in the new supergroup; whichever of the two
    arrives first does the job.
    """
    move_chat(msg.migrate_from_chat_id, msg.chat.id)


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
        reply = await msg.reply(
            t(lang, "admins_only"), disable_notification=True
        )
        delete_later(bot, reply.chat.id, reply.message_id)
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=name, callback_data=f"glang:{code}")]
            for code, name in LANG_NAMES.items()
        ]
    )
    await msg.reply(
        t(lang, "choose_group_lang"),
        reply_markup=kb,
        disable_notification=True,
    )


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


@router.message(Command("notices"), group)
async def on_group_notices(msg: Message, bot: Bot):
    """Ask admins whether to post restart and shutdown notices."""
    lang = group_lang(msg.chat.id, msg.from_user)
    if not await is_admin_message(bot, msg):
        reply = await msg.reply(
            t(lang, "admins_only"), disable_notification=True
        )
        delete_later(bot, reply.chat.id, reply.message_id)
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(lang, "notices_on_button"),
                    callback_data="gnotices:on",
                ),
                InlineKeyboardButton(
                    text=t(lang, "notices_off_button"),
                    callback_data="gnotices:off",
                ),
            ]
        ]
    )
    if notices_enabled(msg.chat.id):
        current = "notices_now_on"
    else:
        current = "notices_now_off"
    await msg.reply(
        t(lang, "choose_notices") + "\n" + t(lang, current),
        reply_markup=kb,
        disable_notification=True,
    )


@router.callback_query(F.data.startswith("gnotices:"))
async def on_group_notices_chosen(c: CallbackQuery, bot: Bot):
    """Save the notices setting if an admin pressed the button."""
    choice = (c.data or "").split(":", 1)[-1]
    if choice not in ("on", "off") or not isinstance(c.message, Message):
        await c.answer()
        return
    chat_id = c.message.chat.id
    # Anyone in the group can press the buttons, so check again.
    if not await is_group_admin(bot, chat_id, c.from_user):
        await c.answer(t(lang_of(c.from_user), "admins_only"), show_alert=True)
        return
    set_chat_setting(chat_id, "notices", choice == "on")
    lang = group_lang(chat_id, c.from_user)
    key = "notices_set_on" if choice == "on" else "notices_set_off"
    await c.message.edit_text(t(lang, key))
    await c.answer()


async def can_delete_messages(bot: Bot, chat_id: int) -> bool:
    """Check whether the bot may delete other people's messages."""
    me = await bot.me()
    member = await bot.get_chat_member(chat_id, me.id)
    if member.status == ChatMemberStatus.CREATOR:
        return True
    return member.status == ChatMemberStatus.ADMINISTRATOR and bool(
        getattr(member, "can_delete_messages", False)
    )


@router.message(Command("cleanup"), group)
async def on_group_cleanup(msg: Message, bot: Bot):
    """Show admins the choice of what to do with link messages."""
    lang = group_lang(msg.chat.id, msg.from_user)
    if not await is_admin_message(bot, msg):
        reply = await msg.reply(
            t(lang, "admins_only"), disable_notification=True
        )
        delete_later(bot, reply.chat.id, reply.message_id)
        return
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=t(lang, f"cleanup_{mode}"),
                    callback_data=f"gcleanup:{mode}",
                )
            ]
            for mode in CLEANUP_MODES
        ]
    )
    current = t(lang, f"cleanup_{cleanup_mode(msg.chat.id)}")
    await msg.reply(
        t(lang, "choose_cleanup")
        + "\n"
        + t(lang, "cleanup_now", mode=current),
        reply_markup=kb,
        disable_notification=True,
    )


@router.callback_query(F.data.startswith("gcleanup:"))
async def on_group_cleanup_chosen(c: CallbackQuery, bot: Bot):
    """Save the cleanup mode if an admin pressed the button."""
    mode = (c.data or "").split(":", 1)[-1]
    if mode not in CLEANUP_MODES or not isinstance(c.message, Message):
        await c.answer()
        return
    chat_id = c.message.chat.id
    # Anyone in the group can press the buttons, so check again.
    if not await is_group_admin(bot, chat_id, c.from_user):
        await c.answer(t(lang_of(c.from_user), "admins_only"), show_alert=True)
        return
    set_chat_setting(chat_id, "cleanup", mode)
    lang = group_lang(chat_id, c.from_user)
    text = t(lang, "cleanup_set", mode=t(lang, f"cleanup_{mode}"))
    if mode != "keep" and not await can_delete_messages(bot, chat_id):
        text += t(lang, "cleanup_need_right")
    await c.message.edit_text(text)
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
    await bot.send_message(event.chat.id, text, disable_notification=True)


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


async def post_restart_notices(bot: Bot, key: str = "restarting"):
    """Tell every group that the bot is restarting or shutting down.

    `key` is the text to post: "restarting" or "shutting_down". The
    message ids are saved so the next run can delete them.
    """
    for chat_id, lang in list(state["groups"].items()):
        if not notices_enabled(chat_id):
            continue
        try:
            msg = await bot.send_message(
                int(chat_id), t(lang, key), disable_notification=True
            )
            state["restart_notices"][chat_id] = msg.message_id
        except TelegramMigrateToChat as e:
            # The group became a supergroup while the bot wasn't
            # looking; the notice goes there next time.
            move_chat(chat_id, e.migrate_to_chat_id)
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
    """Delete the restart/shutdown messages left by the previous run."""
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
            BotCommand(command="help", description=t(code, "cmd_help")),
            BotCommand(
                command="language", description=t(code, "cmd_language")
            ),
        ]
        await bot.set_my_commands(commands, language_code=lang_code)
        # In groups only the admin settings make sense.
        await bot.set_my_commands(
            [
                BotCommand(
                    command="language",
                    description=t(code, "cmd_group_language"),
                ),
                BotCommand(
                    command="notices",
                    description=t(code, "cmd_group_notices"),
                ),
                BotCommand(
                    command="cleanup",
                    description=t(code, "cmd_group_cleanup"),
                ),
                BotCommand(command="help", description=t(code, "cmd_help")),
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
            description = t(code, "bot_description", bot=me.username) + t(
                code, "source_line", repo=REPO_URL
            )
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
    """Warn the groups; on a real shutdown also show the bot offline.

    A restart takes only a few seconds, so the profile status is left
    as it is instead of flickering to offline and back.
    """
    if not quiet_stop:
        key = "restarting" if stop_mode == "restart" else "shutting_down"
        await post_restart_notices(bot, key)
    if stop_mode != "restart":
        await set_profile_status(bot, online=False)


def start_console(dp: Dispatcher, loop: asyncio.AbstractEventLoop):
    """Read commands from the terminal in a background thread.

    "stop" shuts the bot down for a while, "restart" restarts it with
    the latest code. A daemon thread is used so that a blocked input()
    never keeps the process alive after Ctrl+C.
    """

    def worker():
        """Wait for commands until "stop", "restart" or end of input.

        Adding "quiet" ("stop quiet", "restart quiet") skips the
        messages in groups.
        """
        global stop_mode, quiet_stop
        while True:
            try:
                words = input().strip().lower().split()
            except (EOFError, KeyboardInterrupt):
                # No interactive terminal (e.g. running as a service).
                return
            if not words:
                continue
            cmd, flags = words[0], set(words[1:])
            if cmd in ("stop", "exit", "quit", "restart") and flags <= {
                "quiet"
            }:
                stop_mode = "restart" if cmd == "restart" else "shutdown"
                quiet_stop = "quiet" in flags
                logging.info(
                    "%s%s...",
                    "restarting" if cmd == "restart" else "stopping",
                    " quietly" if quiet_stop else "",
                )
                asyncio.run_coroutine_threadsafe(dp.stop_polling(), loop)
                return
            print(
                "Unknown command. Available: stop, restart "
                "(add 'quiet' to skip group messages)"
            )

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
    print("Bot is running. Type 'stop' to shut it down, 'restart' to restart.")
    start_console(dp, asyncio.get_running_loop())
    try:
        await setup_bot_profile(bot)
        await dp.start_polling(bot, allowed_updates=ALLOWED_UPDATES)
    finally:
        await bot.session.close()
        logging.info("bot stopped")


def supervise() -> int:
    """Run the bot in a child process and restart it when asked.

    The child exits with RESTART_EXIT_CODE after "restart", and a new
    child is started, so code changes are picked up. The child shares
    this terminal, so console commands keep working. Ctrl+C reaches
    both processes: the child shuts down gracefully, and the
    supervisor just waits for it.
    """
    env = {**os.environ, CHILD_ENV: "1"}
    while True:
        child = subprocess.Popen([sys.executable, *sys.argv], env=env)
        while True:
            try:
                code = child.wait()
                break
            except KeyboardInterrupt:
                continue  # the child handles Ctrl+C itself
        if code != RESTART_EXIT_CODE:
            return code
        print("Restarting the bot...")


if __name__ == "__main__":
    if os.environ.get(CHILD_ENV):
        asyncio.run(main())
        sys.exit(RESTART_EXIT_CODE if stop_mode == "restart" else 0)
    sys.exit(supervise())
