"""Texts of the shared parts: language, legal, broadcast, status.

A bot can override any of them by defining the same key in its own
texts (for example, a status message that names what the bot does).
Every language here has the same keys; a bot uses only the languages
it supports.
"""

KIT_TEXTS: dict[str, dict[str, str]] = {
    # ═════════════════════════════ ENGLISH ════════════════════════════
    "en": {
        "lang.choose": "🌐 Choose a language:",
        "lang.choose_group": "🌐 Choose the language of this group:",
        "lang.set": "✅ Language: English",
        "err.admins_only": "Only group admins can change this.",
        "err.expired": "These buttons have expired — start over.",
        # ── legal ──
        "legal.terms_name": "Terms of Use",
        "legal.privacy_name": "Privacy Policy",
        "legal.links": "\n\n📄 {links}",
        "legal.read": '\n\nFull text: <a href="{url}">{name}</a>',
        "legal.contact": "\nQuestions and data removal: {tg}",
        # ── author ──
        "author.line": "\n\n👤 Author: {contacts}",
        "author.repo": "\n🧩 Open source: {repo}",
        "author.error": " If it keeps happening, message {tg}.",
        # ── settings ──
        "settings.language": "🌐 Language: <b>{name}</b>",
        "settings.notices": "🔔 Restart notices: <b>{state}</b>",
        "settings.on": "on",
        "settings.off": "off",
        "btn.language": "🌐 Language",
        "btn.notices_on": "🔔 Notices: on",
        "btn.notices_off": "🔕 Notices: off",
        "btn.back": "← Back",
        "notices.set_on": "🔔 Restart notices are on",
        "notices.set_off": "🔕 Restart notices are off",
        # ── status ──
        "status.online": "🟢 Online",
        "status.offline": "🔴 Offline",
        "status.notice_offline": "🌙 {bot} is off for now — back later.",
        "status.notice_reload": "🔄 {bot} is restarting — back in a minute.",
        "status.notice_back": "🟢 {bot} is back online.",
        "profile.by": "by {tg}",
        "profile.privacy": "\n🔒 Privacy: {url}",
        # ── developer ──
        "dev.reloading": "🔄 Restarting with the latest code…",
        "dev.stopping": "🌙 Shutting down.",
        "dev.quiet": " Chats won't be notified.",
        "dev.back": "✅ Back online.",
        "help.dev": (
            "\n\n<b>Developer</b>\n"
            "/broadcast — announcement to all chats\n"
            "/reload — restart with the latest code\n"
            "/stop — shut down\n"
            "<i>Add quiet to skip the notices in chats: /reload quiet</i>\n"
            "/id — chat and user ID"
        ),
        # ── broadcast ──
        "broadcast.panel": (
            "📢 <b>Broadcast</b>\n\n{mode}\n{target}\n\n"
            "↩️ <b>Reply to this message</b> with the announcement: text, "
            "a photo with a caption, anything (one message, not an "
            "album).\nHTML that starts with <code>&lt;</code> goes out as a "
            "rich message: tables, lists, headings."
        ),
        "broadcast.mode_loud": "🔔 With a notification",
        "broadcast.mode_silent": "🔕 Silently",
        "broadcast.to_all": "👥 To: all chats ({n})",
        "broadcast.to_lang": "👥 To: chats in {lang} ({n})",
        "broadcast.btn_loud": "🔔 Sound",
        "broadcast.btn_silent": "🔕 Silent",
        "broadcast.btn_all": "👥 All",
        "broadcast.btn_close": "✖️ Close",
        "broadcast.closed": "📢 Broadcast panel closed.",
        "broadcast.confirm": "{mode}\n{target}\n\nSend the message above?",
        "broadcast.go": "✅ Send to {n} chats",
        "broadcast.cancel": "✖️ Cancel",
        "broadcast.cancelled": "Broadcast cancelled.",
        "broadcast.started": "📤 Sending…",
        "broadcast.done": (
            "✅ Broadcast done\n"
            "Delivered: {sent}\n"
            "Failed: {failed}\n"
            "Unreachable, removed from the list: {gone}"
        ),
        "broadcast.rich_failed": (
            "⚠️ Telegram didn't accept this as a rich message ({error}). It "
            "will go out as an ordinary message, like the preview above."
        ),
        # ── command menu ──
        "menu.help": "Help and commands",
        "menu.language": "Language",
        "menu.settings": "Settings",
        "menu.privacy": "Privacy and terms",
        "menu.id": "Chat and user ID",
        "menu.broadcast": "Announcement to all chats",
        "menu.reload": "Restart with the latest code",
        "menu.stop": "Shut down",
    },
    # ═════════════════════════════ RUSSIAN ════════════════════════════
    "ru": {
        "lang.choose": "🌐 Выбери язык:",
        "lang.choose_group": "🌐 Выберите язык этой группы:",
        "lang.set": "✅ Язык: русский",
        "err.admins_only": "Это могут менять только админы группы.",
        "err.expired": "Кнопки устарели — начни заново.",
        "legal.terms_name": "Правила",
        "legal.privacy_name": "Конфиденциальность",
        "legal.links": "\n\n📄 {links}",
        "legal.read": (
            '\n\nПолный текст (на английском): <a href="{url}">{name}</a>'
        ),
        "legal.contact": "\nВопросы и удаление данных: {tg}",
        "author.line": "\n\n👤 Автор: {contacts}",
        "author.repo": "\n🧩 Исходный код: {repo}",
        "author.error": " Если повторяется — напиши {tg}.",
        "settings.language": "🌐 Язык: <b>{name}</b>",
        "settings.notices": "🔔 Уведомления о перезапуске: <b>{state}</b>",
        "settings.on": "вкл",
        "settings.off": "выкл",
        "btn.language": "🌐 Язык",
        "btn.notices_on": "🔔 Уведомления: вкл",
        "btn.notices_off": "🔕 Уведомления: выкл",
        "btn.back": "← Назад",
        "notices.set_on": "🔔 Уведомления о перезапуске включены",
        "notices.set_off": "🔕 Уведомления о перезапуске выключены",
        "status.online": "🟢 Онлайн",
        "status.offline": "🔴 Офлайн",
        "status.notice_offline": "🌙 {bot} пока выключен — вернётся позже.",
        "status.notice_reload": (
            "🔄 {bot} перезапускается — вернётся через минуту."
        ),
        "status.notice_back": "🟢 {bot} снова в работе.",
        "profile.by": "автор {tg}",
        "profile.privacy": "\n🔒 Privacy: {url}",
        "dev.reloading": "🔄 Перезапускаюсь с новым кодом…",
        "dev.stopping": "🌙 Выключаюсь.",
        "dev.quiet": " Чатам ничего не пишу.",
        "dev.back": "✅ Снова на связи.",
        "help.dev": (
            "\n\n<b>Разработчик</b>\n"
            "/broadcast — объявление всем чатам\n"
            "/reload — перезапуск с новым кодом\n"
            "/stop — выключить\n"
            "<i>Добавь quiet, чтобы не писать в чаты: /reload quiet</i>\n"
            "/id — id чата и пользователя"
        ),
        "broadcast.panel": (
            "📢 <b>Рассылка</b>\n\n{mode}\n{target}\n\n"
            "↩️ <b>Ответь на это сообщение</b> объявлением: текст, фото с "
            "подписью, что угодно (одно сообщение, не альбом).\n"
            "HTML, который начинается с <code>&lt;</code>, уйдёт "
            "rich-сообщением: таблицы, списки, заголовки."
        ),
        "broadcast.mode_loud": "🔔 С уведомлением",
        "broadcast.mode_silent": "🔕 Без звука",
        "broadcast.to_all": "👥 Кому: все чаты ({n})",
        "broadcast.to_lang": "👥 Кому: чаты на языке {lang} ({n})",
        "broadcast.btn_loud": "🔔 Со звуком",
        "broadcast.btn_silent": "🔕 Без звука",
        "broadcast.btn_all": "👥 Все",
        "broadcast.btn_close": "✖️ Закрыть",
        "broadcast.closed": "📢 Панель рассылки закрыта.",
        "broadcast.confirm": "{mode}\n{target}\n\nОтправить сообщение выше?",
        "broadcast.go": "✅ Отправить в {n} чатов",
        "broadcast.cancel": "✖️ Отмена",
        "broadcast.cancelled": "Рассылка отменена.",
        "broadcast.started": "📤 Рассылаю…",
        "broadcast.done": (
            "✅ Рассылка готова\n"
            "Доставлено: {sent}\n"
            "Не удалось: {failed}\n"
            "Недоступны, убраны из списка: {gone}"
        ),
        "broadcast.rich_failed": (
            "⚠️ Telegram не принял это как rich-сообщение ({error}). Уйдёт "
            "обычным сообщением, как в превью выше."
        ),
        "menu.help": "Помощь и команды",
        "menu.language": "Язык",
        "menu.settings": "Настройки",
        "menu.privacy": "Конфиденциальность и правила",
        "menu.id": "ID чата и пользователя",
        "menu.broadcast": "Объявление всем чатам",
        "menu.reload": "Перезапуск с новым кодом",
        "menu.stop": "Выключить",
    },
    # ════════════════════════════ ESTONIAN ════════════════════════════
    "et": {
        "lang.choose": "🌐 Vali keel:",
        "lang.choose_group": "🌐 Vali selle grupi keel:",
        "lang.set": "✅ Keel: eesti",
        "err.admins_only": "Seda saavad muuta ainult grupi adminid.",
        "err.expired": "Need nupud on aegunud — alusta uuesti.",
        "legal.terms_name": "Kasutustingimused",
        "legal.privacy_name": "Privaatsuspoliitika",
        "legal.links": "\n\n📄 {links}",
        "legal.read": (
            '\n\nTäistekst (inglise keeles): <a href="{url}">{name}</a>'
        ),
        "legal.contact": "\nKüsimused ja andmete kustutamine: {tg}",
        "author.line": "\n\n👤 Autor: {contacts}",
        "author.repo": "\n🧩 Lähtekood: {repo}",
        "author.error": " Kui see kordub, kirjuta {tg}.",
        "settings.language": "🌐 Keel: <b>{name}</b>",
        "settings.notices": "🔔 Taaskäivituse teated: <b>{state}</b>",
        "settings.on": "sees",
        "settings.off": "väljas",
        "btn.language": "🌐 Keel",
        "btn.notices_on": "🔔 Teated: sees",
        "btn.notices_off": "🔕 Teated: väljas",
        "btn.back": "← Tagasi",
        "notices.set_on": "🔔 Taaskäivituse teated on sees",
        "notices.set_off": "🔕 Taaskäivituse teated on väljas",
        "status.online": "🟢 Töötab",
        "status.offline": "🔴 Väljas",
        "status.notice_offline": (
            "🌙 {bot} on praegu väljas, tuleb hiljem tagasi."
        ),
        "status.notice_reload": "🔄 {bot} taaskäivitub, on kohe tagasi.",
        "status.notice_back": "🟢 {bot} töötab jälle.",
        "profile.by": "autor {tg}",
        "profile.privacy": "\n🔒 Privacy: {url}",
        "dev.reloading": "🔄 Taaskäivitun uue koodiga…",
        "dev.stopping": "🌙 Lülitun välja.",
        "dev.quiet": " Vestlustele ei kirjuta.",
        "dev.back": "✅ Olen tagasi.",
        "help.dev": (
            "\n\n<b>Arendaja</b>\n"
            "/broadcast — teadaanne kõigile vestlustele\n"
            "/reload — taaskäivitus uue koodiga\n"
            "/stop — lülita välja\n"
            "<i>Lisa quiet, et vestlustele mitte teatada: /reload quiet</i>\n"
            "/id — vestluse ja kasutaja ID"
        ),
        "broadcast.panel": (
            "📢 <b>Teadaanne</b>\n\n{mode}\n{target}\n\n"
            "↩️ <b>Vasta sellele sõnumile</b> teadaandega: tekst, pilt "
            "allkirjaga, mis iganes (üks sõnum, mitte album).\n"
            "HTML, mis algab märgiga <code>&lt;</code>, läheb rich-sõnumina: "
            "tabelid, loendid, pealkirjad."
        ),
        "broadcast.mode_loud": "🔔 Teavitusega",
        "broadcast.mode_silent": "🔕 Vaikselt",
        "broadcast.to_all": "👥 Kellele: kõik vestlused ({n})",
        "broadcast.to_lang": "👥 Kellele: vestlused keeles {lang} ({n})",
        "broadcast.btn_loud": "🔔 Heliga",
        "broadcast.btn_silent": "🔕 Vaikselt",
        "broadcast.btn_all": "👥 Kõik",
        "broadcast.btn_close": "✖️ Sulge",
        "broadcast.closed": "📢 Teadaande paneel on suletud.",
        "broadcast.confirm": "{mode}\n{target}\n\nKas saata ülalolev sõnum?",
        "broadcast.go": "✅ Saada {n} vestlusesse",
        "broadcast.cancel": "✖️ Tühista",
        "broadcast.cancelled": "Saatmine tühistatud.",
        "broadcast.started": "📤 Saadan…",
        "broadcast.done": (
            "✅ Teadaanne saadetud\n"
            "Kohale jõudis: {sent}\n"
            "Ebaõnnestus: {failed}\n"
            "Kättesaamatud, nimekirjast eemaldatud: {gone}"
        ),
        "broadcast.rich_failed": (
            "⚠️ Telegram ei võtnud seda rich-sõnumina vastu ({error}). See "
            "läheb tavalise sõnumina, nagu ülal eelvaates."
        ),
        "menu.help": "Abi ja käsud",
        "menu.language": "Keel",
        "menu.settings": "Seaded",
        "menu.privacy": "Privaatsus ja tingimused",
        "menu.id": "Vestluse ja kasutaja ID",
        "menu.broadcast": "Teadaanne kõigile vestlustele",
        "menu.reload": "Taaskäivitus uue koodiga",
        "menu.stop": "Lülita välja",
    },
}

# Names on the language buttons.
KIT_LANG_NAMES = {
    "en": "🇬🇧 English",
    "ru": "🇷🇺 Русский",
    "et": "🇪🇪 Eesti",
}
