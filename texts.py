"""User-facing texts in all supported languages.

Usage::

    t("en", "downloading")  ->  "⏳ Downloading video…"

The shared texts (language, legal, broadcast, status) come from
botkit/texts.py; a key defined here wins over botkit's. To add a
language, copy the "en" block, translate the values and add the
language code to LANGS (and to botkit/texts.py). A missing key falls
back to the default language, then to English, then to the key
itself, so the bot never fails on a missing translation.
"""

from botkit import i18n
from botkit.i18n import normalize, t

LANGS = ("en", "ru", "et")
DEFAULT_LANG = "en"

TEXTS: dict[str, dict[str, str]] = {
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
            "❌ The video is too big: Telegram lets bots send up to 50 MB,"
            " and this one is too long to compress that much."
        ),
        "failed": (
            "❌ Couldn't download this video. It may be private or deleted, "
            "or the platform blocked the download."
        ),
        "menu.start": "Start / help",
        "menu.language": "Change language",
        "menu.group.language": "Change the group language (admins)",
        "group_lang_hint": (
            "\n"
            "\n"
            "Admins: /settings — my language here, restart notices and what "
            "to do with link messages."
        ),
        "slow": "⏳ This is taking longer than usual…",
        "timeout": "❌ The download took too long. Please try again later.",
        "blocked_content": "🚫 This post can't be downloaded with this bot.",
        "no_reason": "no reason given",
        "banned_abuse": (
            "🚫 You've been blocked from using this bot.\n"
            "Reason: {reason}\n\n"
            "If you think it's a mistake, write /appeal and why, for example:"
            " <code>/appeal I sent the wrong link</code>"
        ),
        "banned_request": (
            "🚫 At your request, the bot doesn't process your messages.\n"
            "To use it again, send /appeal."
        ),
        "appeal_not_banned": "You're not blocked 🙂",
        "appeal_usage": (
            "Write why you should be unblocked, for example:"
            " <code>/appeal I sent the wrong link</code>"
        ),
        "appeal_sent": (
            "📨 Your appeal was sent to the author. The answer will come here."
        ),
        "appeal_wait": (
            "⏳ You've already appealed. You can send a new appeal 24 hours"
            " after the last one."
        ),
        "appeal_rejected": (
            "❌ Your appeal was rejected. You can try again in 24 hours."
        ),
        "unbanned": "✅ You're unblocked, the bot works for you again.",
        "admin_who": (
            "Whom? Reply to a stored video (requests are known for 7 days)"
            " or give a user id: <code>/ban 123456 reason</code>"
        ),
        "admin_which_post": (
            "Which post? Reply to a stored video with its link in the"
            " caption, or give a link: <code>/block https://... reason</code>"
        ),
        "admin_banned": (
            "🚫 Banned <code>{id}</code> ({kind}). Lift with"
            " <code>/unban {id}</code>"
        ),
        "admin_unbanned": "✅ Unbanned <code>{id}</code>",
        "admin_not_banned": "<code>{id}</code> isn't banned",
        "admin_blocked": (
            "🚫 Blocked <code>{post}</code>, cached copy forgotten"
        ),
        "admin_unblocked": "✅ Unblocked <code>{post}</code>",
        "admin_not_blocked": "<code>{post}</code> isn't blocked",
        "admin_list": (
            "<b>Banned users</b>\n{bans}\n\n<b>Blocked posts</b>\n{blocked}"
        ),
        "admin_appeal": (
            "📨 <b>Appeal</b> from {user} (<code>{id}</code>)\n"
            "Ban reason: {reason}\n\n{text}"
        ),
        "admin_appeal_yes": "\n\n✅ Unbanned",
        "admin_appeal_no": "\n\n❌ Rejected",
        "legal.privacy": (
            "🔒 <b>Privacy</b>\n\n"
            "The bot keeps only what it needs: your Telegram ID (for rare"
            " announcements about the bot) and language if you changed it,"
            " group IDs and settings, and copies of"
            " downloaded videos with their links in a private channel, plus,"
            " for a week, who requested each one, and a list of blocked"
            " users, to stop abuse."
            " Names, phone numbers and message texts are not stored.\n\n"
            "Only the author sees this, and only to run the bot. He gives"
            " his word not to show or pass on to anyone what you downloaded"
            " or that you did, except reports of illegal content to"
            " Telegram. Data is never sold."
        ),
        "legal.terms": (
            "📜 <b>Terms of Use</b>\n\n"
            "The bot is free and provided as is, with no guarantees. You are"
            " responsible for the links you send: only share what you're"
            " allowed to, nothing illegal, no spam. With /cleanup, your"
            " comment next to a link is reposted under the video."
        ),
        "legal.contact": "\nQuestions, data or copy removal: {tg}",
        "menu.group.cleanup": "What to do with link messages (admins)",
        "help": (
            "<b>How to use</b>\n"
            "• Private chat: send me a link, I reply with the video\n"
            "• Any chat: type <code>@{bot} </code>, paste a link and tap "
            "the result\n"
            "• Groups: add me, and I reply to every link with the video\n"
            "\n"
            "<b>Commands</b> (who can use them)\n"
            "/start — welcome message (everyone)\n"
            "/help — this help (everyone)\n"
            "/settings — in private: your settings (everyone); in groups: "
            "language, restart notices and link messages (admins)\n"
            "/language — in private: your language (everyone); in groups: "
            "the group language (admins)\n"
            "/cleanup — what to do with link messages in the group (admins)\n"
            "/privacy, /terms — privacy policy and terms of use (everyone)"
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
        "comment_line": "💬 {text}",
        "profile.short": (
            "TikTok without watermark, YouTube Shorts, Instagram Reels: "
            "inline, in DMs and groups."
        ),
        "profile.full": (
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
        "help.autodelete": (
            "\n"
            "\n"
            "<i>In groups, my service messages and your commands to me "
            "disappear on their own after 15 s – 2 min. Videos stay.</i>"
        ),
        "settings.title": "⚙️ <b>Settings</b>\n\n{kit}",
        "settings.group_title": (
            "⚙️ <b>Group settings</b>\n"
            "\n"
            "{kit}\n"
            "🧹 Link messages: <b>{cleanup}</b>\n"
            "\n"
            "<i>Only group admins can change them.</i>"
        ),
        "btn.cleanup": "🧹 Link messages",
        "menu.group.settings": "Group settings (admins)",
        "menu.bans": "Banned users and blocked posts",
        "help.dev_extra": (
            "\n"
            "/ban, /unban, /block, /unblock, /bans — moderation (here or in "
            "the storage channel)"
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
            "❌ Видео слишком большое: Telegram даёт ботам отправлять до"
            " 50 МБ, а это видео слишком длинное, чтобы так его сжать."
        ),
        "failed": (
            "❌ Не получилось скачать видео. Возможно, оно приватное или "
            "удалено, или платформа заблокировала скачивание."
        ),
        "menu.start": "Старт / помощь",
        "menu.language": "Сменить язык",
        "menu.group.language": "Сменить язык группы (админы)",
        "group_lang_hint": (
            "\n"
            "\n"
            "Админам: /settings — мой язык здесь, уведомления о перезапуске "
            "и что делать с сообщениями-ссылками."
        ),
        "slow": "⏳ Это занимает больше времени, чем обычно…",
        "timeout": (
            "❌ Скачивание заняло слишком много времени. Попробуй позже."
        ),
        "blocked_content": "🚫 Этот пост нельзя скачать через бота.",
        "no_reason": "причина не указана",
        "banned_abuse": (
            "🚫 Тебе закрыт доступ к боту.\n"
            "Причина: {reason}\n\n"
            "Если это ошибка, напиши /appeal и почему, например:"
            " <code>/appeal скинул не ту ссылку</code>"
        ),
        "banned_request": (
            "🚫 По твоей просьбе бот не обрабатывает твои сообщения.\n"
            "Чтобы снова им пользоваться, отправь /appeal."
        ),
        "appeal_not_banned": "Ты не заблокирован 🙂",
        "appeal_usage": (
            "Напиши, почему тебя стоит разблокировать, например:"
            " <code>/appeal скинул не ту ссылку</code>"
        ),
        "appeal_sent": ("📨 Апелляция отправлена автору. Ответ придёт сюда."),
        "appeal_wait": (
            "⏳ Ты уже отправлял апелляцию. Новую можно через 24 часа после"
            " прошлой."
        ),
        "appeal_rejected": (
            "❌ Апелляцию отклонили. Попробовать снова можно через 24 часа."
        ),
        "unbanned": "✅ Ты разблокирован, бот снова работает для тебя.",
        "legal.privacy": (
            "🔒 <b>Конфиденциальность</b>\n\n"
            "Бот хранит только нужное для работы: твой Telegram ID (для"
            " редких объявлений о боте) и язык, если ты его менял,"
            " ID и настройки групп, а также копии"
            " скачанных видео со ссылками в закрытом канале, неделю — кто"
            " запросил каждое, и список заблокированных, чтобы пресекать"
            " злоупотребления. Имена, телефоны"
            " и тексты сообщений не сохраняются.\n\n"
            "Всё это видит только автор и только для работы бота. Он даёт"
            " слово никому не показывать и не передавать, что ты скачивал и"
            " что это был ты, — кроме жалоб на незаконный контент в"
            " Telegram. Данные никому не продаются."
        ),
        "legal.terms": (
            "📜 <b>Правила</b>\n\n"
            "Бот бесплатный и работает «как есть», без гарантий. За ссылки"
            " отвечаешь ты: кидай только то, что можно, ничего незаконного,"
            " без спама. При /cleanup твой комментарий к ссылке публикуется"
            " под видео."
        ),
        "legal.contact": "\nВопросы, удаление данных или копий: {tg}",
        "menu.group.cleanup": "Что делать с сообщениями-ссылками (админы)",
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
            "/settings — в личке: твои настройки (всем); в группе: язык, "
            "уведомления о перезапуске и сообщения-ссылки (админам)\n"
            "/language — в личке: твой язык (всем); в группе: язык группы "
            "(админам)\n"
            "/cleanup — что делать с сообщениями-ссылками в группе (админам)\n"
            "/privacy, /terms — конфиденциальность и правила (всем)"
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
        "comment_line": "💬 {text}",
        "profile.short": (
            "TikTok без вотермарки, YouTube Shorts и Instagram Reels: inline, "
            "в личке и в группах."
        ),
        "profile.full": (
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
        "help.autodelete": (
            "\n"
            "\n"
            "<i>В группах мои служебные сообщения и ваши команды мне "
            "исчезают сами через 15 сек – 2 мин. Видео остаются.</i>"
        ),
        "settings.title": "⚙️ <b>Настройки</b>\n\n{kit}",
        "settings.group_title": (
            "⚙️ <b>Настройки группы</b>\n"
            "\n"
            "{kit}\n"
            "🧹 Сообщения-ссылки: <b>{cleanup}</b>\n"
            "\n"
            "<i>Менять могут только админы группы.</i>"
        ),
        "btn.cleanup": "🧹 Сообщения-ссылки",
        "menu.group.settings": "Настройки группы (админы)",
        "menu.bans": "Баны и заблокированные посты",
        "help.dev_extra": (
            "\n"
            "/ban, /unban, /block, /unblock, /bans — модерация (здесь или в "
            "канале-хранилище)"
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
            "❌ Video on liiga suur: Telegram lubab bottidel saata kuni"
            " 50 MB ja see video on nii palju kokkupakkimiseks liiga pikk."
        ),
        "failed": (
            "❌ Videot ei õnnestunud alla laadida. See võib olla privaatne "
            "või kustutatud või blokeeris platvorm allalaadimise."
        ),
        "menu.start": "Alusta / abi",
        "menu.language": "Muuda keelt",
        "menu.group.language": "Muuda grupi keelt (adminid)",
        "group_lang_hint": (
            "\n"
            "\n"
            "Adminidele: /settings — minu keel siin, taaskäivituse teated "
            "ja mida teha linkidega sõnumitega."
        ),
        "slow": "⏳ See võtab tavapärasest kauem aega…",
        "timeout": (
            "❌ Allalaadimine võttis liiga kaua aega. Proovi hiljem uuesti."
        ),
        "blocked_content": (
            "🚫 Seda postitust ei saa selle botiga alla laadida."
        ),
        "no_reason": "põhjust pole märgitud",
        "banned_abuse": (
            "🚫 Sinu ligipääs botile on suletud.\n"
            "Põhjus: {reason}\n\n"
            "Kui see on viga, kirjuta /appeal ja miks, näiteks:"
            " <code>/appeal saatsin vale lingi</code>"
        ),
        "banned_request": (
            "🚫 Sinu palvel bot sinu sõnumeid ei töötle.\n"
            "Et seda uuesti kasutada, saada /appeal."
        ),
        "appeal_not_banned": "Sa ei ole blokeeritud 🙂",
        "appeal_usage": (
            "Kirjuta, miks sind tuleks blokeeringust vabastada, näiteks:"
            " <code>/appeal saatsin vale lingi</code>"
        ),
        "appeal_sent": (
            "📨 Apellatsioon saadeti autorile. Vastus tuleb siia."
        ),
        "appeal_wait": (
            "⏳ Sa juba saatsid apellatsiooni. Uue saad saata 24 tundi pärast"
            " eelmist."
        ),
        "appeal_rejected": (
            "❌ Apellatsioon lükati tagasi. Uuesti saad proovida 24 tunni"
            " pärast."
        ),
        "unbanned": (
            "✅ Blokeering on eemaldatud, bot töötab sinu jaoks jälle."
        ),
        "legal.privacy": (
            "🔒 <b>Privaatsus</b>\n\n"
            "Bot hoiab ainult vajalikku: sinu Telegrami ID (harvade"
            " teadaannete jaoks boti kohta) ja keele, kui seda muutsid,"
            " gruppide ID-d ja seaded ning allalaaditud"
            " videote koopiad koos linkidega privaatses kanalis, nädal aega"
            " ka seda, kes iga video küsis, ning blokeeritud kasutajate"
            " nimekirja, et kuritarvitust peatada. Nimesid,"
            " telefoninumbreid ja sõnumite teksti ei salvestata.\n\n"
            "Seda näeb ainult autor ja ainult boti tööks. Ta annab sõna, et"
            " ei näita ega anna kellelegi edasi, mida sa alla laadisid ega"
            " et see olid sina, välja arvatud teated ebaseaduslikust"
            " sisust Telegramile. Andmeid ei müüda."
        ),
        "legal.terms": (
            "📜 <b>Kasutustingimused</b>\n\n"
            "Bot on tasuta ja töötab „nagu on“, ilma garantiideta. Saadetud"
            " linkide eest vastutad sina: jaga ainult lubatut, mitte midagi"
            " ebaseaduslikku, mitte rämpsposti. /cleanup puhul avaldatakse"
            " sinu kommentaar video all."
        ),
        "legal.contact": "\nKüsimused, andmete või koopiate kustutamine: {tg}",
        "menu.group.cleanup": "Mida teha linkidega sõnumitega (adminid)",
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
            "/settings — privaatselt: sinu seaded (kõik); grupis: keel, "
            "taaskäivituse teated ja linkidega sõnumid (adminid)\n"
            "/language — privaatselt: sinu keel (kõik); grupis: grupi keel "
            "(adminid)\n"
            "/cleanup — mida teha linkidega sõnumitega grupis (adminid)\n"
            "/privacy, /terms — privaatsus ja kasutustingimused (kõik)"
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
        "comment_line": "💬 {text}",
        "profile.short": (
            "TikTok ilma vesimärgita, YouTube Shorts, Instagram Reels: "
            "inline, privaatselt ja grupis."
        ),
        "profile.full": (
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
        "help.autodelete": (
            "\n"
            "\n"
            "<i>Gruppides kaovad minu teenusesõnumid ja teie käsud mulle "
            "ise 15 s – 2 min pärast. Videod jäävad.</i>"
        ),
        "settings.title": "⚙️ <b>Seaded</b>\n\n{kit}",
        "settings.group_title": (
            "⚙️ <b>Grupi seaded</b>\n"
            "\n"
            "{kit}\n"
            "🧹 Linkidega sõnumid: <b>{cleanup}</b>\n"
            "\n"
            "<i>Muuta saavad ainult grupi adminid.</i>"
        ),
        "btn.cleanup": "🧹 Linkidega sõnumid",
        "menu.group.settings": "Grupi seaded (adminid)",
        "menu.bans": "Blokeeritud kasutajad ja postitused",
        "help.dev_extra": (
            "\n"
            "/ban, /unban, /block, /unblock, /bans — modereerimine (siin "
            "või salvestuskanalis)"
        ),
    },
}


i18n.register(TEXTS, LANGS, default=DEFAULT_LANG)

__all__ = ["DEFAULT_LANG", "LANGS", "TEXTS", "normalize", "t"]
