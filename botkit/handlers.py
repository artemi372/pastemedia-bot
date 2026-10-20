"""Handlers of the shared commands and events.

/privacy, /terms     short summary and a link to the full text
/id                  chat and user ID
/language (/lang)    the chat's language (groups: admins only)
/broadcast           developers: an announcement to every chat
/reload, /stop       developers: restart with new code, or shut down

Plus the language and notices buttons of /settings, a group becoming a
supergroup, and the bot being added to or removed from a chat.

Developer commands are invisible to everyone else: their filters don't
match, so the bot's own handlers see the message as usual.
"""

import asyncio
import logging
import time
from html import escape
from typing import TYPE_CHECKING

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.methods import SendRichMessage
from aiogram.types import (
    CallbackQuery,
    ChatMemberUpdated,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputRichMessage,
    LinkPreviewOptions,
    Message,
    Update,
)

from botkit import i18n, rich
from botkit.core import (
    SEND_DELAY,
    TTL_LONG,
    TTL_MEDIUM,
    TTL_SHORT,
    Tally,
    is_private,
)
from botkit.i18n import t

if TYPE_CHECKING:
    from botkit.core import BotKit

log = logging.getLogger("botkit")

NO_PREVIEW = LinkPreviewOptions(is_disabled=True)
# Words after /broadcast that make it silent.
SILENT_WORDS = ("silent", "тихо", "vaikselt")
# An unused broadcast panel is forgotten after this many seconds.
PANEL_TTL = 3600


