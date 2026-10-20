"""Test botkit: storage, languages, safe sending, broadcast, notices.

The same file is in both bots. Telegram is replaced by FakeSession,
which records every request and answers like Telegram would.

Run: python -m pytest tests/test_botkit.py
"""

import asyncio
import contextlib
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from aiogram import Bot, Dispatcher  # noqa: E402
from aiogram.client.session.base import BaseSession  # noqa: E402
from aiogram.exceptions import (  # noqa: E402
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramMigrateToChat,
    TelegramRetryAfter,
)
from aiogram.methods import (  # noqa: E402
    CopyMessage,
    DeleteMessage,
    EditMessageText,
    GetChatMember,
    GetMe,
    SendMessage,
    SendRichMessage,
    SetMyCommands,
    SetMyDescription,
    SetMyShortDescription,
)
from aiogram.types import Message, Update  # noqa: E402

from botkit import (  # noqa: E402
    BotKit,
    KitConfig,
    KitStore,
    Tally,
    fit,
    i18n,
    utf16_len,
)
from botkit.texts import KIT_TEXTS  # noqa: E402

DEV = 111
USER = 222
GROUP = -1001234567890


@contextlib.contextmanager
def texts(bot_texts=None, langs=("en", "ru"), default="en"):
    """Register test texts, then put the bot's own texts back."""
    saved = (
        {k: dict(v) for k, v in i18n.TEXTS.items()},
        i18n.LANGS,
        i18n.DEFAULT_LANG,
    )
    base = {"profile.short": "Short", "profile.full": "Full @{bot}"}
    merged = {
        lang: {**base, **(bot_texts or {}).get(lang, {})} for lang in langs
    }
    i18n.register(merged, langs, default)
    try:
        yield
    finally:
        i18n.TEXTS.clear()
        i18n.TEXTS.update(saved[0])
        i18n.LANGS, i18n.DEFAULT_LANG = saved[1], saved[2]


class FakeSession(BaseSession):
    """A Telegram that records requests and can fail on purpose."""

    def __init__(self):
        """Start with no requests and no failures."""
        super().__init__()
        self.calls = []
        self.fail = {}  # chat_id -> list of exception factories
        self.admins = set()
        self.next_id = 100

    async def close(self):
        """Nothing to close."""

    async def stream_content(self, *args, **kwargs):
        """Not used."""
        raise NotImplementedError

    def message(self, bot, chat_id, text="x"):
        """Build a message as Telegram would return it."""
        self.next_id += 1
        kind = "private" if chat_id > 0 else "supergroup"
        return Message.model_validate(
            {
                "message_id": self.next_id,
                "date": int(time.time()),
                "chat": {"id": chat_id, "type": kind},
                "text": text,
            },
            context={"bot": bot},
        )

    async def make_request(self, bot, method, timeout=None):
        """Record the request and answer it."""
        self.calls.append(method)
        chat_id = getattr(method, "chat_id", None)
        if self.fail.get(chat_id):
            raise self.fail[chat_id].pop(0)(method)
        if isinstance(method, GetMe):
            from aiogram.types import User

            return User(
                id=999, is_bot=True, first_name="Bot", username="test_bot"
            )
        if isinstance(method, GetChatMember):
            from aiogram.types import (
                ChatMemberAdministrator,
                ChatMemberMember,
                User,
            )

            user = User(id=method.user_id, is_bot=False, first_name="U")
            if method.user_id in self.admins:
                return ChatMemberAdministrator.model_construct(
                    status="administrator", user=user
                )
            return ChatMemberMember(user=user)
        if isinstance(method, (SendMessage, SendRichMessage)):
            return self.message(bot, chat_id, getattr(method, "text", "r"))
        if isinstance(method, CopyMessage):
            from aiogram.types import MessageId

            self.next_id += 1
            return MessageId(message_id=self.next_id)
        if isinstance(method, EditMessageText):
            return self.message(bot, chat_id or 1, method.text or "")
        return True

    def of(self, kind):
        """Return the recorded requests of one kind."""
        return [c for c in self.calls if isinstance(c, kind)]


def make_kit(tmp_path, **kwargs):
    """Return a kit on a fresh database."""
    cfg = KitConfig(
        bot_token="1:x",
        bot_name="TestBot",
        dev_ids=(DEV,),
        default_lang="en",
        author_telegram="author",
        author_github="author",
        repo_url="",
        privacy_url="https://example.com/privacy",
        terms_url="https://example.com/terms",
        auto_delete=True,
    )
    store = KitStore(tmp_path / "bot.db")
    return BotKit(cfg, store, menu=["help", "language", "privacy"], **kwargs)


