"""Read the settings that every bot has from the .env file.

Secrets are kept in .env and are never written into the code. The
bot's own settings (API keys, intervals) are read by the bot itself.
"""

import logging
import os
from dataclasses import dataclass, field

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
    # The same pages in other languages: lang -> url, from
    # PRIVACY_URL_RU, TERMS_URL_ET and so on. A language without its
    # own page gets privacy_url / terms_url.
    privacy_urls: dict[str, str] = field(default_factory=dict)
    terms_urls: dict[str, str] = field(default_factory=dict)

    def privacy_for(self, lang: str) -> str:
        """Return the privacy policy link for a language."""
        return self.privacy_urls.get(lang) or self.privacy_url

    def terms_for(self, lang: str) -> str:
        """Return the terms of use link for a language."""
        return self.terms_urls.get(lang) or self.terms_url


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


def _per_lang(name: str) -> dict[str, str]:
    """Read NAME_RU, NAME_ET... from .env into {"ru": url, ...}.

    Empty values are left out, so that language falls back to NAME.
    """
    prefix = name + "_"
    return {
        key[len(prefix) :].lower(): value.strip()
        for key, value in os.environ.items()
        if key.startswith(prefix)
        and key[len(prefix) :].isalpha()
        and value.strip()
    }


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
        privacy_urls=_per_lang("PRIVACY_URL"),
        terms_urls=_per_lang("TERMS_URL"),
    )
