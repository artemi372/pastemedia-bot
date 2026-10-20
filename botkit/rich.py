"""Telegram rich messages (Bot API 10.1+).

Rich messages support tables, lists and collapsible blocks, which
ordinary messages don't. A bot can mark a text with ``wrap``; a request
middleware then turns any message or edit whose text carries the mark
into sendRichMessage / editMessageText with rich_message (see
``to_method``). So every path that sends or edits a message works
unchanged. A broadcast that starts with "<" is sent the same way.

If Telegram rejects a rich message, ``to_classic`` turns it into an
ordinary HTML message, so nothing is ever lost. Inline results stay
ordinary messages.
"""

import logging
import re

from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import EditMessageText, SendMessage, SendRichMessage
from aiogram.types import InputRichMessage, ReplyParameters

log = logging.getLogger("botkit")

# Invisible prefix that marks a text written as rich HTML.
MARK = "\u2063rich\u2063"
# Telegram errors that have nothing to do with how a message is
# formatted: an ordinary message would fail the same way.
NOT_FORMAT_ERRORS = (
    "not modified",
    "message to edit not found",
    "message can't be edited",
    "chat not found",
    "bot was blocked",
    "not enough rights",
)


def wrap(html: str) -> str:
    """Mark rich HTML so that ``layer`` sends it as rich."""
    return MARK + html


def is_rich(text) -> bool:
    """Return True if a text is marked as rich HTML."""
    return isinstance(text, str) and text.startswith(MARK)


def unwrap(text: str) -> str:
    """Return the rich HTML without the mark."""
    return text[len(MARK) :] if is_rich(text) else text


def to_method(method):
    """Turn a marked SendMessage / EditMessageText into a rich one."""
    text = getattr(method, "text", None)
    if not is_rich(text):
        return method
    message = InputRichMessage(html=unwrap(text))
    if isinstance(method, SendMessage):
        reply = method.reply_parameters
        if reply is None and method.reply_to_message_id:
            reply = ReplyParameters(message_id=method.reply_to_message_id)
        return SendRichMessage(
            chat_id=method.chat_id,
            rich_message=message,
            message_thread_id=method.message_thread_id,
            disable_notification=method.disable_notification,
            protect_content=method.protect_content,
            reply_parameters=reply,
            reply_markup=method.reply_markup,
        )
    if isinstance(method, EditMessageText):
        return method.model_copy(
            update={"text": None, "parse_mode": None, "rich_message": message}
        )
    return method


def classic_method(method):
    """Return the method with a marked text as ordinary HTML."""
    text = getattr(method, "text", None)
    if not is_rich(text):
        return method
    return method.model_copy(update={"text": to_classic(unwrap(text))})


def _cells(row: str) -> list[tuple[bool, str]]:
    return [
        (tag == "th", re.sub(r"<br\s*/?>", " · ", body).strip())
        for tag, body in re.findall(r"<(th|td)[^>]*>(.*?)</\1>", row, re.S)
    ]


def _table(m: re.Match) -> str:
    lines = []
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", m.group(0), re.S):
        cells = _cells(row)
        if cells and all(head for head, _ in cells):
            continue  # the header row is obvious without a table
        lines.append(" · ".join(body for _, body in cells))
    return "\n".join(lines) + "\n\n"


def to_classic(html: str) -> str:
    """Downgrade rich HTML to the HTML of an ordinary message."""
    # Line breaks between tags are only source formatting.
    html = re.sub(r">\s+<", "><", html.strip())
    text = re.sub(r"<table[^>]*>.*?</table>", _table, html, flags=re.S)
    text = re.sub(
        r"<details[^>]*>\s*<summary>(.*?)</summary>(.*?)</details>",
        lambda m: f"<blockquote expandable>{m.group(2).strip()}</blockquote>",
        text,
        flags=re.S,
    )
    text = re.sub(r"<li[^>]*>(.*?)</li>", r"• \1\n", text, flags=re.S)
    text = re.sub(r"</?(ul|ol)[^>]*>", "", text)
    text = re.sub(r"<h\d[^>]*>(.*?)</h\d>", r"<b>\1</b>\n\n", text, flags=re.S)
    text = re.sub(r"<br\s*/?>", "\n", text)
    text = re.sub(r"<p[^>]*>(.*?)</p>", r"\1\n\n", text, flags=re.S)
    text = re.sub(r"\n{3,}", "\n\n", text)
    # No empty lines right inside a quote.
    text = re.sub(r"\n+</blockquote>", "</blockquote>", text)
    text = re.sub(
        r"<blockquote expandable>\n+", "<blockquote expandable>", text
    )
    return text.strip()


async def layer(make_request, bot, method):
    """Send marked texts as rich messages (a request middleware).

    If Telegram rejects the rich version, the same message goes out as
    ordinary HTML, so it is never lost.
    """
    if not is_rich(getattr(method, "text", None)):
        return await make_request(bot, method)
    try:
        return await make_request(bot, to_method(method))
    except TelegramBadRequest as e:
        if any(s in str(e).lower() for s in NOT_FORMAT_ERRORS):
            raise
        log.warning("rich message rejected (%s), sending an ordinary one", e)
        return await make_request(bot, classic_method(method))