async def started(kit):
    """Return a bot, a dispatcher and the session, set up like serve."""
    session = FakeSession()
    bot = Bot("1:x", session=session)
    dp = Dispatcher()
    await kit.setup(bot, dp)
    session.calls.clear()
    return bot, dp, session


_update_id = [0]


async def send(bot, dp, chat_id, user_id, text, reply_to=None, lang="en"):
    """Feed a text message to the dispatcher."""
    _update_id[0] += 1
    message = {
        "message_id": 5000 + _update_id[0],
        "date": int(datetime.now().timestamp()),
        "chat": {
            "id": chat_id,
            "type": "private" if chat_id > 0 else "supergroup",
        },
        "from": {
            "id": user_id,
            "is_bot": False,
            "first_name": "U",
            "language_code": lang,
        },
        "text": text,
    }
    if text.startswith("/"):
        cmd = text.split()[0]
        message["entities"] = [
            {"type": "bot_command", "offset": 0, "length": len(cmd)}
        ]
    if reply_to is not None:
        message["reply_to_message"] = {
            "message_id": reply_to,
            "date": int(datetime.now().timestamp()),
            "chat": message["chat"],
            "text": "panel",
        }
    update = Update.model_validate(
        {"update_id": _update_id[0], "message": message},
        context={"bot": bot},
    )
    await dp.feed_update(bot, update)
    return message["message_id"]


async def press(bot, dp, chat_id, user_id, message_id, data):
    """Feed a button press to the dispatcher."""
    _update_id[0] += 1
    update = Update.model_validate(
        {
            "update_id": _update_id[0],
            "callback_query": {
                "id": str(_update_id[0]),
                "from": {"id": user_id, "is_bot": False, "first_name": "U"},
                "chat_instance": "c",
                "data": data,
                "message": {
                    "message_id": message_id,
                    "date": int(datetime.now().timestamp()),
                    "chat": {
                        "id": chat_id,
                        "type": "private" if chat_id > 0 else "supergroup",
                    },
                    "text": "x",
                },
            },
        },
        context={"bot": bot},
    )
    await dp.feed_update(bot, update)


def error(kind, text="", **extra):
    """Return a factory of a Telegram error for FakeSession.fail."""

    def make(method):
        if kind is TelegramMigrateToChat:
            return kind(method, text, migrate_to_chat_id=extra["to"])
        if kind is TelegramRetryAfter:
            return kind(method, text, retry_after=0)
        return kind(method, text)

    return make


# ═══════════════════════════════ TEXTS ═══════════════════════════════
def test_kit_texts_complete():
    """Every language has the same keys and placeholders."""
    for lang, table in KIT_TEXTS.items():
        assert set(table) == set(KIT_TEXTS["en"]), lang
        for key, text in KIT_TEXTS["en"].items():
            want = set(re.findall(r"{(\w+)}", text))
            assert set(re.findall(r"{(\w+)}", table[key])) == want, key


def test_t_fallbacks():
    """The bot's text wins; missing ones fall back, never fail."""
    with texts({"en": {"lang.set": "mine"}, "ru": {}}):
        assert i18n.t("en", "lang.set") == "mine"
        assert i18n.t("ru", "lang.set") == KIT_TEXTS["ru"]["lang.set"]
        assert i18n.t("xx", "lang.set") == "mine"
        assert i18n.t("en", "no.such.key") == "no.such.key"
        assert i18n.normalize("ru-RU") == "ru"
        assert i18n.normalize("de") == "en"
        assert i18n.supported("de") is None


def test_fit_counts_utf16():
    """Emoji take two units, and the cut adds an ellipsis."""
    assert utf16_len("🟢") == 2
    text = "🟢" * 100
    out = fit(text, 120)
    assert utf16_len(out) <= 120 and out.endswith("…")
    assert fit("short", 120) == "short"


