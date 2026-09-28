# pastemedia-bot

Telegram bot that downloads short videos: **TikTok** without watermark, **YouTube Shorts** and **Instagram Reels**.

> [!WARNING]
> **This project is vibe-coded.** It was written with heavy help from AI and hasn't been
> thoroughly reviewed or tested. It works on my machine, but expect rough edges and bugs.
> Use at your own risk, and read the code before running it anywhere important.

Type in any chat:

```
@your_bot https://vm.tiktok.com/xxxxxx
```

pick the result — the bot replaces it with the video.

You can also just send a link to the bot in a private chat, or **add it to a group**: it will reply to any message with a supported link with the video. Error messages delete themselves after 15 seconds to keep chats clean.

| Platform | Links | Status |
|---|---|---|
| TikTok | videos, photo slideshows (sent as albums) | ✅ stable |
| YouTube | Shorts only (`youtube.com/shorts/...`) | ⚠️ works from home IPs; servers often get blocked |
| Instagram | Reels and video posts | ⚠️ often needs cookies from a logged-in account |

**Languages:** English, Russian, Estonian — picked automatically from the Telegram app language, or manually with `/language`. In groups, admins can set one language for the whole group with `/language`. All texts live in [`texts.py`](texts.py), so adding a language means adding one block there.

## How it works

1. Inline query → the bot instantly returns a placeholder.
2. When the placeholder is sent, the bot downloads the video with [yt-dlp](https://github.com/yt-dlp/yt-dlp): a non-watermarked format for TikTok, the best H.264 + AAC up to 1080p for YouTube and Instagram (other codecs don't play on some Telegram clients).
3. The video is uploaded to a private "storage" channel to obtain a `file_id`.
4. The placeholder is edited into the video. Repeated links are served instantly from cache.

TikTok photo slideshows are sent as photo albums (up to 10 per album, without sound) in private chats and groups. In inline mode they are rendered into a video with the original music, since an inline message can hold only one media item.

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
cp .env.example .env   # fill in BOT_TOKEN and STORAGE_CHAT_ID
python bot.py
```

To stop the bot, type `stop` in the same terminal (or press Ctrl+C).

The bot shows its status in its Telegram profile: 🟢 Online while running, 🔴 Offline after a normal stop.

When the bot stops, it posts a "restarting" message in every group it's in, and deletes those messages on the next start. The list of groups, per-user and per-group settings (like the chosen language) are kept in `state.json`, so they survive restarts (runtime data, keep it out of git). A hard crash or power loss skips the notice and the offline status.

### Cookies (optional, for Instagram / YouTube)

If Instagram or YouTube refuses downloads ("login required", "sign in to confirm you're not a bot"), export cookies from a browser where you're logged in (e.g. with the *Get cookies.txt LOCALLY* extension) and save them as:

```
cookies/instagram.txt
cookies/youtube.txt
```

The bot picks them up automatically. **Use a throwaway account**, not your main one: platforms may ban accounts used for automated downloads. Cookies are as secret as a password, so the `cookies/` folder must be in `.gitignore`.

## Limitations

- Max 50 MB per video (Bot API upload limit).
- YouTube and Instagram actively fight downloaders, so they break more often than TikTok.
- Slideshows are parsed from TikTok's web page, which can change without notice.
- Platforms change things often — if downloads break, run `pip install -U "yt-dlp[default]"`.
- Cache is in memory and resets on restart.

## Disclaimer

For personal use. Respect creators' rights and the platforms' Terms of Service — don't reupload other people's content as your own.