def build_router(kit: "BotKit") -> Router:
    """Return the router with the shared handlers of a bot."""
    router = Router(name="botkit")
    dev = F.from_user.func(kit.is_dev)
    private = F.chat.type == "private"

    # ═════════════════════════════ LEGAL ═════════════════════════════
    @router.message(Command("privacy", "terms"))
    async def on_legal(message: Message, command: CommandObject):
        """Summarize the privacy policy or the terms, with a link.

        Telegram requires bots to have a privacy policy that users can
        easily find.
        """
        lang = kit.lang_of(message.chat.id, message.from_user)
        privacy = command.command.lower() == "privacy"
        url = kit.cfg.privacy_url if privacy else kit.cfg.terms_url
        name = "legal.privacy_name" if privacy else "legal.terms_name"
        text = t(lang, "legal.privacy" if privacy else "legal.terms")
        if url:
            text += t(lang, "legal.read", url=escape(url), name=t(lang, name))
        if kit.cfg.author_telegram:
            text += t(lang, "legal.contact", tg=f"@{kit.cfg.author_telegram}")
        await kit.reply(
            message, text, TTL_LONG, link_preview_options=NO_PREVIEW
        )

    @router.message(Command("id"))
    async def on_id(message: Message):
        """Show the chat ID and the user ID (for DEV_IDS and such)."""
        user_id = message.from_user.id if message.from_user else 0
        await kit.reply(
            message,
            f"<code>chat {message.chat.id}\nuser {user_id}</code>",
            TTL_MEDIUM,
        )

    # ════════════════════════════ LANGUAGE ═══════════════════════════
    @router.message(Command("language", "lang"))
    async def on_language(message: Message):
        """Offer the languages; in a group only to its admins."""
        lang = kit.lang_of(message.chat.id, message.from_user)
        if not await kit.can_manage(message):
            await kit.reply(message, t(lang, "err.admins_only"), TTL_SHORT)
            return
        key = "lang.choose" if is_private(message) else "lang.choose_group"
        await kit.reply(
            message,
            t(lang, key),
            TTL_MEDIUM,
            reply_markup=kit.language_keyboard(lang),
        )

    @router.callback_query(F.data.startswith("lang:"))
    async def on_language_chosen(callback: CallbackQuery):
        """Save the chosen language of the chat."""
        _, code, *rest = callback.data.split(":")
        msg = callback.message
        if code not in i18n.LANGS or not isinstance(msg, Message):
            await callback.answer()
            return
        if not await kit.can_manage(callback):
            lang = kit.lang_of(msg.chat.id, callback.from_user)
            await callback.answer(t(lang, "err.admins_only"), show_alert=True)
            return
        kit.set_lang(msg.chat.id, code)
        await callback.answer(t(code, "lang.set"))
        if rest == ["st"] and kit.settings_view is not None:
            text, kb = kit.settings_view(msg.chat.id, callback.from_user.id)
            await kit.edit(msg, text, None, reply_markup=kb)
        else:
            await kit.edit(
                msg, t(code, "lang.set"), TTL_SHORT, reply_markup=None
            )
        if kit.on_lang_changed is not None:
            await kit.on_lang_changed(callback, code)

    # ═══════════════════ /settings: SHARED BUTTONS ═══════════════════
    @router.callback_query(F.data.startswith("kit:"))
    async def on_settings_button(callback: CallbackQuery):
        """Handle the language and notices buttons of /settings."""
        msg = callback.message
        if not isinstance(msg, Message):
            await callback.answer()
            return
        lang = kit.lang_of(msg.chat.id, callback.from_user)
        if not await kit.can_manage(callback):
            await callback.answer(t(lang, "err.admins_only"), show_alert=True)
            return
        what = callback.data.split(":", 1)[1]
        if what == "langs":
            await callback.answer()
            key = "lang.choose" if is_private(msg) else "lang.choose_group"
            await kit.edit(
                msg,
                t(lang, key),
                None,
                reply_markup=kit.language_keyboard(
                    lang, back=kit.settings_view is not None
                ),
            )
            return
        if what == "notices" and kit.notices_apply(msg.chat.id):
            on = not kit.notices_on(msg.chat.id)
            kit.store.update_chat(msg.chat.id, notices=int(on))
            await callback.answer(
                t(lang, "notices.set_on" if on else "notices.set_off")
            )
        else:
            await callback.answer()
        if kit.settings_view is not None:
            text, kb = kit.settings_view(msg.chat.id, callback.from_user.id)
            await kit.edit(msg, text, None, reply_markup=kb)

    # ═══════════════════════════ BROADCAST ═══════════════════════════
    # A developer sends /broadcast [silent] [language] in a private
    # chat and gets a panel: sound or silent, all chats or one
    # language. The announcement is a REPLY to that panel: text, a
    # photo with a caption, anything. HTML that starts with "<" goes
    # out as a rich message. The bot shows what will be sent and asks
    # to confirm. The panel stays open, so the same news can go out
    # once per language: switch the language, reply again.
    panels: dict[int, dict] = {}
    jobs: dict[str, dict] = {}

    def panel_view(lang: str, panel: dict) -> tuple[str, InlineKeyboardMarkup]:
        """Return the text and the buttons of a broadcast panel."""
        mode, target = describe(lang, panel)
        tick = "✅ "

        def button(label: str, data: str, on: bool) -> InlineKeyboardButton:
            return InlineKeyboardButton(
                text=(tick if on else "") + label, callback_data=data
            )

        rows = [
            [
                button(
                    t(lang, "broadcast.btn_loud"),
                    "bc:set:loud",
                    not panel["silent"],
                ),
                button(
                    t(lang, "broadcast.btn_silent"),
                    "bc:set:silent",
                    panel["silent"],
                ),
            ],
            [
                button(
                    t(lang, "broadcast.btn_all"),
                    "bc:set:all",
                    panel["lang"] is None,
                ),
                *(
                    button(
                        code.upper(), f"bc:set:{code}", panel["lang"] == code
                    )
                    for code in i18n.LANGS
                ),
            ],
            [button(t(lang, "broadcast.btn_close"), "bc:close", False)],
        ]
        text = t(lang, "broadcast.panel", mode=mode, target=target)
        return text, InlineKeyboardMarkup(inline_keyboard=rows)

    def describe(lang: str, panel: dict) -> tuple[str, str]:
        """Return the "how" and "to whom" lines of a broadcast."""
        n = len(kit.broadcast_targets(panel["lang"], exclude=panel["dev"]))
        mode = t(
            lang,
            "broadcast.mode_silent"
            if panel["silent"]
            else "broadcast.mode_loud",
        )
        if panel["lang"]:
            target = t(
                lang,
                "broadcast.to_lang",
                lang=kit.lang_name(panel["lang"]),
                n=n,
            )
        else:
            target = t(lang, "broadcast.to_all", n=n)
        return mode, target

    @router.message(Command("broadcast"), private, dev)
    async def on_broadcast(message: Message, command: CommandObject):
        """Open a broadcast panel (developers only)."""
        now = time.time()
        for panel_id, panel in list(panels.items()):
            if now - panel["at"] > PANEL_TTL:
                panels.pop(panel_id, None)
        args = (command.args or "").lower().split()
        panel = {
            "dev": message.from_user.id,
            "silent": any(a in SILENT_WORDS for a in args),
            "lang": next((a for a in args if a in i18n.LANGS), None),
            "at": now,
        }
        lang = kit.lang_of(message.chat.id, message.from_user)
        text, kb = panel_view(lang, panel)
        sent = await message.answer(text, reply_markup=kb)
        panels[sent.message_id] = panel

    def is_panel_reply(message: Message) -> bool:
        """Return True for a developer's reply to their open panel."""
        ref = message.reply_to_message
        if ref is None or message.from_user is None:
            return False
        panel = panels.get(ref.message_id)
        return (
            panel is not None
            and panel["dev"] == message.from_user.id
            and not (message.text or "").startswith("/")
        )

    async def preview(message: Message, lang: str) -> tuple[dict, str]:
        """Show how the announcement will look; return how to send it.

        An ordinary message is copied as is, so the developer's own
        message is its preview. Rich HTML is sent back as a rich
        message; if Telegram rejects it, as ordinary HTML; if that
        fails too, the text goes out exactly as typed.
        """
        raw = (message.text or "").strip()
        if not raw.startswith("<"):
            return {"kind": "copy"}, ""
        try:
            await message.bot(
                SendRichMessage(
                    chat_id=message.chat.id,
                    rich_message=InputRichMessage(html=raw),
                )
            )
            return {"kind": "rich", "html": raw}, ""
        except TelegramBadRequest as e:
            note = t(lang, "broadcast.rich_failed", error=escape(str(e)))
        classic = rich.to_classic(raw)
        try:
            await message.answer(classic)
            return {"kind": "html", "html": classic}, note
        except TelegramBadRequest:
            return {"kind": "copy"}, note

    @router.message(private, F.func(is_panel_reply))
    async def on_broadcast_reply(message: Message):
        """Take the announcement and ask to confirm it."""
        panel = panels[message.reply_to_message.message_id]
        panel["at"] = time.time()
        lang = kit.lang_of(message.chat.id, message.from_user)
        how, note = await preview(message, lang)
        token = f"{message.chat.id}_{message.message_id}"
        jobs[token] = {
            **how,
            "dev": message.from_user.id,
            "chat": message.chat.id,
            "msg": message.message_id,
            "silent": panel["silent"],
            "lang": panel["lang"],
        }
        mode, target = describe(lang, panel)
        n = len(kit.broadcast_targets(panel["lang"], exclude=panel["dev"]))
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=t(lang, "broadcast.go", n=n),
                        callback_data=f"bc:go:{token}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text=t(lang, "broadcast.cancel"),
                        callback_data=f"bc:no:{token}",
                    )
                ],
            ]
        )
        text = t(lang, "broadcast.confirm", mode=mode, target=target)
        await message.reply(
            (note + "\n\n" if note else "") + text, reply_markup=kb
        )

    @router.callback_query(F.data.startswith("bc:"))
    async def on_broadcast_button(callback: CallbackQuery):
        """Handle the panel buttons and the send / cancel buttons."""
        msg = callback.message
        user = callback.from_user
        lang = kit.lang_of(user.id, user)
        parts = callback.data.split(":")
        action = parts[1] if len(parts) > 1 else ""
        if not kit.is_dev(user) or not isinstance(msg, Message):
            await callback.answer(t(lang, "err.expired"), show_alert=True)
            return
        if action in ("set", "close"):
            panel = panels.get(msg.message_id)
            if panel is None or panel["dev"] != user.id:
                await callback.answer(t(lang, "err.expired"), show_alert=True)
                return
            await callback.answer()
            if action == "close":
                panels.pop(msg.message_id, None)
                await kit.edit(msg, t(lang, "broadcast.closed"), None)
                return
            value = parts[2] if len(parts) > 2 else ""
            if value in ("loud", "silent"):
                panel["silent"] = value == "silent"
            elif value == "all":
                panel["lang"] = None
            elif value in i18n.LANGS:
                panel["lang"] = value
            panel["at"] = time.time()
            text, kb = panel_view(lang, panel)
            await kit.edit(msg, text, None, reply_markup=kb)
            return
        job = jobs.get(parts[2] if len(parts) > 2 else "")
        if job is None or job["dev"] != user.id:
            await callback.answer(t(lang, "err.expired"), show_alert=True)
            return
        # Removed before sending, so a second tap can't send it twice.
        jobs.pop(parts[2], None)
        await callback.answer()
        if action != "go":
            await kit.edit(msg, t(lang, "broadcast.cancelled"), None)
            return
        await kit.edit(msg, t(lang, "broadcast.started"), None)
        # In the background, so the bot keeps answering everyone else.
        kit.spawn(run_broadcast(callback.bot, job, msg, lang))

    async def run_broadcast(
        bot: Bot, job: dict, status: Message, lang: str
    ) -> None:
        """Send the announcement to every chat; report the result."""
        silent = job["silent"]
        if job["kind"] == "rich":

            def send(chat_id: int):
                return bot(
                    SendRichMessage(
                        chat_id=chat_id,
                        rich_message=InputRichMessage(html=job["html"]),
                        disable_notification=silent,
                    )
                )
        elif job["kind"] == "html":

            def send(chat_id: int):
                return bot.send_message(
                    chat_id, job["html"], disable_notification=silent
                )
        else:

            def send(chat_id: int):
                return bot.copy_message(
                    chat_id,
                    job["chat"],
                    job["msg"],
                    disable_notification=silent,
                )

        tally = Tally()
        for chat_id in kit.broadcast_targets(job["lang"], exclude=job["dev"]):
            await kit.deliver(bot, chat_id, send, tally)
            await asyncio.sleep(SEND_DELAY)
        log.info(
            "broadcast: %s delivered, %s failed, %s unreachable",
            tally.sent,
            tally.failed,
            tally.gone,
        )
        text = t(
            lang,
            "broadcast.done",
            sent=tally.sent,
            failed=tally.failed,
            gone=tally.gone,
        )
        try:
            await status.edit_text(text)
        except TelegramAPIError:
            await bot.send_message(job["chat"], text)

    # ═════════════════════════ /reload, /stop ═════════════════════════
    @router.message(Command("reload", "stop"), dev)
    async def on_stop(
        message: Message, command: CommandObject, event_update: Update
    ):
        """Restart with the latest code, or shut down (developers).

        "quiet" after the command skips the notices in chats.
        """
        cmd = command.command.lower()
        quiet = "quiet" in (command.args or "").lower().split()
        lang = kit.lang_of(message.chat.id, message.from_user)
        text = t(lang, "dev.reloading" if cmd == "reload" else "dev.stopping")
        if quiet:
            text += t(lang, "dev.quiet")
        await kit.reply(message, text, TTL_SHORT)
        kit.request_stop(
            cmd,
            quiet,
            chat_id=message.chat.id,
            update_id=event_update.update_id,
        )

    # ══════════════════════ CHATS COME AND GO ═══════════════════════
    @router.message(F.migrate_to_chat_id)
    async def on_migrate_to(message: Message):
        """Move the data when a group becomes a supergroup.

        This message comes in the old group.
        """
        kit.move_chat(message.chat.id, message.migrate_to_chat_id)

    @router.message(F.migrate_from_chat_id)
    async def on_migrate_from(message: Message):
        """Move the data when a group becomes a supergroup.

        This message comes in the new supergroup; whichever of the two
        arrives first does the job.
        """
        kit.move_chat(message.migrate_from_chat_id, message.chat.id)

    @router.my_chat_member(F.chat.type.in_({"private", "group", "supergroup"}))
    async def on_membership(event: ChatMemberUpdated):
        """Follow the bot being added, removed, blocked or unblocked.

        A group the bot was added to gets a greeting; a removed or
        blocked chat gets nothing more until it comes back.
        """
        old = event.old_chat_member.status
        new = event.new_chat_member.status
        chat = event.chat
        if new in ("left", "kicked"):
            kit.chat_gone(chat.id, f"bot {new}")
            return
        if old not in ("left", "kicked"):
            return
        if chat.type == "private" and (
            kit.keep_user is not None and not kit.keep_user(chat.id)
        ):
            return
        user = event.from_user
        hint = (
            i18n.supported(user.language_code)
            if user is not None and not user.is_bot
            else None
        )
        kit.store.see_chat(chat.id, chat.type, hint)
        kit.chat_back(chat.id)
        if chat.type == "private" or kit.welcome is None:
            return
        lang = kit.lang_of(chat.id)
        text = await kit.welcome(event.bot, event, lang)
        if not text:
            return
        try:
            await event.bot.send_message(
                chat.id,
                text + kit.legal_links(lang),
                link_preview_options=NO_PREVIEW,
            )
        except TelegramAPIError as e:
            log.warning("no greeting in %s: %s", chat.id, e)

    return router
