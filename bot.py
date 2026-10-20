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

Repeated requests for the same post are served from the ``file_id``
cache, which is kept in the database. TikTok photo slideshows are sent
as a photo album in private chats and groups. In inline mode they are
rendered into an mp4 (images + original music) with ffmpeg, because an
inline message can hold only one media item, not an album.

What every bot does the same way (languages, auto-deletion in groups,
/privacy, /broadcast, /reload, /stop, the restart notices, the profile
status, the console) lives in botkit/, shared with Warden. Start the
bot with ``python bot.py``: botkit's supervisor restarts it on
/reload, so new code and a new .env are picked up.

Author: @artemi372 on Telegram.
Source code: https://github.com/artemi372/pastemedia-bot
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
import time
from typing import Any, Awaitable, Callable

import httpx
import yt_dlp
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatMemberStatus, ChatType, ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.types import (
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
    LinkPreviewOptions,
    Message,
    ReactionTypeEmoji,
    ReplyParameters,
    User,
)
from aiogram.utils.chat_action import ChatActionSender

from botkit import (
    TTL_MEDIUM,
    TTL_SHORT,
    BotKit,
    is_private,
    load_config,
    run,
    setup_logging,
)
from storage import BASE, Storage
from texts import t

# ---------- configuration ----------

REPO_URL = "https://github.com/artemi372/pastemedia-bot"
# BOT_TOKEN, DEV_IDS, the author and the Privacy Policy / Terms of Use
# links (required by Telegram's rules for bots; set PRIVACY_URL and
# TERMS_URL in .env when running your own copy, empty hides the link).
cfg = load_config(
    bot_name="Media Paste Bot",
    default_lang="en",
    privacy_url="https://telegra.ph/Media-Paste-Bot--Privacy-Policy-10-07",
    terms_url="https://telegra.ph/Media-Paste-Bot--Terms-of-Use-10-07",
    repo_url=REPO_URL,
)
# Private channel where the bot is an admin, id like -100...
STORAGE_CHAT_ID = int(os.environ["STORAGE_CHAT_ID"])
MAX_BYTES = 50 * 1024 * 1024  # Bot API upload limit
# Videos above MAX_BYTES are re-encoded with ffmpeg to fit. Sources
# above MAX_SOURCE_BYTES are refused right away: squeezing them into
# 50 MB would take too long and look bad anyway.
MAX_SOURCE_BYTES = 300 * 1024 * 1024
# What re-encoding aims for: a bit under the limit, since the bitrate
# is never hit exactly and the mp4 container adds some bytes.
TARGET_BYTES = 46 * 1024 * 1024
AUDIO_KBPS = 96
# Below this video bitrate the picture turns into mush, so the video
# is reported as too big instead.
MIN_VIDEO_KBPS = 400
COMPRESS_TIMEOUT = 300  # seconds for one ffmpeg run
# In groups, a link inside a long text is most likely an announcement
# or an ad, not something to download: skip messages with more text
# than this around the link, or with more links than this.
GROUP_TEXT_LIMIT = 200
GROUP_URL_LIMIT = 2
APPEAL_COOLDOWN = 24 * 60 * 60  # seconds between appeals of one user
ALBUM_LIMIT = 10  # max photos in one Telegram album
# Reactions on the message with a link. Bots can only use Telegram's
# standard reaction emoji.
REACTION_WORKING = "👀"
REACTION_FAILED = "🤷"
# What to do with a group message that has a link, set by admins with
# /cleanup. Only "keep" replies to it; the others delete it and send
# the media as a separate message with an optional caption.
CLEANUP_MODES = ("keep", "link_user", "user", "none")
SLOW_AFTER = 20  # seconds before "taking longer than usual"
DOWNLOAD_TIMEOUT = 120  # seconds before a download is given up
# Seconds to upload a file to Telegram. aiogram's default of 60 is too
# short for a 1080p video of tens of megabytes on a home connection.
UPLOAD_TIMEOUT = 300
# Max length of the sender's comment copied under the media. Telegram
# allows 1024 characters in a caption; the rest is the link and sender.
COMMENT_LIMIT = 700
SLIDE_SECONDS = 2.5  # how long each slideshow image is shown
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)

