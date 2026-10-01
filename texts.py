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
            "• <b>TikTok</b> without watermark (slideshows as albums)\n"
            "• <b>YouTube Shorts</b>\n"
            "• <b>Instagram</b> Reels and posts (carousels as albums)\n"
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
        "admins_only": "Only group admins can change these settings.",
        "choose_group_lang": "Choose the language for this group:",
        "group_lang_set": "✅ Group language: English",
        "cmd_group_language": "Change the group language (admins)",
        "group_lang_hint": (
            "\n"
            "\n"
            "Admins: /language changes my language, /notices turns restart "
            "notices on or off."
        ),
        "status_online": "🟢 Online",
        "status_offline": "🔴 Offline",
        "slow": "⏳ This is taking longer than usual…",
        "timeout": "❌ The download took too long. Please try again later.",
        "shutting_down": "🌙 The bot is off for now, back later.",
        "owner_stop": "🌙 Shutting down.",
        "owner_restart": "🔄 Restarting, back in a few seconds.",
        "owner_quiet": " Groups won't be notified.",
        "cmd_group_notices": "Restart notices on/off (admins)",
        "choose_notices": "Should I post here when I restart or shut down?",
        "notices_now_on": "Now: 🔔 on",
        "notices_now_off": "Now: 🔕 off",
        "notices_on_button": "🔔 Yes",
        "notices_off_button": "🔕 No",
        "notices_set_on": "🔔 Restart and shutdown notices are on.",
        "notices_set_off": "🔕 Restart and shutdown notices are off.",
        "source_line": "\n\n👤 Author: @{author}\n🧩 Open source: {repo}",
        "cmd_help": "Help and commands",
        "cmd_group_cleanup": "What to do with link messages (admins)",
        "help": (
            "<b>How to use</b>\n"
            "• Private chat: send me a link, I reply with the video\n"
            "• Any chat: type <code>@{bot} </code>, paste a link and tap the "
            "result\n"
            "• Groups: add me, and I reply to every link with the video\n"
            "\n"
            "<b>Commands</b> (who can use them)\n"
            "/start — welcome message (everyone)\n"
            "/help — this help (everyone)\n"
            "/language — in private: your language (everyone); in groups: the "
            "group language (admins)\n"
            "/notices — restart and shutdown messages in the group (admins)\n"
            "/cleanup — what to do with link messages in the group (admins)"
        ),
        "choose_cleanup": (
            "What should I do with the message that has the link, once the "
            "video is sent?"
        ),
        "cleanup_keep": "Keep it, reply to it",
        "cleanup_link_user": "Delete, show link + sender",
        "cleanup_user": "Delete, show sender",
        "cleanup_none": "Delete, video only",
        "cleanup_now": "Now: {mode}",
        "cleanup_set": "✅ Done: {mode}",
        "cleanup_need_right": (
            "\n"
            "\n"
            "⚠️ I can't delete messages here yet: make me an admin with the "
            "“Delete messages” permission."
        ),
        "sent_by": "👤 Sent by {user}",
        "login_needed": (
            "🔞 This post is only shown to logged-in adults, so I can't"
            " download it."
        ),
        "already_posted": (
            "🔁 {user}, this one was already posted, here it is."
        ),
        "already_posted_anon": "🔁 This one was already posted, here it is.",
        "link_line": "🔗 {link}",
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
            "🎞 TikTok slideshows come as photo albums."
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
            "• <b>TikTok</b> без вотермарки (слайд-шоу — альбомом)\n"
            "• <b>YouTube Shorts</b>\n"
            "• <b>Instagram</b>: рилсы и посты (карусели — альбомом)\n"
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
        "admins_only": "Менять настройки могут только админы группы.",
        "choose_group_lang": "Выберите язык для этой группы:",
        "group_lang_set": "✅ Язык группы: русский",
        "cmd_group_language": "Сменить язык группы (админы)",
        "group_lang_hint": (
            "\n"
            "\n"
            "Админам: /language меняет мой язык, /notices включает или "
            "выключает уведомления о перезапуске."
        ),
        "status_online": "🟢 Работает",
        "status_offline": "🔴 Выключен",
        "slow": "⏳ Это занимает больше времени, чем обычно…",
        "timeout": (
            "❌ Скачивание заняло слишком много времени. Попробуй позже."
        ),
        "shutting_down": "🌙 Бот выключен, вернусь позже.",
        "owner_stop": "🌙 Выключаюсь.",
        "owner_restart": "🔄 Перезапускаюсь, вернусь через пару секунд.",
        "owner_quiet": " Группам ничего не пишу.",
        "cmd_group_notices": "Уведомления о рестарте (админы)",
        "choose_notices": (
            "Писать сюда, когда я перезапускаюсь или выключаюсь?"
        ),
        "notices_now_on": "Сейчас: 🔔 включены",
        "notices_now_off": "Сейчас: 🔕 выключены",
        "notices_on_button": "🔔 Да",
        "notices_off_button": "🔕 Нет",
        "notices_set_on": (
            "🔔 Уведомления о перезапуске и выключении включены."
        ),
        "notices_set_off": (
            "🔕 Уведомления о перезапуске и выключении выключены."
        ),
        "source_line": "\n\n👤 Автор: @{author}\n🧩 Исходный код: {repo}",
        "cmd_help": "Помощь и команды",
        "cmd_group_cleanup": "Что делать с сообщениями-ссылками (админы)",
        "help": (
            "<b>Как пользоваться</b>\n"
            "• В личке: пришли ссылку, я отвечу видео\n"
            "• В любом чате: напиши <code>@{bot} </code>, вставь ссылку и "
            "нажми на результат\n"
            "• В группах: добавь меня, и я буду отвечать видео на каждую "
            "ссылку\n"
            "\n"
            "<b>Команды</b> (кому доступны)\n"
            "/start — приветствие (всем)\n"
            "/help — эта справка (всем)\n"
            "/language — в личке: твой язык (всем); в группе: язык группы "
            "(админам)\n"
            "/notices — сообщения о перезапуске и выключении в группе "
            "(админам)\n"
            "/cleanup — что делать с сообщениями-ссылками в группе (админам)"
        ),
        "choose_cleanup": (
            "Что делать с сообщением со ссылкой, когда видео отправлено?"
        ),
        "cleanup_keep": "Оставить, ответить на него",
        "cleanup_link_user": "Удалить, указать ссылку и автора",
        "cleanup_user": "Удалить, указать автора",
        "cleanup_none": "Удалить, только видео",
        "cleanup_now": "Сейчас: {mode}",
        "cleanup_set": "✅ Готово: {mode}",
        "cleanup_need_right": (
            "\n"
            "\n"
            "⚠️ Пока я не могу здесь удалять сообщения: сделайте меня админом "
            "с правом «Удаление сообщений»."
        ),
        "sent_by": "👤 Прислал(а) {user}",
        "login_needed": (
            "🔞 Этот пост показывают только взрослым залогиненным"
            " пользователям, скачать не получится."
        ),
        "already_posted": "🔁 {user}, это уже скидывали, вот оно.",
        "already_posted_anon": "🔁 Это уже скидывали, вот оно.",
        "link_line": "🔗 {link}",
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
            "🎞 Слайд-шоу из TikTok присылаю альбомом фотографий."
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
            "• <b>TikTok</b> ilma vesimärgita (slaidiesitlused albumina)\n"
            "• <b>YouTube Shorts</b>\n"
            "• <b>Instagram</b> Reels ja postitused (karussellid albumina)\n"
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
        "admins_only": "Seadeid saavad muuta ainult grupi administraatorid.",
        "choose_group_lang": "Vali selle grupi keel:",
        "group_lang_set": "✅ Grupi keel: eesti",
        "cmd_group_language": "Muuda grupi keelt (adminid)",
        "group_lang_hint": (
            "\n"
            "\n"
            "Adminidele: /language muudab minu keelt, /notices lülitab "
            "taaskäivituse teated sisse või välja."
        ),
        "status_online": "🟢 Töötab",
        "status_offline": "🔴 Väljas",
        "slow": "⏳ See võtab tavapärasest kauem aega…",
        "timeout": (
            "❌ Allalaadimine võttis liiga kaua aega. Proovi hiljem uuesti."
        ),
        "shutting_down": "🌙 Bot on välja lülitatud, tulen hiljem tagasi.",
        "owner_stop": "🌙 Lülitun välja.",
        "owner_restart": "🔄 Taaskäivitun, olen paari sekundi pärast tagasi.",
        "owner_quiet": " Gruppidele ei kirjuta.",
        "cmd_group_notices": "Taaskäivituse teated (adminid)",
        "choose_notices": (
            "Kas teatada siin, kui ma taaskäivitun või välja lülitun?"
        ),
        "notices_now_on": "Praegu: 🔔 sees",
        "notices_now_off": "Praegu: 🔕 väljas",
        "notices_on_button": "🔔 Jah",
        "notices_off_button": "🔕 Ei",
        "notices_set_on": (
            "🔔 Taaskäivituse ja väljalülitamise teated on sees."
        ),
        "notices_set_off": (
            "🔕 Taaskäivituse ja väljalülitamise teated on väljas."
        ),
        "source_line": "\n\n👤 Autor: @{author}\n🧩 Lähtekood: {repo}",
        "cmd_help": "Abi ja käsud",
        "cmd_group_cleanup": "Mida teha linkidega sõnumitega (adminid)",
        "help": (
            "<b>Kuidas kasutada</b>\n"
            "• Privaatselt: saada mulle link, vastan videoga\n"
            "• Igas vestluses: kirjuta <code>@{bot} </code>, kleebi link ja "
            "vajuta tulemusele\n"
            "• Gruppides: lisa mind ja vastan igale lingile videoga\n"
            "\n"
            "<b>Käsud</b> (kes saab kasutada)\n"
            "/start — tervitus (kõik)\n"
            "/help — see abi (kõik)\n"
            "/language — privaatselt: sinu keel (kõik); grupis: grupi keel "
            "(adminid)\n"
            "/notices — taaskäivituse ja väljalülitamise teated grupis "
            "(adminid)\n"
            "/cleanup — mida teha linkidega sõnumitega grupis (adminid)"
        ),
        "choose_cleanup": "Mida teha lingiga sõnumiga, kui video on saadetud?",
        "cleanup_keep": "Jäta alles, vasta sellele",
        "cleanup_link_user": "Kustuta, näita linki ja saatjat",
        "cleanup_user": "Kustuta, näita saatjat",
        "cleanup_none": "Kustuta, ainult video",
        "cleanup_now": "Praegu: {mode}",
        "cleanup_set": "✅ Valmis: {mode}",
        "cleanup_need_right": (
            "\n"
            "\n"
            "⚠️ Ma ei saa siin veel sõnumeid kustutada: tehke mind adminiks "
            "õigusega „Sõnumite kustutamine”."
        ),
        "sent_by": "👤 Saatis {user}",
        "login_needed": (
            "🔞 Seda postitust näidatakse ainult sisse logitud"
            " täiskasvanutele, ma ei saa seda alla laadida."
        ),
        "already_posted": "🔁 {user}, see oli juba siin, vaata siit.",
        "already_posted_anon": "🔁 See oli juba siin, vaata siit.",
        "link_line": "🔗 {link}",
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
            "🎞 TikToki slaidiesitlused saadan fotoalbumina."
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
