"""botkit: what Warden and Media Paste Bot do the same way.

This folder is identical in both bots. Change it in one of them, then
copy the whole folder to the other, so the shared parts never drift
apart again. What is here:

    config.py    settings every bot has (.env): DEV_IDS, author, links
    store.py     SQLite: known chats, settings, auto-deletion queue
    i18n.py      texts in the chat's language, t(lang, key)
    texts.py     the shared texts in English, Russian and Estonian
    core.py      BotKit: language, permissions, auto-deletion, safe
                 sending, profile status, menus, restart notices
    handlers.py  /privacy, /terms, /id, /language, /broadcast,
                 /reload, /stop, groups becoming supergroups
    rich.py      Telegram rich messages (tables, lists, headings)
    runner.py    the supervisor that restarts the bot on /reload, the
                 console commands, keep Windows awake

A bot uses it like this::

    store = Storage()                         # extends KitStore
    kit = BotKit(load_config(...), store, menu=[...])
    ...
    async def main() -> int:
        bot = Bot(kit.cfg.bot_token, ...)
        return await kit.serve(bot, Dispatcher(), router)

    if __name__ == "__main__":
        run(main)
"""

from botkit.config import KitConfig, load_config
from botkit.core import (
    DEAD_CHAT_ERRORS,
    TTL_LONG,
    TTL_MEDIUM,
    TTL_SHORT,
    BotKit,
    Tally,
    fit,
    is_private,
    utf16_len,
)
from botkit.runner import run, setup_logging
from botkit.store import KitStore, chat_kind

__all__ = [
    "DEAD_CHAT_ERRORS",
    "TTL_LONG",
    "TTL_MEDIUM",
    "TTL_SHORT",
    "BotKit",
    "KitConfig",
    "KitStore",
    "Tally",
    "chat_kind",
    "fit",
    "is_private",
    "load_config",
    "run",
    "setup_logging",
    "utf16_len",
]