# ══════════════════════════════ STORAGE ══════════════════════════════
def test_move_chat_moves_settings(tmp_path):
    """A supergroup gets the group's row and per-chat settings."""
    store = KitStore(tmp_path / "bot.db")
    store.update_chat(-5, lang="ru", notices=0)
    store.set_setting("toxic:-5", "max")
    store.set_setting("toxic:-55", "keep")
    store.see_chat(GROUP, "supergroup", "en")
    assert store.move_chat(-5, GROUP)
    row = store.chat(GROUP)
    assert row["lang"] == "ru" and row["notices"] == 0 and row["hint"] == "en"
    assert store.chat(-5) is None
    assert store.get_setting(f"toxic:{GROUP}") == "max"
    assert store.get_setting("toxic:-55") == "keep"
    assert not store.move_chat(-5, GROUP)  # the second message


def test_settings_prefix_is_literal(tmp_path):
    """Treat "_" and "%" in a prefix literally, not as wildcards."""
    store = KitStore(tmp_path / "bot.db")
    store.set_setting("a_b:1", "x")
    store.set_setting("axb:1", "y")
    assert store.settings_with_prefix("a_b:") == [("a_b:1", "x")]


def test_see_chat_keeps_group_hint(tmp_path):
    """A group keeps the first language; a private chat follows."""
    store = KitStore(tmp_path / "bot.db")
    store.see_chat(GROUP, "supergroup", "ru")
    store.see_chat(GROUP, "supergroup", "en")
    assert store.chat(GROUP)["hint"] == "ru"
    store.see_chat(USER, "private", "ru")
    store.see_chat(USER, "private", "en")
    assert store.chat(USER)["hint"] == "en"
    store.update_chat(USER, active=0)
    store.see_chat(USER, "private", None)
    assert store.chat(USER)["active"] == 1


# ═════════════════════════════ LANGUAGE ══════════════════════════════
def test_lang_of(tmp_path):
    """Chosen beats the app language, which beats the hint."""
    from aiogram.types import User

    with texts():
        kit = make_kit(tmp_path)
        user = User(id=USER, is_bot=False, first_name="U", language_code="ru")
        assert kit.lang_of(USER, user) == "ru"
        assert kit.lang_of(None, user) == "ru"
        assert kit.lang_of(USER) == "en"  # unknown chat, no user
        kit.store.see_chat(GROUP, "supergroup", "ru")
        assert kit.lang_of(GROUP, user) == "ru"
        kit.set_lang(GROUP, "en")
        assert kit.lang_of(GROUP) == "en"


# ══════════════════════════ SAFE SENDING ═════════════════════════════
def test_deliver_handles_dead_and_moved_chats(tmp_path):
    """Blocked chats are marked, moved groups get it at the new ID."""

    async def run():
        kit = make_kit(tmp_path)
        bot, _dp, session = await started(kit)
        kit.store.see_chat(USER, "private", "en")
        kit.store.see_chat(-5, "group", "en")
        session.fail[USER] = [error(TelegramForbiddenError, "blocked")]
        session.fail[-5] = [error(TelegramMigrateToChat, "moved", to=GROUP)]
        session.fail[-7] = [
            error(TelegramRetryAfter, "flood"),
            error(TelegramBadRequest, "Bad Request: chat not found"),
        ]
        tally = Tally()
        for chat_id in (USER, -5, -7):
            await kit.deliver(
                bot, chat_id, lambda c: bot.send_message(c, "hi"), tally
            )
        assert (tally.sent, tally.failed, tally.gone) == (1, 0, 2)
        assert kit.store.chat(USER)["active"] == 0
        assert kit.store.chat(-5) is None and kit.store.chat(GROUP)
        assert GROUP in [m.chat_id for m in session.of(SendMessage)]

    with texts():
        asyncio.run(run())


def test_groups_get_silent_messages(tmp_path):
    """Messages to groups are silent unless the caller decides."""

    async def run():
        kit = make_kit(tmp_path)
        bot, _dp, session = await started(kit)
        await bot.send_message(GROUP, "a")
        await bot.send_message(USER, "b")
        await bot.send_message(GROUP, "c", disable_notification=False)
        flags = [m.disable_notification for m in session.of(SendMessage)]
        assert flags == [True, None, False]

    with texts():
        asyncio.run(run())


# ════════════════════════════ COMMANDS ═══════════════════════════════
def test_language_in_group_needs_admin(tmp_path):
    """A member can't change the group language; an admin can."""

    async def run():
        kit = make_kit(tmp_path)
        bot, dp, session = await started(kit)
        await send(bot, dp, GROUP, USER, "/language")
        assert "admins" in session.of(SendMessage)[-1].text
        await press(bot, dp, GROUP, USER, 1, "lang:ru")
        assert kit.store.chat(GROUP)["lang"] is None
        session.admins.add(USER)
        await press(bot, dp, GROUP, USER, 1, "lang:ru")
        assert kit.store.chat(GROUP)["lang"] == "ru"
        # Commands in groups are queued for deletion.
        assert kit.store.due_deletions(int(time.time()) + 999)

    with texts():
        asyncio.run(run())


