"""User-facing texts in all supported languages.

To add a language: add a new block to TEXTS with the same keys, and a name to LANG_NAMES.
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
            "👋 Hi! I download TikTok videos without watermark.\n\n"
            "<b>In any chat:</b> type <code>@{bot} </code>, paste a TikTok link and tap the result.\n"
            "<b>Here:</b> just send me a link.\n\n"
            "Photo slideshows are turned into a video with music.\n\n"
            "/language — change language"
        ),
        "try_button": "🔍 Try in a chat",
        "downloading": "⏳ Downloading video…",
        "loading_button": "⏳ loading…",
        "hang_on": "Hang on, downloading 🙂",
        "inline_title": "📥 Download TikTok without watermark",
        "cached_title": "🎬 TikTok without watermark",
        "no_link": "Send me a TikTok link 🙂",
        "too_big": "❌ The video is larger than 50 MB, Telegram doesn't let bots send files that big.",
        "failed": "❌ Couldn't download this video. It may be private or deleted, or TikTok changed something.",
        "choose_lang": "Choose language:",
        "lang_set": "✅ Language: English",
        "cmd_start": "Start / help",
        "cmd_language": "Change language",
        "group_hello": "👋 Hi! Post a TikTok link here and I'll reply with the video without watermark.",
        "group_need_access": (
            "\n\n⚠️ Right now I can't see regular messages. "
            "Make me an admin, or ask the bot owner to disable privacy mode."
        ),
    },
    "ru": {
        "start": (
            "👋 Привет! Я скачиваю видео из TikTok без вотермарки.\n\n"
            "<b>В любом чате:</b> напиши <code>@{bot} </code>, вставь ссылку на TikTok и нажми на результат.\n"
            "<b>Здесь:</b> просто пришли мне ссылку.\n\n"
            "Фото-слайдшоу превращаю в видео с музыкой.\n\n"
            "/language — сменить язык"
        ),
        "try_button": "🔍 Попробовать в чате",
        "downloading": "⏳ Скачиваю видео…",
        "loading_button": "⏳ загрузка…",
        "hang_on": "Секунду, качаю 🙂",
        "inline_title": "📥 Скачать TikTok без вотермарки",
        "cached_title": "🎬 TikTok без вотермарки",
        "no_link": "Пришли мне ссылку на TikTok 🙂",
        "too_big": "❌ Видео больше 50 МБ, Telegram не даёт ботам отправлять такие файлы.",
        "failed": "❌ Не получилось скачать видео. Возможно, оно приватное или удалено, или TikTok что-то поменял.",
        "choose_lang": "Выбери язык:",
        "lang_set": "✅ Язык: русский",
        "cmd_start": "Старт / помощь",
        "cmd_language": "Сменить язык",
        "group_hello": "👋 Привет! Кидайте сюда ссылки на TikTok, я отвечу видео без вотермарки.",
        "group_need_access": (
            "\n\n⚠️ Сейчас я не вижу обычные сообщения. "
            "Сделайте меня администратором или попросите владельца бота отключить privacy mode."
        ),
    },
    "et": {
        "start": (
            "👋 Tere! Laadin TikToki videod alla ilma vesimärgita.\n\n"
            "<b>Igas vestluses:</b> kirjuta <code>@{bot} </code>, kleebi TikToki link ja vajuta tulemusele.\n"
            "<b>Siin:</b> saada mulle lihtsalt link.\n\n"
            "Fotoslaidiesitlustest teen muusikaga video.\n\n"
            "/language — muuda keelt"
        ),
        "try_button": "🔍 Proovi vestluses",
        "downloading": "⏳ Laadin videot alla…",
        "loading_button": "⏳ laadimine…",
        "hang_on": "Hetk, laadin alla 🙂",
        "inline_title": "📥 Laadi TikTok alla ilma vesimärgita",
        "cached_title": "🎬 TikTok ilma vesimärgita",
        "no_link": "Saada mulle TikToki link 🙂",
        "too_big": "❌ Video on suurem kui 50 MB, Telegram ei luba bottidel nii suuri faile saata.",
        "failed": "❌ Videot ei õnnestunud alla laadida. See võib olla privaatne või kustutatud või muutis TikTok midagi.",
        "choose_lang": "Vali keel:",
        "lang_set": "✅ Keel: eesti",
        "cmd_start": "Alusta / abi",
        "cmd_language": "Muuda keelt",
        "group_hello": "👋 Tere! Saatke siia TikToki linke ja ma vastan videoga ilma vesimärgita.",
        "group_need_access": (
            "\n\n⚠️ Praegu ma ei näe tavalisi sõnumeid. "
            "Tehke mind administraatoriks või paluge boti omanikul privacy mode välja lülitada."
        ),
    },
}


def detect_lang(language_code: str | None) -> str:
    """Map a Telegram language_code (e.g. 'ru', 'et', 'en-US') to a supported language."""
    code = (language_code or "").lower().split("-")[0]
    return code if code in TEXTS else DEFAULT_LANG


def t(lang: str, key: str, **kwargs) -> str:
    """Get a text by key in the given language, falling back to the default language."""
    text = TEXTS.get(lang, TEXTS[DEFAULT_LANG]).get(key) or TEXTS[DEFAULT_LANG][key]
    return text.format(**kwargs) if kwargs else text
