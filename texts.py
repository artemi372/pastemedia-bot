"""User-facing texts in all supported languages.

To add a language, add a new block to TEXTS with the same keys and
its name to LANG_NAMES.
"""

DEFAULT_LANG = "en"

LANG_NAMES = {
    "en": "🇬🇧 English",
    "ru": "🇷🇺 Русский",
    "et": "🇪🇪 Eesti",
}

TEXTS = {
    "en": {
        "start": (
            "👋 Hi! I download short videos:\n"
            "• <b>TikTok</b> without watermark (slideshows too)\n"
            "• <b>YouTube Shorts</b>\n"
            "• <b>Instagram Reels</b>\n"
            "\n"
            "<b>In any chat:</b> type <code>@{bot} </code>, paste a link and "
            "tap the result.\n"
            "<b>Here:</b> just send me a link.\n"
            "<b>In groups:</b> add me and I'll reply to links with the "
            "video.\n"
            "\n"
            "/language — change language"
        ),
        "try_button": "🔍 Try in a chat",
        "downloading": "⏳ Downloading video…",
        "loading_button": "⏳ loading…",
        "hang_on": "Hang on, downloading 🙂",
        "inline_title": "📥 Download video",
        "cached_title": "🎬 Video",
        "no_link": (
            "Send me a link to TikTok, YouTube Shorts or Instagram Reels 🙂"
        ),
        "too_big": (
            "❌ The video is larger than 50 MB, Telegram doesn't let bots "
            "send files that big."
        ),
        "failed": (
            "❌ Couldn't download this video. It may be private or deleted, "
            "or the platform blocked the download."
        ),
        "choose_lang": "Choose language:",
        "lang_set": "✅ Language: English",
        "cmd_start": "Start / help",
        "cmd_language": "Change language",
        "restarting": "🔄 The bot is restarting, back in a moment!",
        "bot_short_description": (
            "TikTok without watermark, YouTube Shorts and Instagram Reels: "
            "inline, in private chat and in groups."
        ),
        "bot_description": (
            "📥 Short videos right in Telegram: TikTok without watermark, "
            "YouTube Shorts, Instagram Reels.\n"
            "\n"
            "• Any chat: type @{bot} and paste a link\n"
            "• Private chat: just send me a link\n"
            "• Groups: add me and I'll reply to every link with the video\n"
            "\n"
            "🎞 TikTok photo slideshows become videos with music."
        ),
        "group_hello": (
            "👋 Hi! Post TikTok, YouTube Shorts or Instagram Reels links here "
            "and I'll reply with the video."
        ),
        "group_need_access": (
            "\n"
            "\n"
            "⚠️ Right now I can't see regular messages. Make me an admin, or "
            "ask the bot owner to disable privacy mode."
        ),
    },
    "ru": {
        "start": (
            "👋 Привет! Я скачиваю короткие видео:\n"
            "• <b>TikTok</b> без вотермарки (и слайд-шоу тоже)\n"
            "• <b>YouTube Shorts</b>\n"
            "• <b>Instagram Reels</b>\n"
            "\n"
            "<b>В любом чате:</b> напиши <code>@{bot} </code>, вставь ссылку "
            "и нажми на результат.\n"
            "<b>Здесь:</b> просто пришли мне ссылку.\n"
            "<b>В группах:</b> добавь меня, и я буду отвечать видео на "
            "ссылки.\n"
            "\n"
            "/language — сменить язык"
        ),
        "try_button": "🔍 Попробовать в чате",
        "downloading": "⏳ Скачиваю видео…",
        "loading_button": "⏳ загрузка…",
        "hang_on": "Секунду, качаю 🙂",
        "inline_title": "📥 Скачать видео",
        "cached_title": "🎬 Видео",
        "no_link": (
            "Пришли мне ссылку на TikTok, YouTube Shorts или Instagram Reels "
            "🙂"
        ),
        "too_big": (
            "❌ Видео больше 50 МБ, Telegram не даёт ботам отправлять такие "
            "файлы."
        ),
        "failed": (
            "❌ Не получилось скачать видео. Возможно, оно приватное или "
            "удалено, или платформа заблокировала скачивание."
        ),
        "choose_lang": "Выбери язык:",
        "lang_set": "✅ Язык: русский",
        "cmd_start": "Старт / помощь",
        "cmd_language": "Сменить язык",
        "restarting": "🔄 Бот перезагружается, скоро вернусь!",
        "bot_short_description": (
            "TikTok без вотермарки, YouTube Shorts и Instagram Reels: inline, "
            "в личке и в группах."
        ),
        "bot_description": (
            "📥 Короткие видео прямо в Telegram: TikTok без вотермарки, "
            "YouTube Shorts, Instagram Reels.\n"
            "\n"
            "• В любом чате: напиши @{bot} и вставь ссылку\n"
            "• В личке: просто пришли мне ссылку\n"
            "• В группе: добавь меня, и я отвечу видео на каждую ссылку\n"
            "\n"
            "🎞 Фото-слайдшоу из TikTok превращаю в видео с музыкой."
        ),
        "group_hello": (
            "👋 Привет! Кидайте сюда ссылки на TikTok, YouTube Shorts или "
            "Instagram Reels, я отвечу видео."
        ),
        "group_need_access": (
            "\n"
            "\n"
            "⚠️ Сейчас я не вижу обычные сообщения. Сделайте меня "
            "администратором или попросите владельца бота отключить privacy "
            "mode."
        ),
    },
    "et": {
        "start": (
            "👋 Tere! Laadin alla lühivideoid:\n"
            "• <b>TikTok</b> ilma vesimärgita (ka slaidiesitlused)\n"
            "• <b>YouTube Shorts</b>\n"
            "• <b>Instagram Reels</b>\n"
            "\n"
            "<b>Igas vestluses:</b> kirjuta <code>@{bot} </code>, kleebi link "
            "ja vajuta tulemusele.\n"
            "<b>Siin:</b> saada mulle lihtsalt link.\n"
            "<b>Gruppides:</b> lisa mind ja vastan linkidele videoga.\n"
            "\n"
            "/language — muuda keelt"
        ),
        "try_button": "🔍 Proovi vestluses",
        "downloading": "⏳ Laadin videot alla…",
        "loading_button": "⏳ laadimine…",
        "hang_on": "Hetk, laadin alla 🙂",
        "inline_title": "📥 Laadi video alla",
        "cached_title": "🎬 Video",
        "no_link": (
            "Saada mulle TikToki, YouTube Shortsi või Instagram Reelsi link 🙂"
        ),
        "too_big": (
            "❌ Video on suurem kui 50 MB, Telegram ei luba bottidel nii "
            "suuri faile saata."
        ),
        "failed": (
            "❌ Videot ei õnnestunud alla laadida. See võib olla privaatne "
            "või kustutatud või blokeeris platvorm allalaadimise."
        ),
        "choose_lang": "Vali keel:",
        "lang_set": "✅ Keel: eesti",
        "cmd_start": "Alusta / abi",
        "cmd_language": "Muuda keelt",
        "restarting": "🔄 Bot taaskäivitub, olen kohe tagasi!",
        "bot_short_description": (
            "TikTok ilma vesimärgita, YouTube Shorts ja Instagram Reels: "
            "inline, privaatselt ja gruppides."
        ),
        "bot_description": (
            "📥 Lühivideod otse Telegramis: TikTok ilma vesimärgita, YouTube "
            "Shorts, Instagram Reels.\n"
            "\n"
            "• Igas vestluses: kirjuta @{bot} ja kleebi link\n"
            "• Privaatselt: saada mulle lihtsalt link\n"
            "• Grupis: lisa mind ja vastan igale lingile videoga\n"
            "\n"
            "🎞 TikToki fotoslaidiesitlustest teen muusikaga video."
        ),
        "group_hello": (
            "👋 Tere! Saatke siia TikToki, YouTube Shortsi või Instagram "
            "Reelsi linke ja ma vastan videoga."
        ),
        "group_need_access": (
            "\n"
            "\n"
            "⚠️ Praegu ma ei näe tavalisi sõnumeid. Tehke mind "
            "administraatoriks või paluge boti omanikul privacy mode välja "
            "lülitada."
        ),
    },
}


def detect_lang(language_code: str | None) -> str:
    """Map a Telegram language_code to a supported language.

    For example, "et" and "en-US" become "et" and "en"; unsupported
    languages fall back to DEFAULT_LANG.
    """
    code = (language_code or "").lower().split("-")[0]
    return code if code in TEXTS else DEFAULT_LANG


def t(lang: str, key: str, **kwargs) -> str:
    """Return a text by key in the given language.

    Missing languages and keys fall back to DEFAULT_LANG. Keyword
    arguments are substituted into the text with str.format().
    """
    text = TEXTS.get(lang, TEXTS[DEFAULT_LANG]).get(key)
    text = text or TEXTS[DEFAULT_LANG][key]
    return text.format(**kwargs) if kwargs else text