def test_dev_commands_are_invisible(tmp_path):
    """Others' /broadcast and /stop reach the bot's own handlers."""

    async def run():
        kit = make_kit(tmp_path)
        bot, dp, session = await started(kit)
        seen = []
        from aiogram import Router

        router = Router()

        @router.message()
        async def fallback(message: Message):
            seen.append(message.text)

        dp.include_router(router)
        await send(bot, dp, USER, USER, "/broadcast")
        await send(bot, dp, USER, USER, "/stop")
        assert seen == ["/broadcast", "/stop"]
        assert kit._stop is None

    with texts():
        asyncio.run(run())


def test_broadcast_only_on_reply(tmp_path):
    """The panel sets sound and language; only a reply is sent."""

    async def run():
        kit = make_kit(tmp_path)
        bot, dp, session = await started(kit)
        for chat_id, lang in ((USER, "en"), (333, "ru"), (GROUP, "ru")):
            kit.store.see_chat(chat_id, chat_id > 0 and "private" or "group")
            kit.set_lang(chat_id, lang)
        await send(bot, dp, DEV, DEV, "/broadcast")
        panel = session.of(SendMessage)[-1]
        panel_id = session.next_id
        assert "3" in panel.text  # all chats except the developer
        await press(bot, dp, DEV, DEV, panel_id, "bc:set:silent")
        await press(bot, dp, DEV, DEV, panel_id, "bc:set:ru")
        # A message that isn't a reply is not an announcement.
        await send(bot, dp, DEV, DEV, "hello everyone")
        assert not any(
            "bc:go" in str(m.reply_markup) for m in session.of(SendMessage)
        )
        news = await send(bot, dp, DEV, DEV, "news", reply_to=panel_id)
        confirm = session.of(SendMessage)[-1]
        go = confirm.reply_markup.inline_keyboard[0][0]
        assert go.callback_data == f"bc:go:{DEV}_{news}"
        assert "2" in go.text  # the two Russian chats
        await press(bot, dp, DEV, DEV, session.next_id, go.callback_data)
        for _ in range(50):
            await asyncio.sleep(0.01)
            if len(session.of(CopyMessage)) == 2:
                break
        copies = session.of(CopyMessage)
        assert sorted(c.chat_id for c in copies) == sorted([333, GROUP])
        assert all(c.disable_notification is True for c in copies)
        await asyncio.sleep(0.1)
        done = session.of(EditMessageText)[-1].text
        assert "2" in done
        # A second tap can't send it twice.
        await press(bot, dp, DEV, DEV, session.next_id, go.callback_data)
        await asyncio.sleep(0.05)
        assert len(session.of(CopyMessage)) == 2

    with texts():
        asyncio.run(run())


def test_broadcast_rich(tmp_path):
    """HTML that starts with "<" goes out as a rich message."""

    async def run():
        kit = make_kit(tmp_path)
        bot, dp, session = await started(kit)
        kit.store.see_chat(USER, "private", "en")
        await send(bot, dp, DEV, DEV, "/broadcast silent")
        panel_id = session.next_id
        await send(
            bot, dp, DEV, DEV, "<h2>Patch</h2><p>notes</p>", reply_to=panel_id
        )
        assert session.of(SendRichMessage)  # the preview
        go = session.of(SendMessage)[-1].reply_markup.inline_keyboard[0][0]
        await press(bot, dp, DEV, DEV, session.next_id, go.callback_data)
        await asyncio.sleep(0.2)
        sent = [m for m in session.of(SendRichMessage) if m.chat_id == USER]
        assert sent and sent[0].disable_notification is True

    with texts():
        asyncio.run(run())


def test_reload_command(tmp_path):
    """/reload asks to stop and greets the developer afterwards."""

    async def run():
        kit = make_kit(tmp_path)
        bot, dp, session = await started(kit)
        await send(bot, dp, DEV, DEV, "/reload quiet")
        assert kit._stop["mode"] == "reload" and kit._stop["quiet"]
        assert kit._stop["update_id"] == _update_id[0]
        assert kit.store.get_setting("kit:reload_chat") == str(DEV)
        await kit._greet_after_reload(bot)
        assert session.of(SendMessage)[-1].chat_id == DEV

    with texts():
        asyncio.run(run())


