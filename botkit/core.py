"""The shared part of the bots: everything they do the same way.

One BotKit object per bot. It knows the chats, picks the language,
deletes messages later, checks who may do what, sends to chats safely,
keeps the profile status and the command menus up to date, posts the
restart notices and runs the bot until /stop or /reload. The handlers
for the shared commands live in handlers.py.

Hooks let the bot add its own behaviour; each one is optional and is
set as an attribute after creating the kit, for example::

    kit.on_chat_moved = db.move_tracked
"""

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass
from html import escape
from typing import Any, Awaitable, Callable, Iterable

from aiogram import Bot, Dispatcher, Router
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramMigrateToChat,
    TelegramRetryAfter,
)
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeChat,
    BotCommandScopeDefault,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    User,
)

from botkit import i18n, rich, runner
from botkit.config import KitConfig
from botkit.i18n import t
from botkit.runner import RELOAD_EXIT_CODE
from botkit.store import KitStore

log = logging.getLogger("botkit")

# How long bot messages live in groups, in seconds.
# Service messages: "looking...", errors, answers to commands.
TTL_SHORT = 15
# Help, greetings, lists.
TTL_MEDIUM = 60
# Longer reads: reports, legal texts, questions that need an answer.
TTL_LONG = 120
# Telegram allows about 30 messages per second.
SEND_DELAY = 0.05
# Telegram "Bad Request" messages that mean the chat is gone for good.
DEAD_CHAT_ERRORS = (
    "chat not found",
    "peer_id_invalid",
    "group chat was deleted",
    "chat was deleted",
    "user is deactivated",
    "bot was kicked",
)
# Commands handled by botkit itself.
KIT_COMMANDS = ("privacy", "terms", "id", "language", "lang")
# Developer commands handled by botkit; they appear in the developers'
# own command menu only.
DEV_COMMANDS = ("id", "broadcast", "reload", "stop")


def is_private(message: Message | None) -> bool:
    """Return True if the message was sent in a private chat."""
    return message is not None and message.chat.type == "private"


def utf16_len(text: str) -> int:
    """Return the length of a text the way Telegram counts it.

    Telegram counts UTF-16 code units, so most emoji take two.
    """
    return len(text.encode("utf-16-le")) // 2


def fit(text: str, limit: int) -> str:
    """Cut a text to a Telegram length limit, adding "…" if needed."""
    if utf16_len(text) <= limit:
        return text
    if limit <= 0:
        return ""
    while text and utf16_len(text + "…") > limit:
        text = text[:-1]
    return text.rstrip() + "…"


@dataclass
class Tally:
    """Counts of a mass send: a broadcast or the restart notices."""

    sent: int = 0
    failed: int = 0
    gone: int = 0


