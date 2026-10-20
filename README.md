# pastemedia-bot

Telegram bot that downloads short videos and posts: **TikTok** without watermark, **YouTube Shorts**, **Instagram** Reels and posts.

Made by [@artemi372](https://t.me/artemi372) · try it: [@mediapastebot](https://t.me/mediapastebot)

> [!WARNING]
> **This project is vibe-coded.** It was written with heavy help from AI and hasn't been
> thoroughly reviewed or tested. It works on my machine, but expect rough edges and bugs.
> Use at your own risk, and read the code before running it anywhere important.

> [!NOTE]
> **Instagram needs cookies** from a logged-in account, and YouTube may ask for them too — see [Cookies](#cookies-optional-for-instagram--youtube).

Type in any chat:

```
@your_bot https://vm.tiktok.com/xxxxxx
```

pick the result — the bot replaces it with the video.

You can also just send a link to the bot in a private chat, or **add it to a group**: it will reply to any message with a supported link with the video. While downloading, the bot puts 👀 on the message with the link (removed when done, 🤷 on failure). In groups, the bot's service messages and the commands sent to it delete themselves after 15 s – 2 min to keep the chat clean (`AUTO_DELETE=0` turns this off); videos stay.

### Commands

| Command | Where | Who |
|---|---|---|
| `/start` | private chat | everyone |
| `/help` | everywhere | everyone |
| `/settings` | private chat: your language; group: language, restart notices, link messages | everyone / group admins |
| `/language` | private chat: your language; group: the group language | everyone / group admins |
| `/cleanup` | group: what to do with the message that has the link | group admins |
| `/privacy`, `/terms` | everywhere: short summary and a link to the full text | everyone |
| `/id` | everywhere: chat and user ID | everyone |
| `/appeal` | private chat: ask to be unbanned | banned users |

Group admins also means anonymous admins.

`/cleanup` modes: keep the message and reply to it (default); or delete it and post the media as a separate message with the link and the sender, with the sender only, or with nothing. Deleting needs the bot to be a group admin with the *Delete messages* permission. Whatever the sender wrote next to the link ("lol look at this") is copied under the media as 💬, so it isn't lost. If the download fails, the message is never deleted.

If someone posts a video that was already sent in the group (one of the last 50, within a week), the bot doesn't send it again: it replies to the earlier video with "🔁 already posted". Short and full links to the same post count as the same video.

Settings and the recent videos survive a group turning into a supergroup (Telegram gives it a new id then, e.g. after admins change some group settings).

| Platform | Links | Status |
|---|---|---|
| TikTok | videos, photo slideshows (sent as albums) | ✅ stable |
| YouTube | Shorts only (`youtube.com/shorts/...`) | ⚠️ works from home IPs; servers often get blocked |
| Instagram | Reels, posts and carousels (photos + videos, sent as albums) | ⚠️ needs cookies from a logged-in account |

**Languages:** English, Russian, Estonian — picked automatically from the Telegram app language, or manually with `/language`. A group speaks the language of whoever added the bot until admins pick one in `/settings` or with `/language`; they can turn restart/shutdown messages on or off in `/settings`. The bot's texts live in [`texts.py`](texts.py), the shared ones in [`botkit/texts.py`](botkit/texts.py).

## How it works

1. Inline query → the bot instantly returns a placeholder.
2. When the placeholder is sent, the bot downloads the video with [yt-dlp](https://github.com/yt-dlp/yt-dlp): a non-watermarked format for TikTok, the best H.264 + AAC up to 1080p for YouTube and Instagram (other codecs don't play on some Telegram clients).
3. The video is uploaded to a private "storage" channel to obtain a `file_id`.
4. The placeholder is edited into the video. Repeated links are served instantly from cache.

Each video is uploaded to the storage channel only once: the `file_id`s are saved in the database (`data/bot.db`, out of git), so they survive restarts, and short and full links to one post share an entry.

TikTok photo slideshows and Instagram carousels are sent as albums (up to 10 items per album) in private chats and groups; Instagram albums can mix photos and videos. In inline mode, where a message can hold only one media item, TikTok slideshows become a video with the original music, and Instagram posts send their first video, or a slideshow video if the post has only photos. Instagram posts are listed and downloaded with [gallery-dl](https://github.com/mikf/gallery-dl).

## Setup

1. Create a bot with [@BotFather](https://t.me/BotFather) (`/newbot`).
2. `/setinline` — enable inline mode.
3. `/setinlinefeedback` — set to **Enabled** (required, otherwise the placeholder never turns into a video).
4. Create a private channel, add the bot as an admin, get its id (`-100...`).
   - *(For groups)* `/setprivacy` → **Disable**, so the bot can see regular messages with links. Then remove and re-add the bot to existing groups, the change only applies after that. Alternatively, make the bot an admin in the group.
5. Install [ffmpeg](https://ffmpeg.org/) (slideshows, merging YouTube video + audio) and [Deno](https://deno.com/) (required by yt-dlp for YouTube):
   - Windows: `winget install ffmpeg` and `winget install DenoLand.Deno`
   - Debian/Ubuntu: `apt install ffmpeg` and `curl -fsSL https://deno.land/install.sh | sh`
6. Configure and run:

```bash
git clone https://github.com/artemi372/pastemedia-bot.git
cd pastemedia-bot
pip install -r requirements.txt
cp .env.example .env   # fill in BOT_TOKEN, STORAGE_CHAT_ID and DEV_IDS
python bot.py
```

The bot restarts itself after `/reload` (see [botkit](#botkit-shared-with-warden)). With systemd, use `Restart=on-failure`: `Restart=always` would start the bot again right after `/stop`.

**Developers** are the Telegram user ids in `DEV_IDS` (comma-separated; `/id` shows yours). Only they see and can use the commands below; for everyone else they don't exist.

Commands in the terminal where the bot runs, or `/stop` and `/reload` in Telegram:

- `stop` — shut the bot down; groups get "🌙 Media Paste Bot is off for now — back later." and the profile shows 🔴 Offline
- `reload` — restart with the latest code and `.env`; groups get "🔄 Media Paste Bot is restarting", and the bot is back a few seconds later
- add `quiet` (`stop quiet`, `reload quiet`) to skip the messages in groups, e.g. while testing
- `status` — how many chats the bot knows

Group admins can turn these messages off for their group in `/settings`. Ctrl+C or a service stop shut the bot down without messages. Use these instead of closing the window or the PyCharm Stop button: those kill the bot before it can update its status. The bot shows its status in its Telegram profile: 🟢 Online while running, 🔴 Offline after a stop. The group messages are cleaned up on the next start ("off for now" turns into "back online" for a minute). A hard crash or power loss skips the notice and the offline status.

**Moderation** (developers). Post these in the **storage channel**, where only you can post, or send them to the bot in private chat:

- `/ban` as a reply to a stored video bans whoever requested it (known for 7 days), or `/ban <user id> [reason]`. A reason starting with `request` marks a ban the user asked for (e.g. under the privacy policy): their settings are deleted, and they can lift it themselves with `/appeal`.
- `/unban <user id>`
- `/block` as a reply to a stored video (the one with the link caption), or `/block <link> [reason]`: the post is never downloaded again, its cached copy is forgotten and the stored one deleted. `/unblock <link>` allows it again.
- `/bans` lists banned users and blocked posts.

In the storage channel, the command and the answer delete themselves after a minute. Banned users get a message with the reason; their links are ignored silently in groups. With `/appeal <why>` they send the developers an appeal with Unban/Reject buttons, at most once a day.

**Broadcast** (developers, private chat): `/broadcast` opens a panel: 🔔 with sound or 🔕 silent, all chats or one language (`en`, `ru`, `et`). The announcement is a **reply to that panel**: text with formatting, a photo with a caption, anything (one message, not an album). HTML that starts with `<` goes out as a rich message (tables, lists, headings). The bot shows what will be sent with "✅ Send to N chats" and "Cancel"; nothing goes out until you press Send. The panel stays open, so patch notes can go out once per language: switch the language, reply with the next text. `/broadcast silent ru` opens the panel with those already picked.

It goes to every group and every user who wrote to the bot privately, except you and banned users. Flood limits are waited out; groups and users that blocked or kicked the bot are skipped from then on and reported as unreachable. Users who only use the bot inline can't be messaged.

In groups, the bot ignores links inside long texts (over 200 characters besides the link) or messages with more than two links, so announcements and ads with an Instagram link aren't reposted.

Known chats, settings, the `file_id` cache, recent videos, bans and blocked posts are kept in `data/bot.db` (runtime data, out of git). An older `state.json` and `media_cache.json` are imported on the first start and renamed to `*.imported`.

### Cookies (optional, for Instagram / YouTube)

If Instagram or YouTube refuses downloads ("login required", "sign in to confirm you're not a bot"), export cookies from a browser where you're logged in (e.g. with the *Get cookies.txt LOCALLY* extension) and save them as:

```
cookies/instagram.txt
cookies/youtube.txt
cookies/tiktok.txt
```

The bot picks them up automatically. **Use a throwaway account**, not your main one: platforms may ban accounts used for automated downloads. Cookies are as secret as a password, so the `cookies/` folder must be in `.gitignore`.

## Limitations

- Max 50 MB per video (Bot API upload limit). The bot first picks the best quality that fits; if a video is still too big, it's re-encoded with ffmpeg (one at a time, it takes a minute or two on a small server). Videos too long to look decent in 50 MB (roughly over 12 minutes) are refused. Albums aren't compressed.
- YouTube and Instagram actively fight downloaders, so they break more often than TikTok.
- Slideshows are parsed from TikTok's web page, which can change without notice.
- Platforms change things often — if downloads break, run `pip install -U "yt-dlp[default]"`.

## botkit (shared with Warden)

Everything this bot does the same way as [@dotawardenbot](https://t.me/dotawardenbot) lives in [`botkit/`](botkit), and the folder is **identical in both projects**: change it in one, then copy the whole folder to the other (`tests/test_botkit.py` too).

| File | Contents |
|---|---|
| `config.py` | settings every bot has: `BOT_TOKEN`, `DEV_IDS`, `DEFAULT_LANG`, author, legal links, `AUTO_DELETE` |
| `store.py` | SQLite tables: known chats (language, restart notices, reachable or not), settings, deletion queue |
| `i18n.py`, `texts.py` | `t(lang, key)` and the shared texts in English, Russian and Estonian; a bot's own text wins |
| `core.py` | languages, permissions (anonymous admins too), auto-deletion that survives restarts, safe sending (flood limits, supergroups, blocked chats), the profile status, command menus, restart notices |
| `handlers.py` | `/privacy`, `/terms`, `/id`, `/language`, `/broadcast`, `/reload`, `/stop`, groups becoming supergroups, the bot being added or removed |
| `rich.py` | rich messages (tables, lists, headings) with a fallback to ordinary HTML |
| `runner.py` | the supervisor that restarts the bot on `/reload`, console commands, keeping Windows awake |

Logs and the console speak English; users get their own language. Tests: `python -m pytest tests`. Style: `ruff check .` and `ruff format .` (PEP 8, PEP 257, see `ruff.toml`).

## Privacy and terms

The official bot's [Privacy Policy](https://telegra.ph/Media-Paste-Bot--Privacy-Policy-10-07) and [Terms of Use](https://telegra.ph/Media-Paste-Bot--Terms-of-Use-10-07) are linked from `/privacy`, `/terms`, `/help` and the bot's profile. Telegram requires every bot to have a privacy policy, so if you run your own copy, publish your own and set `PRIVACY_URL` and `TERMS_URL` in `.env` (an empty value hides the link). Also add the privacy link in @BotFather.

## Disclaimer

For personal use. Respect creators' rights and the platforms' Terms of Service — don't reupload other people's content as your own.

Use a separate (throwaway) account for cookies, never your main one: platforms may ban accounts used for automated downloads. Cookies are as secret as a password — keep the `cookies/` folder out of git. The bot reads them on every download, so no restart is needed after replacing them.

## Troubleshooting

**"Sign in to confirm you're not a bot" (YouTube) or "login required" (Instagram)** — add or refresh cookies (see above). For YouTube, export them from a private/incognito window: log in, open `youtube.com/robots.txt` in the same tab, export, then close the window and never open that session again (YouTube rotates cookies in open tabs).

**Instagram: HTTP 400 / "content may be inappropriate"** — Instagram hides some posts from the account used for cookies. On that account:
1. Set a birthday that makes it 18+ (*Accounts Center → Personal details → Birthday*).
2. Set *Settings → Suggested content → Sensitive content* to *Standard* (or *More* where available).
3. Open the post in the browser to check it shows, then export cookies again.

**YouTube: "Sign in to confirm your age"** — the video is age-restricted. It needs cookies from an 18+ account; in the EU, YouTube may also ask that account to verify its age. Age-restricted Shorts are rare.

**Downloads suddenly break everywhere** — the platform changed something. Update the downloaders: `pip install -U -r requirements.txt`. If yt-dlp fails on an Instagram Reel, the bot automatically retries with gallery-dl.

**TikTok: "This post may not be comfortable for some audiences"** — TikTok hides some posts from logged-out viewers. Save cookies from an 18+ TikTok account as `cookies/tiktok.txt`.

**Can't be fixed on the bot's side:** private or deleted posts, and videos blocked in your country.

## Author

[@artemi372](https://t.me/artemi372) on Telegram — questions, bugs and ideas are welcome there or in [Issues](https://github.com/artemi372/pastemedia-bot/issues).