# ═════════════════════ PROFILE, MENUS, NOTICES ═══════════════════════
def test_profile_fits_and_is_cached(tmp_path):
    """Long texts are cut to Telegram's limits; nothing is resent."""

    async def run():
        bot_texts = {
            "en": {"profile.short": "s" * 200, "profile.full": "f" * 900},
            "ru": {"profile.short": "к" * 200, "profile.full": "п" * 900},
        }
        with texts(bot_texts):
            kit = make_kit(tmp_path)
            bot, _dp, session = await started(kit)
            await kit.set_profile_status(bot, online=False)
            shorts = session.of(SetMyShortDescription)
            fulls = session.of(SetMyDescription)
            assert len(shorts) == 3 and len(fulls) == 3
            for m in shorts:
                assert utf16_len(m.short_description) <= 120
            for m in fulls:
                assert utf16_len(m.description) <= 512
                assert m.description.endswith("example.com/privacy")
            session.calls.clear()
            await kit.set_profile_status(bot, online=False)
            await kit.set_menus(bot)
            assert not session.of(SetMyDescription)
            assert not session.of(SetMyCommands)

    asyncio.run(run())


def test_notices_round_trip(tmp_path):
    """Groups get "off for now", which becomes "back" on start."""

    async def run():
        kit = make_kit(tmp_path)
        bot, _dp, session = await started(kit)
        kit.store.see_chat(GROUP, "supergroup", "en")
        kit.store.see_chat(-7, "group", "en")
        kit.store.update_chat(-7, notices=0)
        kit.store.see_chat(USER, "private", "en")
        await kit.post_notices(bot, "offline")
        assert [m.chat_id for m in session.of(SendMessage)] == [GROUP]
        saved = json.loads(kit.store.get_setting("kit:status"))
        assert saved["kind"] == "offline" and len(saved["msgs"]) == 1
        await kit.clear_notices(bot)
        assert session.of(EditMessageText)
        assert kit.store.get_setting("kit:status") == ""
        await kit.post_notices(bot, "reload")
        await kit.clear_notices(bot)
        assert session.of(DeleteMessage)

    with texts():
        asyncio.run(run())


def test_autodelete_survives_restart(tmp_path):
    """The deletion queue is in the database, never in private."""

    async def run():
        kit = make_kit(tmp_path)
        bot, _dp, session = await started(kit)
        group_msg = session.message(bot, GROUP)
        private_msg = session.message(bot, USER)
        kit.autodelete(group_msg, 0)
        kit.autodelete(private_msg, 0)
        # A new kit on the same database: as after a restart.
        again = BotKit(kit.cfg, KitStore(tmp_path / "bot.db"), menu=[])
        due = again.store.due_deletions(int(time.time()) + 1)
        assert due == [(GROUP, group_msg.message_id)]
        task = asyncio.ensure_future(again._cleaner(bot))
        await asyncio.sleep(0.1)
        task.cancel()
        assert session.of(DeleteMessage)
        assert not again.store.due_deletions(int(time.time()) + 1)

    with texts():
        asyncio.run(run())


def test_menus_have_dev_commands(tmp_path):
    """Developers get their commands; groups their own texts."""

    async def run():
        bot_texts = {"en": {"menu.group.help": "Group help"}, "ru": {}}
        with texts(bot_texts):
            kit = make_kit(tmp_path, group_menu=["help"])
            bot, _dp, session = await started(kit)
            kit.store.del_setting("kit:menus")
            await kit.set_menus(bot)
            scopes = {}
            for m in session.of(SetMyCommands):
                key = (m.scope.type, m.language_code)
                scopes[key] = {c.command: c.description for c in m.commands}
            assert "reload" in scopes[("chat", None)]
            assert "reload" not in scopes[("default", None)]
            assert scopes[("all_group_chats", "en")]["help"] == "Group help"

    asyncio.run(run())