class BotKit:
    """Shared state and helpers of one bot."""

    def __init__(
        self,
        cfg: KitConfig,
        store: KitStore,
        *,
        menu: Iterable[str],
        group_menu: Iterable[str] = (),
        dev_menu: Iterable[str] = (),
        commands: Iterable[str] = (),
        notices_in_private: bool = False,
    ):
        """Set up the kit.

        ``menu`` is the command menu (names; the descriptions are the
        "menu.<name>" texts), ``group_menu`` an optional separate menu
        for groups and ``dev_menu`` the bot's own developer commands.
        ``commands`` are all commands of the bot: in groups they are
        deleted after a while. With ``notices_in_private`` the restart
        notices also go to private chats (see notice_chats).
        """
        from botkit.handlers import build_router

        self.cfg = cfg
        self.store = store
        i18n.set_default(cfg.default_lang)
        self.menu = list(menu)
        self.group_menu = list(group_menu)
        self.dev_menu = list(dev_menu)
        self.commands = {
            *commands,
            *self.menu,
            *self.group_menu,
            *self.dev_menu,
            *KIT_COMMANDS,
            *DEV_COMMANDS,
        }
        self.notices_in_private = notices_in_private
        self.username = ""

        # ── Hooks (all optional) ──
        # async (bot, event: ChatMemberUpdated, lang) -> str: the
        # greeting when the bot is added to a group.
        self.welcome: Callable[..., Awaitable[str]] | None = None
        # (chat_id, user_id) -> (text, keyboard): the bot's /settings
        # view, shown again after a language or notices change.
        self.settings_view: Callable[[int, int], tuple] | None = None
        # async (callback, lang): after the language of a chat changed.
        self.on_lang_changed: Callable[..., Awaitable[Any]] | None = None
        # (old_id, new_id): a group became a supergroup.
        self.on_chat_moved: Callable[[int, int], Any] | None = None
        # (chat_id): the bot was removed from a chat or blocked.
        self.on_chat_gone: Callable[[int], Any] | None = None
        # (chat_id): the bot was added back or unblocked.
        self.on_chat_back: Callable[[int], Any] | None = None
        # () -> chat IDs that get restart notices (default: groups).
        self.notice_chats: Callable[[], Iterable[int]] | None = None
        # (chat_id) -> True to leave a chat out of broadcasts.
        self.broadcast_skip: Callable[[int], bool] | None = None
        # (user_id) -> False to not remember a private chat at all.
        self.keep_user: Callable[[int], bool] | None = None
        # () -> str: the bot's part of the console "status" line.
        self.status_line: Callable[[], str] | None = None
        # Extra console commands: name -> (function, help text). The
        # function returns the text to print, or None.
        self.console_commands: dict[str, tuple[Callable, str]] = {}

        self._dp: Dispatcher | None = None
        self._stop: dict | None = None
        self._seen: dict[int, tuple[str, str | None]] = {}
        self._tasks: set[asyncio.Task] = set()
        self.router: Router = build_router(self)

    # ════════════════════════════ LANGUAGE ════════════════════════════
    def lang_of(self, chat_id: int | None, user: User | None = None) -> str:
        """Return the language to use in a chat.

        A language chosen with /language wins. Otherwise a private chat
        follows the user's Telegram app, and a group uses the language
        of the first person seen there. Without a chat (inline mode),
        the user's private chat decides.
        """
        if chat_id is None:
            if user is None:
                return i18n.DEFAULT_LANG
            chat_id = user.id
        row = self.store.chat(chat_id)
        if row is not None and row["lang"] in i18n.LANGS:
            return row["lang"]
        if chat_id > 0 and user is not None and user.id == chat_id:
            app = i18n.supported(user.language_code)
            if app:
                return app
        if row is not None and row["hint"] in i18n.LANGS:
            return row["hint"]
        return i18n.DEFAULT_LANG

    def set_lang(self, chat_id: int, lang: str) -> None:
        """Remember the language chosen for a chat."""
        self.store.update_chat(chat_id, lang=i18n.normalize(lang))

    @staticmethod
    def lang_name(lang: str) -> str:
        """Return the name of a language for buttons and settings."""
        return i18n.LANG_NAMES.get(lang, lang)

    # ═════════════════════════════ CHATS ══════════════════════════════
    def see(self, message: Message) -> None:
        """Remember the chat of an incoming message.

        Private chats are what a broadcast can reach; groups also get
        the restart notices. A database write happens only when
        something changed.
        """
        chat, user = message.chat, message.from_user
        if chat.type == "private":
            if user is None:
                return
            if self.keep_user is not None and not self.keep_user(user.id):
                return
            hint = i18n.supported(user.language_code)
            if self._seen.get(chat.id) == (chat.type, hint):
                return
        elif chat.type in ("group", "supergroup"):
            hint = (
                i18n.supported(user.language_code)
                if user is not None and not user.is_bot
                else None
            )
            prev = self._seen.get(chat.id)
            if (
                prev is not None
                and prev[0] == chat.type
                and (prev[1] is not None or hint is None)
            ):
                return
        else:
            return
        self.store.see_chat(chat.id, chat.type, hint)
        if chat.type != "private":
            row = self.store.chat(chat.id)
            hint = row["hint"] if row else hint
        self._seen[chat.id] = (chat.type, hint)

    def chat_gone(self, chat_id: int, reason: object = "") -> None:
        """Stop writing to a chat: the bot was removed or blocked."""
        self.store.update_chat(chat_id, active=0)
        self._seen.pop(chat_id, None)
        log.info(
            "chat %s is unreachable (%s), marked inactive", chat_id, reason
        )
        if self.on_chat_gone is not None:
            self.on_chat_gone(chat_id)

    def chat_back(self, chat_id: int) -> None:
        """Write to a chat again: the bot was added or unblocked."""
        self.store.update_chat(chat_id, active=1)
        self._seen.pop(chat_id, None)
        log.info("chat %s is reachable again", chat_id)
        if self.on_chat_back is not None:
            self.on_chat_back(chat_id)

    def move_chat(self, old_id: int, new_id: int) -> None:
        """Move everything about a group to its new supergroup ID.

        Telegram gives a group a new ID when it becomes a supergroup
        (for example after an admin changes some of its settings); the
        bot's and botkit's data move along. Moving twice is harmless:
        the message about it comes both in the old and the new chat.
        """
        moved = self.store.move_chat(old_id, new_id)
        self._seen.pop(old_id, None)
        self._seen.pop(new_id, None)
        if self.on_chat_moved is not None:
            self.on_chat_moved(old_id, new_id)
        if moved:
            log.info(
                "group %s is now supergroup %s, data moved", old_id, new_id
            )

    # ═══════════════════════════ PERMISSIONS ══════════════════════════
    def is_dev(self, user: User | int | None) -> bool:
        """Return True if the user is one of DEV_IDS."""
        user_id = user.id if isinstance(user, User) else user
        return user_id is not None and user_id in self.cfg.dev_ids

    @staticmethod
    async def is_chat_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
        """Return True if the user is an owner or admin of the group."""
        try:
            member = await bot.get_chat_member(chat_id, user_id)
        except TelegramAPIError:
            return False
        return member.status in ("creator", "administrator")

    async def can_manage(self, event: Message | CallbackQuery) -> bool:
        """Return True if the sender may change this chat's settings.

        Anyone may in a private chat; in a group only its admins
        (anonymous ones too) and the developers.
        """
        message = event.message if isinstance(event, CallbackQuery) else event
        if message is None or message.chat.type == "private":
            return True
        user = event.from_user
        if self.is_dev(user):
            return True
        if (
            isinstance(event, Message)
            and event.sender_chat is not None
            and event.sender_chat.id == event.chat.id
        ):
            return True  # an anonymous admin writes as the group
        if user is None:
            return False
        return await self.is_chat_admin(event.bot, message.chat.id, user.id)

    # ═════════════════════════ AUTO-DELETION ══════════════════════════
    def autodelete(
        self, msg: Message | bool | None, ttl: int | None, force=False
    ) -> None:
        """Queue a message for deletion after ``ttl`` seconds.

        Nothing is deleted in a private chat with the bot: that is the
        user's own space. ``ttl=None`` keeps the message. The queue is
        in the database, so a restart doesn't forget anything. With
        AUTO_DELETE=0 nothing is deleted unless ``force`` is set.
        """
        if (
            ttl is not None
            and (self.cfg.auto_delete or force)
            and isinstance(msg, Message)
            and not is_private(msg)
        ):
            self.store.schedule_delete(
                msg.chat.id, msg.message_id, int(time.time()) + ttl
            )

    async def reply(
        self, message: Message, text: str, ttl: int | None, **kwargs
    ) -> Message:
        """Answer in the message's chat and schedule the deletion."""
        msg = await message.answer(text, **kwargs)
        self.autodelete(msg, ttl)
        return msg

    async def edit(
        self, msg: Message, text: str, ttl: int | None, **kwargs
    ) -> None:
        """Edit a message and restart its deletion timer.

        A typical case is replacing "looking..." with the result. If
        that message is gone already, the text is sent anew.
        """
        try:
            await msg.edit_text(text, **kwargs)
        except TelegramBadRequest as e:
            if "not modified" in str(e):
                pass
            elif "message to edit not found" in str(e):
                self.autodelete(await msg.answer(text, **kwargs), ttl)
                return
            else:
                raise
        self.autodelete(msg, ttl)

    async def _cleaner(self, bot: Bot) -> None:
        """Delete the messages whose time has come, every 5 seconds."""
        while True:
            try:
                due = self.store.due_deletions(int(time.time()))
            except Exception:
                log.exception("couldn't read the deletion queue")
                due = []
            for chat_id, message_id in due:
                try:
                    await bot.delete_message(chat_id, message_id)
                except TelegramRetryAfter as e:
                    await asyncio.sleep(e.retry_after)
                    break
                except TelegramBadRequest as e:
                    # Deleted by hand, older than 48 hours or no rights
                    # in the group: there is nothing more to do.
                    log.debug("not deleted %s/%s: %s", chat_id, message_id, e)
                except TelegramForbiddenError as e:
                    log.debug("not deleted %s/%s: %s", chat_id, message_id, e)
                except Exception as e:
                    log.warning("network down, will delete later: %s", e)
                    break
                self.store.remove_deletion(chat_id, message_id)
            await asyncio.sleep(5)

    # ═══════════════════════════ CONTACTS ═════════════════════════════
    def contacts(self, html: bool = True) -> str:
        """Return the author's contacts as one line ("" if none)."""
        parts = []
        if self.cfg.author_telegram:
            parts.append(f"@{self.cfg.author_telegram}")
        if self.cfg.author_github:
            url = f"github.com/{self.cfg.author_github}"
            parts.append(
                f'<a href="https://{url}">GitHub</a>' if html else url
            )
        return " · ".join(parts)

    def credits(self, lang: str, html: bool = True) -> str:
        """Return the author line and the source code line."""
        out = ""
        contacts = self.contacts(html)
        if contacts:
            out += t(lang, "author.line", contacts=contacts)
        if self.cfg.repo_url:
            out += t(lang, "author.repo", repo=self.cfg.repo_url)
        return out

    def legal_links(self, lang: str) -> str:
        """Return the line with the terms and privacy policy links."""
        links = [
            f'<a href="{escape(url)}">{t(lang, name)}</a>'
            for url, name in (
                (self.cfg.terms_url, "legal.terms_name"),
                (self.cfg.privacy_url, "legal.privacy_name"),
            )
            if url
        ]
        return t(lang, "legal.links", links=" · ".join(links)) if links else ""

    def footer(self, lang: str) -> str:
        """Return the end of /start and /help: author, legal links."""
        return self.credits(lang) + self.legal_links(lang)

    def contact_hint(self, lang: str) -> str:
        """Return "if it keeps happening, message @author" or ""."""
        if not self.cfg.author_telegram:
            return ""
        return t(lang, "author.error", tg=f"@{self.cfg.author_telegram}")

    def dev_help(self, lang: str) -> str:
        """Return the developer part of /help (the bot's part too)."""
        text = t(lang, "help.dev")
        if i18n.has(lang, "help.dev_extra"):
            text += t(lang, "help.dev_extra")
        return text

    # ══════════════════════════ SETTINGS ══════════════════════════════
    def notices_apply(self, chat_id: int) -> bool:
        """Tell whether restart notices are a setting of this chat."""
        return chat_id < 0 or self.notices_in_private

    def notices_on(self, chat_id: int) -> bool:
        """Tell whether a chat wants the restart notices."""
        row = self.store.chat(chat_id)
        return row is None or bool(row["notices"])

    def settings_lines(self, lang: str, chat_id: int) -> str:
        """Return the shared lines of a /settings view."""
        lines = [t(lang, "settings.language", name=self.lang_name(lang))]
        if self.notices_apply(chat_id):
            state = (
                "settings.on" if self.notices_on(chat_id) else "settings.off"
            )
            lines.append(t(lang, "settings.notices", state=t(lang, state)))
        return "\n".join(lines)

    def settings_buttons(
        self, lang: str, chat_id: int
    ) -> list[InlineKeyboardButton]:
        """Return the shared buttons of a /settings view."""
        buttons = [
            InlineKeyboardButton(
                text=t(lang, "btn.language"), callback_data="kit:langs"
            )
        ]
        if self.notices_apply(chat_id):
            on = self.notices_on(chat_id)
            buttons.append(
                InlineKeyboardButton(
                    text=t(
                        lang, "btn.notices_on" if on else "btn.notices_off"
                    ),
                    callback_data="kit:notices",
                )
            )
        return buttons

    def language_keyboard(
        self, lang: str, back: bool = False
    ) -> InlineKeyboardMarkup:
        """Return the language buttons (and "Back" to the settings)."""
        suffix = ":st" if back else ""
        rows = [
            [
                InlineKeyboardButton(
                    text=self.lang_name(code),
                    callback_data=f"lang:{code}{suffix}",
                )
            ]
            for code in i18n.LANGS
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

    # ═════════════════════════ SAFE SENDING ═══════════════════════════
    async def deliver(
        self,
        bot: Bot,
        chat_id: int,
        send: Callable[[int], Awaitable[Any]],
        tally: Tally | None = None,
    ) -> Any:
        """Send something to a chat and return the result, or None.

        ``send`` gets the chat ID and makes the request. Flood limits
        are waited out; a group that became a supergroup gets it at the
        new ID (and its data moves); a chat where the bot was removed or
        blocked is marked unreachable, so nobody tries it again. One
        failing chat never stops the others.
        """
        tally = tally or Tally()
        for _ in range(5):
            try:
                result = await send(chat_id)
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
                continue
            except TelegramMigrateToChat as e:
                self.move_chat(chat_id, e.migrate_to_chat_id)
                chat_id = e.migrate_to_chat_id
                continue
            except TelegramForbiddenError as e:
                self.chat_gone(chat_id, e)
                tally.gone += 1
                return None
            except TelegramBadRequest as e:
                if any(s in str(e).lower() for s in DEAD_CHAT_ERRORS):
                    self.chat_gone(chat_id, e)
                    tally.gone += 1
                else:
                    log.warning("couldn't send to chat %s: %s", chat_id, e)
                    tally.failed += 1
                return None
            except TelegramAPIError as e:
                log.warning("couldn't send to chat %s: %s", chat_id, e)
                tally.failed += 1
                return None
            except Exception:
                log.exception("couldn't send to chat %s", chat_id)
                tally.failed += 1
                return None
            tally.sent += 1
            return result
        tally.failed += 1
        return None

    async def _silent_layer(self, make_request, bot, method):
        """Send messages to groups without a notification sound.

        Groups get silent messages, so the bot doesn't buzz everyone's
        phone; in a private chat the user is waiting, so a sound helps.
        A caller that sets disable_notification itself decides.
        """
        if getattr(method, "disable_notification", False) is None:
            chat_id = getattr(method, "chat_id", None)
            if isinstance(chat_id, int) and chat_id < 0:
                method.disable_notification = True
        return await make_request(bot, method)

    # ═══════════════════════════ BROADCAST ════════════════════════════
    def broadcast_targets(
        self, lang: str | None, exclude: int | None = None
    ) -> list[int]:
        """Return the chats a broadcast goes to: groups, then users.

        With ``lang``, only the chats where the bot speaks it.
        """
        out = []
        for row in self.store.chats(active=True):
            chat_id = row["chat_id"]
            if chat_id == exclude:
                continue
            if self.broadcast_skip is not None and self.broadcast_skip(
                chat_id
            ):
                continue
            if lang and self.lang_of(chat_id) != lang:
                continue
            out.append(chat_id)
        return out

    # ═════════════════════════ PROFILE STATUS ═════════════════════════
    # The bot profile has two texts, and both start with the status:
    #   short description: the "about" line in the profile and in
    #                      search (up to 120 characters);
    #   description:       the "What can this bot do?" screen in an
    #                      empty chat (up to 512 characters).
    # The bot's texts are "profile.short" and "profile.full" ({bot} is
    # its username). Telegram has strict rate limits here, so a text is
    # sent only when it has changed.
    async def set_profile_status(self, bot: Bot, online: bool) -> None:
        """Show 🟢 online or 🔴 offline in the bot profile."""
        status_key = "status.online" if online else "status.offline"
        for code in (None, *i18n.LANGS):
            lang = code or i18n.DEFAULT_LANG
            status = t(lang, status_key)
            by = (
                t(lang, "profile.by", tg=f"@{self.cfg.author_telegram}")
                if self.cfg.author_telegram
                else ""
            )
            short = fit(
                " · ".join(
                    p for p in (status, t(lang, "profile.short"), by) if p
                ),
                120,
            )
            privacy = (
                t(lang, "profile.privacy", url=self.cfg.privacy_url)
                if self.cfg.privacy_url
                else ""
            )
            if utf16_len(privacy) > 200:
                privacy = ""  # a link that long would crowd out the text
            body = (
                status
                + "\n\n"
                + t(lang, "profile.full", bot=self.username)
                + self.credits(lang, html=False)
            )
            # The privacy link must stay even if the text is cut.
            full = fit(body, 512 - utf16_len(privacy)) + privacy
            key = f"kit:profile:{code or '-'}"
            if self.store.get_setting(key) == short + "\n" + full:
                continue
            try:
                await bot.set_my_short_description(
                    short_description=short, language_code=code
                )
                await bot.set_my_description(
                    description=full, language_code=code
                )
            except TelegramRetryAfter as e:
                log.warning("profile not updated, flood limit: %s", e)
                return
            except TelegramAPIError as e:
                log.warning("profile not updated (%s): %s", code or "-", e)
                continue
            self.store.set_setting(key, short + "\n" + full)

    # ══════════════════════════ COMMAND MENUS ═════════════════════════
    @staticmethod
    def _commands(
        lang: str, names: Iterable[str], prefix: str = "menu."
    ) -> list[BotCommand]:
        """Build a command menu from command names.

        The description is the "menu.<name>" text; the group menu
        prefers "menu.group.<name>" if the bot has one.
        """
        out, seen = [], set()
        for name in names:
            if name in seen:
                continue
            seen.add(name)
            key = f"{prefix}{name}"
            if not i18n.has(lang, key):
                key = f"menu.{name}"
            out.append(BotCommand(command=name, description=t(lang, key)))
        return out

    async def set_menus(self, bot: Bot) -> None:
        """Set the command menus in every language.

        Telegram shows the menu that matches the app language. Groups
        can have their own menu; the developers' menu also has the
        developer commands, and nobody else sees those. Nothing is sent
        if the menus haven't changed since the last start.
        """
        plan = []
        dev_names = [*self.menu, *self.dev_menu, *DEV_COMMANDS]
        for code in (None, *i18n.LANGS):
            lang = code or i18n.DEFAULT_LANG
            plan.append(("all", code, self._commands(lang, self.menu)))
            if self.group_menu:
                plan.append(
                    (
                        "groups",
                        code,
                        self._commands(lang, self.group_menu, "menu.group."),
                    )
                )
            for dev in self.cfg.dev_ids:
                plan.append((dev, code, self._commands(lang, dev_names)))
        digest = hashlib.sha256(
            json.dumps(
                [
                    (scope, code, [(c.command, c.description) for c in cmds])
                    for scope, code, cmds in plan
                ]
            ).encode()
        ).hexdigest()
        if self.store.get_setting("kit:menus") == digest:
            return
        complete = True
        for scope, code, commands in plan:
            if scope == "all":
                target = BotCommandScopeDefault()
            elif scope == "groups":
                target = BotCommandScopeAllGroupChats()
            else:
                target = BotCommandScopeChat(chat_id=scope)
            try:
                await bot.set_my_commands(
                    commands, scope=target, language_code=code
                )
            except TelegramRetryAfter as e:
                log.warning("menus not updated, flood limit: %s", e)
                return
            except TelegramAPIError as e:
                # A developer who never opened the bot has no chat yet.
                log.warning("no %s menu for %s: %s", code or "-", scope, e)
                complete = False
        if complete:
            self.store.set_setting("kit:menus", digest)

    # ═════════════════════════ RESTART NOTICES ════════════════════════
    # On /stop or /reload (and the console commands) every chat that
    # wants it gets a short notice; "quiet" skips it. On the next start
    # an "off" notice in a group turns into "back online" (and goes away
    # by itself); the others are simply deleted.
    def notice_targets(self) -> list[int]:
        """Return the chats that get the restart notices."""
        if self.notice_chats is not None:
            candidates = set(self.notice_chats())
        else:
            candidates = {
                r["chat_id"]
                for r in self.store.chats(active=True)
                if r["kind"] != "private"
            }
        out = []
        for chat_id in sorted(candidates):
            if chat_id > 0 and not self.notices_in_private:
                continue
            row = self.store.chat(chat_id)
            if row is not None and (not row["active"] or not row["notices"]):
                continue
            out.append(chat_id)
        return out

    async def post_notices(self, bot: Bot, kind: str) -> None:
        """Post "off for now" or "restarting" (offline / reload)."""
        sent = []
        tally = Tally()
        for chat_id in self.notice_targets():
            text = t(
                self.lang_of(chat_id),
                f"status.notice_{kind}",
                bot=self.cfg.bot_name,
            )
            msg = await self.deliver(
                bot, chat_id, lambda c, s=text: bot.send_message(c, s), tally
            )
            if msg is not None:
                sent.append([msg.chat.id, msg.message_id])
            await asyncio.sleep(SEND_DELAY)
        self.store.set_setting(
            "kit:status", json.dumps({"kind": kind, "msgs": sent})
        )
        log.info(
            "%s notices: %s sent, %s failed", kind, tally.sent, tally.failed
        )

    async def clear_notices(self, bot: Bot) -> None:
        """Clean up the notices of the previous run."""
        raw = self.store.get_setting("kit:status")
        if not raw:
            return
        self.store.set_setting("kit:status", "")
        data = json.loads(raw)
        for chat_id, message_id in data.get("msgs", []):
            try:
                if data.get("kind") == "offline" and chat_id < 0:
                    msg = await bot.edit_message_text(
                        t(
                            self.lang_of(chat_id),
                            "status.notice_back",
                            bot=self.cfg.bot_name,
                        ),
                        chat_id=chat_id,
                        message_id=message_id,
                    )
                    self.autodelete(msg, TTL_MEDIUM, force=True)
                else:
                    await bot.delete_message(chat_id, message_id)
            except TelegramAPIError:
                # Deleted by hand, or older than 48 hours.
                pass

    async def _greet_after_reload(self, bot: Bot) -> None:
        """Tell the developer who sent /reload that the bot is back."""
        raw = self.store.get_setting("kit:reload_chat")
        if not raw:
            return
        self.store.del_setting("kit:reload_chat")
        chat_id = int(raw)
        try:
            msg = await bot.send_message(
                chat_id, t(self.lang_of(chat_id), "dev.back")
            )
            self.autodelete(msg, TTL_SHORT)
        except TelegramAPIError as e:
            log.warning("couldn't say I'm back in %s: %s", chat_id, e)

    # ═════════════════════════ START AND STOP ═════════════════════════
    def spawn(self, coro: Awaitable) -> asyncio.Task:
        """Run a coroutine in the background, keeping a reference."""
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._task_done)
        return task

    def _task_done(self, task: asyncio.Task) -> None:
        """Forget a finished background task and log its crash.

        Without this a background loop that raised (the match tracker,
        the deletion queue) would stop without a single line in the log.
        """
        self._tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            log.error(
                "background task %s crashed",
                task.get_coro().__qualname__,
                exc_info=error,
            )

    def request_stop(
        self,
        mode: str,
        quiet: bool = False,
        *,
        chat_id: int | None = None,
        update_id: int | None = None,
    ) -> None:
        """Stop the bot: mode "stop" (off) or "reload" (new code).

        Without ``quiet``, chats get a notice. ``chat_id`` gets "back
        online" after a reload; ``update_id`` is the command's update,
        confirmed to Telegram so that it isn't delivered again.
        """
        if self._dp is None:
            return
        self._stop = {"mode": mode, "quiet": quiet, "update_id": update_id}
        if mode == "reload" and chat_id is not None:
            self.store.set_setting("kit:reload_chat", str(chat_id))
        log.info("%s requested%s", mode, " (quiet)" if quiet else "")
        self.spawn(self._dp.stop_polling())

    def status(self) -> str:
        """Return the console "status" line."""
        rows = self.store.chats(active=True)
        groups = sum(1 for r in rows if r["kind"] != "private")
        line = (
            f"Online as @{self.username}. Chats: {groups} groups, "
            f"{len(rows) - groups} private."
        )
        if self.status_line is not None:
            line += " " + self.status_line()
        return line

    async def console(self, line: str) -> None:
        """Run a command typed into the console window."""
        words = line.strip().lower().split()
        if not words:
            return
        cmd, flags = words[0], set(words[1:])
        if cmd in ("stop", "reload") and flags <= {"quiet"}:
            print("Restarting…" if cmd == "reload" else "Shutting down…")
            self.request_stop(cmd, "quiet" in flags)
        elif cmd == "status":
            print(self.status())
        elif cmd in self.console_commands and not flags:
            out = self.console_commands[cmd][0]()
            if out:
                print(out)
        else:
            print(self.console_help())

    def console_help(self) -> str:
        """Return the list of console commands."""
        lines = [
            "Console commands:",
            "  stop [quiet]    shut down (quiet: no notices in chats)",
            "  reload [quiet]  restart with the latest code",
            "  status          what the bot is doing",
        ]
        for name, (_, about) in self.console_commands.items():
            lines.append(f"  {name:<15} {about}")
        return "\n".join(lines)

    async def setup(self, bot: Bot, dp: Dispatcher, *routers: Router):
        """Connect the kit to the bot and the dispatcher.

        Installs the request layers (silent messages in groups, rich
        messages) and the handlers, then brings the profile, the menus
        and the notices of the previous run up to date.
        """
        self._dp = dp
        bot.session.middleware(self._silent_layer)
        bot.session.middleware(rich.layer)
        dp.message.outer_middleware(self._on_message)
        dp.include_router(self.router)
        for router in routers:
            dp.include_router(router)
        self.username = (await bot.me()).username or ""
        await self.set_menus(bot)
        await self.set_profile_status(bot, online=True)
        await self.clear_notices(bot)
        await self._greet_after_reload(bot)

    async def serve(
        self,
        bot: Bot,
        dp: Dispatcher,
        *routers: Router,
        background: Iterable[Awaitable] = (),
    ) -> int:
        """Run the bot until /stop or /reload; return the exit code.

        botkit's handlers come first, then the bot's ``routers``.
        ``background`` are the bot's own endless loops.
        """
        await self.setup(bot, dp, *routers)
        self.spawn(self._cleaner(bot))
        for coro in background:
            self.spawn(coro)
        runner.keep_awake(True)
        runner.start_console(self)
        print("Bot is running. Type 'help' for console commands.")
        try:
            await dp.start_polling(
                bot,
                allowed_updates=dp.resolve_used_update_types(),
                close_bot_session=False,
            )
        finally:
            runner.keep_awake(False)
            for task in list(self._tasks):
                task.cancel()
            stop = self._stop or {"mode": "signal", "quiet": True}
            try:
                await self._shut_down(bot, stop)
            finally:
                await bot.session.close()
        return RELOAD_EXIT_CODE if stop["mode"] == "reload" else 0

    async def _shut_down(self, bot: Bot, stop: dict) -> None:
        """Post the notices, show offline and confirm the last command.

        A reload takes only a few seconds, so the profile status stays
        online instead of flickering. Ctrl+C or a service stop are
        quiet.
        """
        mode = stop["mode"]
        try:
            if mode in ("stop", "reload") and not stop["quiet"]:
                await asyncio.wait_for(
                    self.post_notices(
                        bot, "reload" if mode == "reload" else "offline"
                    ),
                    60,
                )
            if mode != "reload":
                await asyncio.wait_for(
                    self.set_profile_status(bot, online=False), 15
                )
        except Exception as e:
            log.warning("shutdown notices not finished: %s", e)
        # Otherwise Telegram would deliver /reload again after the
        # restart, and the bot would restart forever.
        if stop.get("update_id") is not None:
            try:
                await bot.get_updates(
                    offset=stop["update_id"] + 1, timeout=0, limit=1
                )
            except TelegramAPIError as e:
                log.warning("couldn't confirm the last command: %s", e)
        log.info("bot stopped (%s)", mode)

    async def _on_message(self, handler, event: Message, data: dict):
        """Run before every incoming message.

        Remember the chat, and in a group queue the user's command to
        this bot for deletion, to keep the group clean.
        """
        try:
            self.see(event)
        except Exception:
            log.exception("couldn't remember chat %s", event.chat.id)
        if (
            event.chat.type in ("group", "supergroup")
            and event.text
            and event.text.startswith("/")
        ):
            command, _, target = event.text.split()[0][1:].partition("@")
            if command.lower() in self.commands and (
                not target or target.lower() == self.username.lower()
            ):
                self.autodelete(event, TTL_SHORT)
        return await handler(event, data)
