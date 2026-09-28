# pastetiktokvideo

Inline Telegram bot that downloads TikTok videos without watermark.

> [!WARNING]
> **This project is vibe-coded.** It was written with heavy help from AI and hasn't been
> thoroughly reviewed or tested. It works on my machine, but expect rough edges and bugs.
> Use at your own risk, and read the code before running it anywhere important.

Type in any chat:

```
@your_bot https://vm.tiktok.com/xxxxxx
```

pick the result — the bot replaces it with the clean video.

You can also just send a link to the bot in a private chat.

**Languages:** English, Russian, Estonian — picked automatically from the Telegram app language, or manually with `/language`. All texts live in [`texts.py`](texts.py), so adding a language means adding one block there.

## How it works

1. Inline query → the bot instantly returns a placeholder.
2. When the placeholder is sent, the bot downloads the video with [yt-dlp](https://github.com/yt-dlp/yt-dlp), picking a non-watermarked format (H.264 preferred).
3. The video is uploaded to a private "storage" channel to obtain a `file_id`.
4. The placeholder is edited into the video. Repeated links are served instantly from cache.

Photo slideshows are rendered into a video (images + original music) with ffmpeg, since an inline message can hold only one media item.

## Setup

1. Create a bot with [@BotFather](https://t.me/BotFather) (`/newbot`).
2. `/setinline` — enable inline mode.
3. `/setinlinefeedback` — set to **Enabled** (required, otherwise the placeholder never turns into a video).
4. Create a private channel, add the bot as an admin, get its id (`-100...`).
5. Install [ffmpeg](https://ffmpeg.org/) (needed for slideshows): `winget install ffmpeg` on Windows, `apt install ffmpeg` on Debian/Ubuntu.
6. Configure and run:

```bash
git clone https://github.com/artemi372/pastetiktokvideo.git
cd pastetiktokvideo
pip install -r requirements.txt
cp .env.example .env   # fill in BOT_TOKEN and STORAGE_CHAT_ID
python bot.py
```

To stop the bot, type `stop` in the same terminal (or press Ctrl+C).

## Limitations

- Max 50 MB per video (Bot API upload limit).
- Slideshows are parsed from TikTok's web page, which can change without notice.
- TikTok changes things often — if downloads break, run `pip install -U yt-dlp`.
- Cache is in memory and resets on restart.

## Disclaimer

For personal use. Respect creators' rights and TikTok's Terms of Service — don't reupload other people's content as your own.