def test_membership_and_migration(tmp_path):
    """Added: greeting; removed: inactive; supergroup: data moves."""

    async def run():
        kit = make_kit(tmp_path)
        moved = []
        kit.on_chat_moved = lambda old, new: moved.append((old, new))

        async def welcome(bot, event, lang):
            return "hello"

        kit.welcome = welcome
        bot, dp, session = await started(kit)

        def member_update(status_old, status_new, chat_id=-5):
            _update_id[0] += 1
            user = {"id": USER, "is_bot": False, "first_name": "U"}
            me = {"id": 999, "is_bot": True, "first_name": "B"}
            return Update.model_validate(
                {
                    "update_id": _update_id[0],
                    "my_chat_member": {
                        "chat": {"id": chat_id, "type": "group"},
                        "from": {**user, "language_code": "ru"},
                        "date": int(time.time()),
                        "old_chat_member": {"status": status_old, "user": me},
                        "new_chat_member": {
                            "status": status_new,
                            "user": me,
                            "until_date": 0,
                        },
                    },
                },
                context={"bot": bot},
            )

        await dp.feed_update(bot, member_update("left", "member"))
        assert session.of(SendMessage)[-1].text.startswith("hello")
        assert kit.store.chat(-5)["hint"] == "ru"
        await dp.feed_update(bot, member_update("member", "kicked"))
        assert kit.store.chat(-5)["active"] == 0
        await dp.feed_update(bot, member_update("left", "member"))
        assert kit.store.chat(-5)["active"] == 1
        kit.set_lang(-5, "ru")
        _update_id[0] += 1
        await dp.feed_update(
            bot,
            Update.model_validate(
                {
                    "update_id": _update_id[0],
                    "message": {
                        "message_id": 1,
                        "date": int(time.time()),
                        "chat": {"id": -5, "type": "group"},
                        "migrate_to_chat_id": GROUP,
                    },
                },
                context={"bot": bot},
            ),
        )
        assert moved == [(-5, GROUP)]
        assert kit.lang_of(GROUP) == "ru"

    with texts():
        asyncio.run(run())


def test_settings_buttons(tmp_path):
    """Language and notices buttons work and return to /settings."""

    async def run():
        kit = make_kit(tmp_path)
        kit.settings_view = lambda chat_id, user_id: (
            kit.settings_lines(kit.lang_of(chat_id), chat_id),
            None,
        )
        bot, dp, session = await started(kit)
        session.admins.add(USER)
        await press(bot, dp, GROUP, USER, 1, "kit:notices")
        assert kit.store.chat(GROUP)["notices"] == 0
        assert "off" in session.of(EditMessageText)[-1].text
        await press(bot, dp, GROUP, USER, 1, "kit:langs")
        markup = session.of(EditMessageText)[-1].reply_markup
        assert markup.inline_keyboard[0][0].callback_data == "lang:en:st"
        await press(bot, dp, GROUP, USER, 1, "lang:ru:st")
        assert kit.lang_of(GROUP) == "ru"
        assert "Язык" in session.of(EditMessageText)[-1].text

    with texts():
        asyncio.run(run())


def test_privacy_and_id(tmp_path):
    """/privacy links the full text; /id shows both IDs."""

    async def run():
        with texts({"en": {"legal.privacy": "Privacy!"}, "ru": {}}):
            kit = make_kit(tmp_path)
            bot, dp, session = await started(kit)
            await send(bot, dp, USER, USER, "/privacy")
            text = session.of(SendMessage)[-1].text
            assert text.startswith("Privacy!")
            assert "example.com/privacy" in text and "@author" in text
            await send(bot, dp, GROUP, USER, "/id")
            assert f"chat {GROUP}" in session.of(SendMessage)[-1].text

    asyncio.run(run())


def test_shut_down_stop(tmp_path):
    """A /stop posts notices, shows offline and confirms the update."""

    async def run():
        kit = make_kit(tmp_path)
        bot, _dp, session = await started(kit)
        kit.store.see_chat(GROUP, "supergroup", "en")
        await kit._shut_down(
            bot, {"mode": "stop", "quiet": False, "update_id": 41}
        )
        assert [m.chat_id for m in session.of(SendMessage)] == [GROUP]
        offline = session.of(SetMyShortDescription)
        assert offline and "Offline" in offline[0].short_description
        from aiogram.methods import GetUpdates

        assert session.of(GetUpdates)[0].offset == 42

    with texts():
        asyncio.run(run())


if __name__ == "__main__":
    import tempfile

    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            with tempfile.TemporaryDirectory() as tmp:
                if "tmp_path" in fn.__code__.co_varnames:
                    fn(Path(tmp))
                else:
                    fn()
            print("✅", name)