PLATFORM_PATTERNS = {
    # Videos, photo posts and short links, not profiles or sounds.
    "tiktok": (
        r"https?://(?:(?:vm|vt)\.tiktok\.com/[\w-]+"
        r"|(?:www\.|m\.)?tiktok\.com/"
        r"(?:@[\w.-]+/(?:video|photo)/\d+|t/[\w-]+)"
        # New short links, e.g. tt.site/t/ZN8BmuJda
        r"|(?:www\.)?tt\.site/t/[\w-]+)\S*"
    ),
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
# Any link at all, to count them in a message.
URL_RE = re.compile(r"https?://\S+", re.I)
# Punctuation that sticks to a link in a sentence: "look (https://...)."
TRAILING = ".,!?;:)]}>»\"'"

# Optional cookies (Netscape cookies.txt format) for platforms that
# block anonymous access. Keep this folder out of git: cookies are as
# secret as a password.
COOKIES_DIR = BASE / "cookies"

setup_logging()
log = logging.getLogger("bot")
router = Router()
# The database: known chats and settings (botkit), the file_id cache,
# recent videos in groups, bans, blocked posts (storage.py). Runtime
# data, kept in data/ and out of git.
db = Storage()
# Owner commands, also usable in the storage channel.
ADMIN_COMMANDS = ("ban", "unban", "block", "unblock", "bans")
kit = BotKit(
    cfg,
    db,
    menu=["start", "help", "settings", "language", "privacy"],
    group_menu=["settings", "cleanup", "language", "help", "privacy"],
    dev_menu=["bans"],
    commands={"start", "help", "settings", "cleanup", "appeal", "terms"}
    | set(ADMIN_COMMANDS),
)
# The shared helpers, under the names the rest of the code uses.
lang_of = kit.lang_of
reply = kit.reply
edit = kit.edit

# ---------- runtime state ----------

# Instagram post url -> its files as listed by gallery-dl (in memory)
instagram_posts: dict[str, list[dict]] = {}
# short url -> full url after redirects (in memory)
resolved: dict[str, str] = {}
# Prevents downloading the same link twice in parallel.
locks: dict[str, asyncio.Lock] = {}
# Re-encoding takes all CPU cores, so only one runs at a time; the
# others wait in line.
compress_slot = asyncio.Semaphore(1)


class TooBigError(RuntimeError):
    """The file exceeds the Bot API upload limit."""


class BlockedError(RuntimeError):
    """The post is on the block list."""


class DownloadTimeoutError(RuntimeError):
    """The download took longer than DOWNLOAD_TIMEOUT."""


def cleanup_mode(chat_id: int) -> str:
    """Return the /cleanup mode of a group ("keep" by default)."""
    mode = db.get_setting(f"cleanup:{chat_id}", "keep")
    return mode if mode in CLEANUP_MODES else "keep"


def ban_of(user: User | int | None) -> dict | None:
    """Return the ban of a user, or None if they aren't banned."""
    return db.ban_of(user.id if isinstance(user, User) else user)


# ---------- helpers ----------


def error_text(lang: str, e: Exception) -> str:
    """Turn an exception into a friendly message for the user.

    Technical details go to the log, not to the chat.
    """
    if isinstance(e, BlockedError):
        return t(lang, "blocked_content")
    if isinstance(e, TooBigError):
        return t(lang, "too_big")
    # A network error while uploading is almost always a timeout.
    if isinstance(e, (DownloadTimeoutError, TelegramNetworkError)):
        return t(lang, "timeout")
    # yt-dlp's wording for posts hidden from logged-out or underage
    # viewers.
    text = str(e).lower()
    if any(
        s in text
        for s in ("log in for access", "login required", "confirm your age")
    ):
        return t(lang, "login_needed")
    return t(lang, "failed") + kit.contact_hint(lang)


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
            log.warning("couldn't show the slow notice: %s", e)

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
    path = COOKIES_DIR / f"{platform}.txt"
    return str(path) if path.is_file() else None


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
        """Rank a format: has sound, fits into 50 MB, H.264, height.

        A format of unknown size counts as fitting; if it turns out
        too big, it gets compressed. Formats without sound go last.
        """
        has_audio = f.get("acodec") != "none"
        size = f.get("filesize") or f.get("filesize_approx") or 0
        vcodec = (f.get("vcodec") or "").lower()
        # HEVC doesn't play on some Telegram clients.
        h264 = vcodec.startswith(("h264", "avc"))
        return (
            has_audio,
            size <= MAX_BYTES,
            h264,
            f.get("height") or 0,
            f.get("tbr") or 0,
        )

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
    """Follow short links (vm.tiktok.com, tt.site) to the post URL."""
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
                log.warning("couldn't parse %s JSON", script_id)
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
    log.warning(
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
        log.warning("couldn't probe %s", path)
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


def fetch_file(c: httpx.Client, url: str, path: str, limit: int = MAX_BYTES):
    """Download a file, refusing anything above `limit` bytes.

    The default is the Bot API limit; a single video may be bigger,
    since it can still be compressed.
    """
    size = 0
    with c.stream("GET", url) as response:
        response.raise_for_status()
        with open(path, "wb") as f:
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > limit:
                    raise TooBigError(f"file is larger than {limit} bytes")
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
                fetch_file(c, file["url"], path, MAX_SOURCE_BYTES)
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
        log.warning("yt-dlp failed on %s (%s), trying gallery-dl", url, e)
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
        # The best quality that fits into 50 MB when the size is known
        # (exact, then estimated), otherwise just the best; a too big
        # file is compressed afterwards. Video gets 45 MB, leaving room
        # for the audio track.
        "format": (
            "bv*[filesize<45MiB]+ba/bv*[filesize_approx<45MiB]+ba"
            "/b[filesize<50MiB]/b[filesize_approx<50MiB]/bv*+ba/b"
        ),
        # Prefer H.264 + AAC: HEVC, AV1 and VP9 don't play on some
        # Telegram clients.
        "format_sort": ["vcodec:h264", "res:1080", "acodec:aac"],
        "merge_output_format": "mp4",
        # yt-dlp skips files that are known to be too big even to
        # compress.
        "max_filesize": MAX_SOURCE_BYTES,
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
        raise TooBigError("video is too big even to compress")
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
    # Needed for posts TikTok shows only to logged-in adults.
    cookiefile = cookies_for("tiktok")
    if cookiefile:
        base["cookiefile"] = cookiefile
    with yt_dlp.YoutubeDL(base) as ydl:
        info = ydl.extract_info(full_url, download=False)

    fmt = _pick_clean_format(info)
    opts = base | {
        "format": fmt["format_id"],
        "outtmpl": os.path.join(outdir, "%(id)s.%(ext)s"),
        "max_filesize": MAX_SOURCE_BYTES,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(full_url, download=True)
        path = ydl.prepare_filename(info)

    if not os.path.isfile(path):
        raise TooBigError("video is too big even to compress")
    return path, info


def compress_plan(duration: float, factor: float = 1.0) -> tuple[int, int]:
    """Pick a video bitrate (kbit/s) and size for a video to fit.

    The size is the shorter side in pixels: lower bitrates look
    better at a lower resolution. `factor` lowers the bitrate for a
    second try. Raise TooBigError if the video is too long to look
    acceptable in 50 MB.
    """
    total_kbps = TARGET_BYTES * 8 / 1000 / max(duration, 1) * factor
    video_kbps = int(total_kbps - AUDIO_KBPS)
    if video_kbps < MIN_VIDEO_KBPS:
        raise TooBigError(f"{duration:.0f} s is too long to fit into 50 MB")
    for min_kbps, side in ((2500, 1080), (1200, 720), (700, 480)):
        if video_kbps >= min_kbps:
            return video_kbps, side
    return video_kbps, 360


def audio_streams(path: str) -> int:
    """Return the number of audio streams in a file (-1 if unknown)."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a"]
            + ["-show_entries", "stream=index", "-of", "csv=p=0", path],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        ).stdout
    except Exception:
        return -1
    return len(out.split())


def compress_video(src: str, outdir: str) -> tuple[str, dict]:
    """Re-encode a video with ffmpeg so it fits into the Bot API limit.

    H.264 + AAC, the bitrate computed from the duration. If the result
    is still too big (the bitrate is never hit exactly), try once more
    with 15% less. Return the new path and its metadata.
    """
    duration = (probe_video(src) or {}).get("duration")
    if not duration:
        raise TooBigError("can't compress: unknown duration")
    out = os.path.join(outdir, "compressed.mp4")
    src_audio = audio_streams(src)
    if src_audio == 0:
        log.warning("%s has no sound before compression", src)
    for factor in (1.0, 0.85):
        kbps, side = compress_plan(duration, factor)
        # Limit the shorter side, so portrait Shorts and landscape
        # videos are scaled the same way; -2 keeps the size even.
        scale = (
            f"scale='if(gt(iw,ih),-2,min({side},iw))'"
            f":'if(gt(iw,ih),min({side},ih),-2)'"
        )
        cmd = ["ffmpeg", "-y", "-v", "error", "-i", src, "-vf", scale]
        # The first video and the first audio track, picked explicitly:
        # ffmpeg's automatic choice can skip the sound in some files.
        cmd += ["-map", "0:v:0", "-map", "0:a:0?"]
        cmd += ["-c:v", "libx264", "-preset", "veryfast"]
        cmd += ["-b:v", f"{kbps}k", "-maxrate", f"{kbps * 3 // 2}k"]
        cmd += ["-bufsize", f"{kbps * 2}k", "-pix_fmt", "yuv420p"]
        cmd += ["-c:a", "aac", "-b:a", f"{AUDIO_KBPS}k", "-ac", "2"]
        cmd += ["-movflags", "+faststart", out]
        log.info(
            "compressing %s s video to %s kbit/s, %sp", duration, kbps, side
        )
        # The timeout kills ffmpeg, so nothing keeps running after it.
        subprocess.run(
            cmd, check=True, capture_output=True, timeout=COMPRESS_TIMEOUT
        )
        if src_audio > 0 and audio_streams(out) == 0:
            raise RuntimeError("the sound was lost in compression")
        if os.path.getsize(out) <= MAX_BYTES:
            return out, probe_video(out)
    raise TooBigError("still larger than 50 MB after compression")


async def get_file_id(bot: Bot, url: str, user_id: int | None = None) -> str:
    """Return a Telegram file_id for the video behind a link.

    On a cache miss, download the video and upload it to the storage
    channel first, noting who requested it. Different links to one
    post share the cache entry. Blocked posts raise BlockedError.
    """
    key = await asyncio.to_thread(media_key, url)
    if db.is_blocked(key):
        raise BlockedError(key)
    if cached := db.media_get("videos", key):
        return cached
    lock = locks.setdefault(key, asyncio.Lock())
    async with lock:
        if cached := db.media_get("videos", key):
            return cached
        # A timed-out download may still hold its files open.
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            path, info = await run_with_timeout(download, url, tmp)
            if os.path.getsize(path) > MAX_BYTES:
                path, info = await compress(path, tmp)
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
        db.remember_upload([msg.message_id], user_id)
        db.media_put("videos", key, msg.video.file_id)
        return msg.video.file_id


async def compress(path: str, outdir: str) -> tuple[str, dict]:
    """Compress a too big video, one at a time.

    Each ffmpeg run has its own timeout; this one also covers waiting
    in line and a second try.
    """
    log.info("%s is %.0f MB, compressing", path, os.path.getsize(path) / 2**20)
    try:
        async with compress_slot:
            return await asyncio.wait_for(
                asyncio.to_thread(compress_video, path, outdir),
                COMPRESS_TIMEOUT * 2 + 30,
            )
    except (asyncio.TimeoutError, subprocess.TimeoutExpired) as e:
        raise DownloadTimeoutError("compression timed out") from e


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


async def get_album_items(
    bot: Bot, url: str, user_id: int | None = None
) -> list[tuple[str, str]]:
    """Return (kind, file_id) for every photo and video of an album.

    On a cache miss, download the files and upload them to the storage
    channel first, noting who requested them. Different links to one
    post share the cache entry. Blocked posts raise BlockedError.
    """
    key = await asyncio.to_thread(media_key, url)
    if db.is_blocked(key):
        raise BlockedError(key)
    if cached := db.media_get("albums", key):
        return [tuple(item) for item in cached]
    lock = locks.setdefault("album:" + key, asyncio.Lock())
    async with lock:
        if cached := db.media_get("albums", key):
            return [tuple(item) for item in cached]
        items = []
        message_ids = []
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            files = await run_with_timeout(download_album, url, tmp)
            for part in chunks(files):
                for msg in await upload_album_part(bot, part, url):
                    message_ids.append(msg.message_id)
                    if item := sent_item(msg):
                        items.append(item)
        db.remember_upload(message_ids, user_id)
        if not items:
            raise RuntimeError("Telegram didn't return the uploaded files")
        db.media_put("albums", key, [list(item) for item in items])
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
        log.info("couldn't set reaction %r: %s", emoji, e)


def sender_mention(user: User | None) -> str:
    """Return an HTML mention: @username, or a clickable name."""
    if user is None:
        return "?"
    if user.username:
        return f"@{user.username}"
    name = html.escape(user.full_name or str(user.id))
    return f'<a href="tg://user?id={user.id}">{name}</a>'


def find_link(text: str | None) -> str:
    """Return the first supported link in a text ("" if none).

    Punctuation that sticks to the end of a link is cut off.
    """
    m = LINK_RE.search(text or "")
    return m.group(0).rstrip(TRAILING) if m else ""


def url_of(msg: Message) -> str:
    """Return the first supported link in a message ("" if none)."""
    return find_link(msg.text)


def looks_like_announcement(msg: Message, url: str) -> bool:
    """Tell whether a group message with a link isn't a share.

    Announcements, ads and channel posts often include an Instagram or
    TikTok link, and reposting it would only duplicate the post. A
    share is just a link, maybe with a short comment.
    """
    if msg.is_automatic_forward:
        return True  # a channel post in its discussion group
    text = msg.text or ""
    extra = " ".join(text.replace(url, " ").split())
    return (
        len(extra) > GROUP_TEXT_LIMIT
        or len(URL_RE.findall(text)) > GROUP_URL_LIMIT
    )


def link_comment(text: str, url: str) -> str:
    """Return what the sender wrote around the link, if anything."""
    comment = " ".join(text.replace(url, " ").split())
    if len(comment) > COMMENT_LIMIT:
        comment = comment[: COMMENT_LIMIT - 1].rstrip() + "…"
    return comment


def cleanup_caption(
    mode: str, lang: str, url: str, user: User | None, comment: str = ""
):
    """Build the caption for a /cleanup mode, or None if it has none.

    In the modes that delete the link message, the sender's own words
    go first, so they aren't lost with it.
    """
    parts = []
    if comment and mode != "keep":
        parts.append(t(lang, "comment_line", text=html.escape(comment)))
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
    first album. In groups it comes without a notification (botkit
    does that). Returns the id of the first message sent.
    """
    options = {}
    if as_reply:
        options["reply_parameters"] = ReplyParameters(
            message_id=msg.message_id
        )
    user_id = msg.from_user.id if msg.from_user else None
    if await asyncio.to_thread(is_album, url):
        items = await get_album_items(bot, url, user_id)
    else:
        items = [("video", await get_file_id(bot, url, user_id))]
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
    lang = lang_of(msg.chat.id, msg.from_user)
    me = await bot.me()
    # The button opens the chat picker with "@bot " already typed in.
    try_button = InlineKeyboardButton(
        text=t(lang, "try_button"), switch_inline_query=""
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[[try_button]])
    text = t(lang, "start", bot=me.username) + kit.footer(lang)
    # No big GitHub preview card under the greeting.
    await msg.answer(
        text,
        reply_markup=kb,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


def ban_text(lang: str, ban: dict) -> str:
    """Explain a ban to the banned user, with how to appeal."""
    if ban.get("kind") == "request":
        return t(lang, "banned_request")
    reason = html.escape(ban.get("reason") or t(lang, "no_reason"))
    return t(lang, "banned_abuse", reason=reason)


@router.message(
    F.text.regexp(LINK_RE, mode="search"), ~F.text.startswith("/"), private
)
async def on_link(msg: Message, bot: Bot):
    """Reply with the media to a link sent directly to the bot."""
    lang = lang_of(msg.chat.id, msg.from_user)
    if ban := ban_of(msg.from_user):
        # Answers to an appeal come in the language seen here.
        db.update_ban(msg.from_user.id, lang=lang)
        await msg.answer(ban_text(lang, ban))
        return
    url = find_link(msg.text)
    await react(bot, msg, REACTION_WORKING)
    status = await msg.reply(t(lang, "downloading"))
    try:
        async with slow_notice(lambda: status.edit_text(t(lang, "slow"))):
            await reply_with_media(bot, msg, url)
    except Exception as e:
        log.exception("download failed: %s", url)
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
        log.warning("couldn't delete status message")


@router.message(Command("help"))
async def on_help(msg: Message, bot: Bot):
    """Explain how to use the bot and who can run which command."""
    lang = lang_of(msg.chat.id, msg.from_user)
    me = await bot.me()
    text = t(lang, "help", bot=me.username)
    if not is_private(msg):
        text += t(lang, "help.autodelete")
    elif kit.is_dev(msg.from_user):
        # Developer commands only in a private chat: in a group
        # everyone would see them.
        text += kit.dev_help(lang)
    await reply(
        msg,
        text + kit.footer(lang),
        TTL_MEDIUM,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


# ---------- /settings ----------


def settings_view(chat_id: int, user_id: int):
    """Return the text and buttons of a chat's settings.

    The language and the restart notices are botkit's; groups also
    choose what happens to a message with a link (/cleanup).
    """
    lang = lang_of(chat_id)
    buttons = kit.settings_buttons(lang, chat_id)
    if chat_id > 0:
        text = t(lang, "settings.title", kit=kit.settings_lines(lang, chat_id))
    else:
        text = t(
            lang,
            "settings.group_title",
            kit=kit.settings_lines(lang, chat_id),
            cleanup=t(lang, f"cleanup_{cleanup_mode(chat_id)}"),
        )
        buttons.append(
            InlineKeyboardButton(
                text=t(lang, "btn.cleanup"), callback_data="cleanup:st"
            )
        )
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    return text, InlineKeyboardMarkup(inline_keyboard=rows)


kit.settings_view = settings_view


@router.message(Command("settings"))
async def on_settings(msg: Message):
    """Show the settings of this chat; in a group only to admins."""
    lang = lang_of(msg.chat.id, msg.from_user)
    if not await kit.can_manage(msg):
        await reply(msg, t(lang, "err.admins_only"), TTL_SHORT)
        return
    text, kb = settings_view(msg.chat.id, msg.from_user.id)
    await reply(msg, text, TTL_MEDIUM, reply_markup=kb)


# ---------- developers: moderation ----------


def ban_target(args: list[str], replied: Message | None) -> int | None:
    """Find whom a /ban or /unban is about.

    Either a user id as the first argument, or, in the storage
    channel, the user who requested the media the command replies to.
    """
    if args and args[0].lstrip("-").isdigit():
        return int(args.pop(0))
    if replied is not None:
        return db.uploader_of(replied.message_id)
    return None


async def notify(bot: Bot, user_id: int, key: str, **kwargs):
    """Message a user in their language (they may block the bot).

    The language is the user's /language choice, or the one seen when
    they last ran into the ban.
    """
    row = db.chat(user_id)
    lang = (
        (row["lang"] if row else None)
        or (ban_of(user_id) or {}).get("lang")
        or lang_of(user_id)
    )
    try:
        await bot.send_message(user_id, t(lang, key, **kwargs))
    except Exception as e:
        log.info("couldn't notify %s: %s", user_id, e)


async def admin_command(
    bot: Bot, cmd: str, args: list[str], replied: Message | None
) -> str:
    """Run a moderation command and return the answer (English, HTML).

    /ban <id|reply> [reason]: ban a user; a reason starting with
        "request" marks a ban the user asked for.
    /unban <id>: lift a ban.
    /block <link|reply> [reason]: never download a post again; its
        cached copy is forgotten, and the replied copy deleted.
    /unblock <link>: allow a post again.
    /bans: show both lists.
    """
    if cmd in ("ban", "unban"):
        user_id = ban_target(args, replied)
        if user_id is None:
            return t("en", "admin_who")
        if cmd == "unban":
            if ban_of(user_id) is None:
                return t("en", "admin_not_banned", id=user_id)
            await notify(bot, user_id, "unbanned")
            db.unban(user_id)
            return t("en", "admin_unbanned", id=user_id)
        reason = " ".join(args)
        kind = "request" if reason.lower().startswith("request") else "abuse"
        db.ban(user_id, reason, kind)
        if kind == "abuse":
            await notify(
                bot,
                user_id,
                "banned_abuse",
                reason=html.escape(reason or t("en", "no_reason")),
            )
        return t("en", "admin_banned", id=user_id, kind=kind)
    if cmd in ("block", "unblock"):
        url = find_link(args[0]) if args else ""
        if args and url:
            args = args[1:]
        elif replied is not None:
            url = find_link(replied.caption)
        if not url:
            return t("en", "admin_which_post")
        key = await asyncio.to_thread(media_key, url)
        if cmd == "unblock":
            if not db.unblock(key):
                return t("en", "admin_not_blocked", post=key)
            return t("en", "admin_unblocked", post=key)
        db.block(key, " ".join(args))
        db.media_drop(key)
        if replied is not None:
            with contextlib.suppress(Exception):
                await replied.delete()
        return t("en", "admin_blocked", post=key)
    bans = [
        f"<code>{b['user_id']}</code> {b['kind']}: "
        f"{html.escape(b.get('reason') or '-')}"
        for b in db.bans()
    ]
    blocked = [
        f"<code>{html.escape(b['key'])}</code>: "
        f"{html.escape(b.get('reason') or '-')}"
        for b in db.blocked()
    ]
    return t(
        "en",
        "admin_list",
        bans="\n".join(bans) or "-",
        blocked="\n".join(blocked) or "-",
    )


@router.channel_post(F.chat.id == STORAGE_CHAT_ID, Command(*ADMIN_COMMANDS))
async def on_storage_command(msg: Message, bot: Bot, command: CommandObject):
    """Run a moderation command posted in the storage channel.

    Only its admins can post there, so the post itself proves it's
    the author. Reply to a stored video to ban whoever requested it or
    to block the post. The command and the answer disappear after a
    minute, to keep the channel clean.
    """
    args = (command.args or "").split()
    text = await admin_command(
        bot, command.command.lower(), args, msg.reply_to_message
    )
    answer = await bot.send_message(
        STORAGE_CHAT_ID,
        text,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )
    for message in (msg, answer):
        kit.autodelete(message, TTL_MEDIUM, force=True)


@router.message(
    Command(*ADMIN_COMMANDS), private, F.from_user.func(kit.is_dev)
)
async def on_dev_admin(msg: Message, bot: Bot, command: CommandObject):
    """Run a moderation command sent in private chat (developers)."""
    args = (command.args or "").split()
    await msg.answer(
        await admin_command(bot, command.command.lower(), args, None),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


def appeal_keyboard(user_id: int) -> InlineKeyboardMarkup:
    """Build the developer's buttons for an appeal."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Unban", callback_data=f"appeal:yes:{user_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Reject", callback_data=f"appeal:no:{user_id}"
                ),
            ]
        ]
    )


@router.message(Command("appeal"), private)
async def on_appeal(msg: Message, bot: Bot, command: CommandObject):
    """Let a banned user ask to be unbanned.

    A ban the user asked for is lifted right away. Other appeals go to
    the developers (or the storage channel if DEV_IDS isn't set) with
    buttons, at most one per APPEAL_COOLDOWN.
    """
    lang = lang_of(msg.chat.id, msg.from_user)
    user = msg.from_user
    ban = ban_of(user)
    if ban is None:
        await msg.answer(t(lang, "appeal_not_banned"))
        return
    if ban.get("kind") == "request":
        db.unban(user.id)
        await msg.answer(t(lang, "unbanned"))
        return
    if time.time() - (ban.get("appealed") or 0) < APPEAL_COOLDOWN:
        await msg.answer(t(lang, "appeal_wait"))
        return
    if not command.args:
        await msg.answer(t(lang, "appeal_usage"))
        return
    # The language is kept to answer in it later.
    db.update_ban(user.id, appealed=int(time.time()), lang=lang)
    text = t(
        "en",
        "admin_appeal",
        user=sender_mention(user),
        id=user.id,
        reason=html.escape(ban.get("reason") or "-"),
        text=html.escape(command.args[:1000]),
    )
    for chat_id in cfg.dev_ids or (STORAGE_CHAT_ID,):
        try:
            await bot.send_message(
                chat_id, text, reply_markup=appeal_keyboard(user.id)
            )
        except Exception as e:
            log.warning("appeal not delivered to %s: %s", chat_id, e)
    await msg.answer(t(lang, "appeal_sent"))


@router.callback_query(F.data.startswith("appeal:"))
async def on_appeal_decided(c: CallbackQuery, bot: Bot):
    """Unban or reject when a developer answers an appeal."""
    in_storage = (
        isinstance(c.message, Message) and c.message.chat.id == STORAGE_CHAT_ID
    )
    if not kit.is_dev(c.from_user) and not (not cfg.dev_ids and in_storage):
        await c.answer()
        return
    _, decision, raw_id = (c.data or "::").split(":", 2)
    if not raw_id.lstrip("-").isdigit():
        await c.answer()
        return
    user_id = int(raw_id)
    if decision == "yes":
        await notify(bot, user_id, "unbanned")
        db.unban(user_id)
        result = t("en", "admin_appeal_yes")
    else:
        await notify(bot, user_id, "appeal_rejected")
        result = t("en", "admin_appeal_no")
    if isinstance(c.message, Message):
        await c.message.edit_text((c.message.html_text or "") + result)
    await c.answer()


@router.message(private)
async def on_other(msg: Message):
    """Hint that a link is expected in private chat."""
    await msg.answer(t(lang_of(msg.chat.id, msg.from_user), "no_link"))


# ---------- handlers: groups ----------

group = F.chat.type.in_({ChatType.GROUP, ChatType.SUPERGROUP})


@router.message(
    F.text.regexp(LINK_RE, mode="search"),
    ~F.text.startswith("/"),
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
    url = find_link(msg.text)
    user_id = msg.from_user.id if msg.from_user else None
    if looks_like_announcement(msg, url):
        log.info("group %s: link in a long text, skipped", msg.chat.id)
        return
    if ban_of(msg.from_user):
        # Silently: a ban is nobody else's business.
        log.info("group %s: link from banned %s", msg.chat.id, user_id)
        return
    mode = cleanup_mode(msg.chat.id)
    lang = lang_of(msg.chat.id, msg.from_user)
    log.info(
        "group %s: %s link from %s, cleanup=%s",
        msg.chat.id,
        platform_of(url),
        user_id,
        mode,
    )
    # In groups with topics, repeats are looked for in the same topic:
    # a reply can't point to a message in another one.
    thread = msg.message_thread_id if msg.is_topic_message else None
    key = f"{thread or 0}:" + await asyncio.to_thread(media_key, url)
    earlier = db.earlier_post(msg.chat.id, key)
    if earlier and await point_to_earlier(bot, msg, earlier, mode, lang):
        return
    await react(bot, msg, REACTION_WORKING)
    try:
        async with ChatActionSender.upload_video(
            bot=bot, chat_id=msg.chat.id, message_thread_id=thread
        ):
            sent_id = await reply_with_media(
                bot,
                msg,
                url,
                as_reply=mode == "keep",
                caption=cleanup_caption(
                    mode,
                    lang,
                    url,
                    msg.from_user,
                    link_comment(msg.text, url),
                ),
            )
    except Exception as e:
        log.exception("download failed: %s", url)
        # The original stays on failure, so the link isn't lost.
        await react(bot, msg, REACTION_FAILED)
        kit.autodelete(await msg.reply(error_text(lang, e)), TTL_SHORT)
        return
    if sent_id is not None:
        db.remember_post(msg.chat.id, key, sent_id)
    if mode == "keep":
        await react(bot, msg, None)
        return
    # The media is sent, so the original message can go. Without the
    # "Delete messages" right this fails, and the message just stays.
    try:
        await msg.delete()
        log.info("deleted the link message in %s", msg.chat.id)
    except Exception as e:
        log.warning("couldn't delete the link message: %s", e)
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
        log.info("earlier post %s is gone: %s", earlier, e)
        return False
    log.info("group %s: repeated link, pointed to %s", msg.chat.id, earlier)
    # A repeat with a comment stays: the media isn't sent again, so the
    # words would have nowhere to go.
    if mode != "keep" and not link_comment(msg.text or "", url_of(msg)):
        try:
            await msg.delete()
        except Exception as e:
            log.warning("couldn't delete the repeated link: %s", e)
    return True


async def can_delete_messages(bot: Bot, chat_id: int) -> bool:
    """Check whether the bot may delete other people's messages."""
    me = await bot.me()
    member = await bot.get_chat_member(chat_id, me.id)
    if member.status == ChatMemberStatus.CREATOR:
        return True
    return member.status == ChatMemberStatus.ADMINISTRATOR and bool(
        getattr(member, "can_delete_messages", False)
    )


def cleanup_keyboard(lang: str, back: bool) -> InlineKeyboardMarkup:
    """Return the /cleanup choices (and "Back" to /settings)."""
    suffix = ":st" if back else ""
    rows = [
        [
            InlineKeyboardButton(
                text=t(lang, f"cleanup_{mode}"),
                callback_data=f"cleanup:{mode}{suffix}",
            )
        ]
        for mode in CLEANUP_MODES
    ]
    if back:
        rows.append(
            [
                InlineKeyboardButton(
                    text=t(lang, "btn.back"), callback_data="kit:back"
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def cleanup_text(lang: str, chat_id: int) -> str:
    """Return the /cleanup question with the current choice."""
    current = t(lang, f"cleanup_{cleanup_mode(chat_id)}")
    now = t(lang, "cleanup_now", mode=current)
    return t(lang, "choose_cleanup") + "\n" + now


@router.message(Command("cleanup"), group)
async def on_group_cleanup(msg: Message):
    """Show admins the choice of what to do with link messages."""
    lang = lang_of(msg.chat.id, msg.from_user)
    if not await kit.can_manage(msg):
        await reply(msg, t(lang, "err.admins_only"), TTL_SHORT)
        return
    await reply(
        msg,
        cleanup_text(lang, msg.chat.id),
        TTL_MEDIUM,
        reply_markup=cleanup_keyboard(lang, back=False),
    )


@router.callback_query(F.data.startswith("cleanup:"))
async def on_group_cleanup_chosen(c: CallbackQuery, bot: Bot):
    """Save the cleanup mode if an admin pressed the button.

    "cleanup:st" opens the choice from /settings; "cleanup:<mode>:st"
    goes back to /settings after saving.
    """
    _, mode, *rest = (c.data or "").split(":")
    msg = c.message
    if not isinstance(msg, Message) or is_private(msg):
        await c.answer()
        return
    lang = lang_of(msg.chat.id, c.from_user)
    # Anyone in the group can press the buttons, so check again.
    if not await kit.can_manage(c):
        await c.answer(t(lang, "err.admins_only"), show_alert=True)
        return
    if mode == "st":
        await c.answer()
        await edit(
            msg,
            cleanup_text(lang, msg.chat.id),
            None,
            reply_markup=cleanup_keyboard(lang, back=True),
        )
        return
    if mode not in CLEANUP_MODES:
        await c.answer()
        return
    db.set_setting(f"cleanup:{msg.chat.id}", mode)
    text = t(lang, "cleanup_set", mode=t(lang, f"cleanup_{mode}"))
    if mode != "keep" and not await can_delete_messages(bot, msg.chat.id):
        text += t(lang, "cleanup_need_right")
    if rest == ["st"]:
        await c.answer(text.split("\n")[0])
        view, kb = settings_view(msg.chat.id, c.from_user.id)
        await edit(msg, view, None, reply_markup=kb)
    else:
        await c.answer()
        await edit(msg, text, TTL_SHORT, reply_markup=None)


async def welcome(bot: Bot, event: ChatMemberUpdated, lang: str) -> str:
    """Return the greeting for a group the bot was added to.

    It also warns if the bot can't see regular messages there.
    """
    # Fresh data, not bot.me(): privacy mode may have been changed
    # while the bot was running.
    me = await bot.get_me()
    is_admin = event.new_chat_member.status == ChatMemberStatus.ADMINISTRATOR
    text = t(lang, "group_hello") + t(lang, "group_lang_hint")
    if not me.can_read_all_group_messages and not is_admin:
        text += t(lang, "group_need_access")
    return text


kit.welcome = welcome
kit.on_chat_moved = db.move_recent
# Banned users get no broadcasts, and their private chats aren't kept.
kit.broadcast_skip = lambda chat_id: db.ban_of(chat_id) is not None
kit.keep_user = lambda user_id: db.ban_of(user_id) is None


# ---------- handlers: inline mode ----------


@router.inline_query()
async def on_inline(q: InlineQuery):
    """Answer an inline query with the video or a placeholder.

    A cached video is sent right away; otherwise a placeholder is
    returned and replaced once the user sends it.
    """
    lang = lang_of(None, q.from_user)
    url = find_link(q.query)
    if not url or ban_of(q.from_user):
        await q.answer([], cache_time=1, is_personal=True)
        return

    key = await asyncio.to_thread(media_key, url)
    file_id = db.media_get("videos", key)
    if file_id and not db.is_blocked(key):
        cached = InlineQueryResultCachedVideo(
            id="c" + result_id(url),
            video_file_id=file_id,
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
    url = find_link(r.query)
    if not url:
        return
    lang = lang_of(None, r.from_user)
    if ban := ban_of(r.from_user):
        await bot.edit_message_text(
            inline_message_id=r.inline_message_id, text=ban_text(lang, ban)
        )
        return

    def show_slow():
        """Replace "Downloading..." with "taking longer than usual"."""
        return bot.edit_message_text(
            inline_message_id=r.inline_message_id,
            text=t(lang, "slow"),
            reply_markup=loading_keyboard(lang),
        )

    try:
        async with slow_notice(show_slow):
            file_id = await get_file_id(bot, url, r.from_user.id)
        await bot.edit_message_media(
            inline_message_id=r.inline_message_id,
            media=InputMediaVideo(media=file_id, supports_streaming=True),
        )
    except Exception as e:
        log.exception("download failed: %s", url)
        await bot.edit_message_text(
            inline_message_id=r.inline_message_id, text=error_text(lang, e)
        )


@router.callback_query(F.data == "noop")
async def on_placeholder_tap(c: CallbackQuery):
    """Handle taps on the placeholder button."""
    await c.answer(t(lang_of(None, c.from_user), "hang_on"))


# ---------- startup ----------


async def main() -> int:
    """Start the bot and run it until /stop or /reload."""
    db.import_json()
    log.info(
        "data folder: %s (cookies: %s)",
        BASE,
        ", ".join(sorted(p.name for p in COOKIES_DIR.iterdir()))
        if COOKIES_DIR.is_dir()
        else "none",
    )
    bot = Bot(
        cfg.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    return await kit.serve(bot, Dispatcher(), router)


if __name__ == "__main__":
    run(main)
