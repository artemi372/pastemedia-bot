"""Read the settings that every bot has from the .env file.

Secrets are kept in .env and are never written into the code. The
bot's own settings (API keys, intervals) are read by the bot itself.
"""

import logging
import os
from dataclasses import dataclass

from dotenv import load_dotenv

log = logging.getLogger("botkit")


@dataclass(frozen=True)
class KitConfig:
    """Settings shared by the bots."""

    bot_token: str
    # Shown in status messages ("Warden is restarting").
    bot_name: str
    # Developers: /broadcast, /reload, /stop and the bot's own service
    # commands. Everyone else doesn't even see these commands.
    dev_ids: tuple[int, ...]
    # Language for chats that haven't chosen one (DEFAULT_LANG).
    default_lang: str
    # Author contacts for /help, the bot profile and errors; empty
    # values are hidden.
    author_telegram: str
    author_github: str
    # Public source code, if any (shown next to the author).
    repo_url: str
    # Privacy policy and terms of use (/privacy, /terms, /help, bot
    # profile). Telegram requires every bot to have a privacy policy.
    privacy_url: str
    terms_url: str
    # Whether bot messages in groups delete themselves after a while.
    auto_delete: bool


def _flag(name: str, default: str) -> bool:
    """Read an on/off setting: 0, false, no or empty mean off."""
    return os.getenv(name, default).strip().lower() not in (
        "0",
        "false",
        "no",
        "",
    )


def _ids(raw: str) -> tuple[int, ...]:
    """Parse "123, 456" into (123, 456), skipping anything else."""
    parts = raw.replace(",", " ").split()
    return tuple(int(p) for p in parts if p.lstrip("-").isdigit())


def load_config(
    *,
    bot_name: str,
    default_lang: str,
    privacy_url: str = "",
    terms_url: str = "",
    repo_url: str = "",
) -> KitConfig:
    """Build the KitConfig from .env, with the bot's own defaults."""
    load_dotenv()
    token = os.getenv("BOT_TOKEN", "").strip()
    if not token:
        raise SystemExit("BOT_TOKEN is missing in .env")
    dev_ids = _ids(os.getenv("DEV_IDS", ""))
    for old in ("ADMIN_IDS", "OWNER_ID"):
        if os.getenv(old) and not dev_ids:
            log.warning("%s is no longer used: rename it to DEV_IDS", old)
    return KitConfig(
        bot_token=token,
        bot_name=bot_name,
        dev_ids=dev_ids,
        default_lang=os.getenv("DEFAULT_LANG", default_lang).strip(),
        # An empty value in .env (AUTHOR_TELEGRAM=) hides the contact.
        author_telegram=os.getenv("AUTHOR_TELEGRAM", "artemi372")
        .strip()
        .lstrip("@"),
        author_github=os.getenv("AUTHOR_GITHUB", "artemi372").strip(),
        repo_url=repo_url,
        privacy_url=os.getenv("PRIVACY_URL", privacy_url).strip(),
        terms_url=os.getenv("TERMS_URL", terms_url).strip(),
        auto_delete=_flag("AUTO_DELETE", "1"),
    )
