"""Look up texts in the chat's language.

The bot registers its own texts once (in its texts module); they are
merged with the shared texts of botkit, and the bot's version of a key
wins. Usage::

    t("en", "lang.set")             ->  "✅ Language: English"
    t("ru", "broadcast.go", n=3)     ->  "✅ Отправить в 3 чатов"

A missing translation falls back to the default language, then to
English, then to the key itself, so the bot never fails on a missing
text.
"""

import logging

from botkit.texts import KIT_LANG_NAMES, KIT_TEXTS

log = logging.getLogger("botkit")

# Merged texts: language -> key -> text.
TEXTS: dict[str, dict[str, str]] = {"en": dict(KIT_TEXTS["en"])}
LANGS: tuple[str, ...] = ("en",)
LANG_NAMES: dict[str, str] = dict(KIT_LANG_NAMES)
DEFAULT_LANG = "en"


def register(
    texts: dict[str, dict[str, str]],
    langs: tuple[str, ...],
    default: str,
) -> None:
    """Register the bot's texts and the languages it speaks."""
    global LANGS, DEFAULT_LANG
    LANGS = tuple(langs)
    DEFAULT_LANG = default if default in LANGS else LANGS[0]
    TEXTS.clear()
    for code in set(LANGS) | {"en"}:
        TEXTS[code] = {**KIT_TEXTS.get(code, {}), **texts.get(code, {})}


def set_default(lang: str) -> None:
    """Change the default language (DEFAULT_LANG in .env)."""
    global DEFAULT_LANG
    DEFAULT_LANG = normalize(lang, LANGS[0])


def supported(code: str | None) -> str | None:
    """Return the supported language for a Telegram code, or None.

    For example, "ru-RU" becomes "ru". An unsupported or missing code
    gives None.
    """
    code = (code or "").split("-")[0].lower()
    return code if code in LANGS else None


def normalize(code: str | None, default: str | None = None) -> str:
    """Return a supported language for a code, or the default one."""
    return supported(code) or default or DEFAULT_LANG


def has(lang: str, key: str) -> bool:
    """Tell whether a text exists in the language or the defaults."""
    return any(key in TEXTS.get(c, {}) for c in (lang, DEFAULT_LANG, "en"))


def t(lang: str, key: str, /, **params) -> str:
    """Return the text for a key in the given language.

    Keyword parameters are substituted with str.format().
    """
    for code in (lang, DEFAULT_LANG, "en"):
        text = TEXTS.get(code, {}).get(key)
        if text is not None:
            break
    else:
        log.warning("missing text: %s", key)
        return key
    return text.format(**params) if params else text
