"""Store the bot state in a small SQLite database (data/bot.db).

The shared tables (known chats, settings, the auto-deletion queue) come
from botkit's KitStore. The bot's own tables:

1. media: Telegram file_ids of everything uploaded to the storage
   channel, so a video is uploaded there once, not after every restart
   or for every kind of link to it.
2. recent: the latest videos in each group, so a repeated link points
   to the earlier message instead of sending the video again.
3. bans: users who may not use the bot, and why.
4. blocked: posts the bot won't download.
5. uploads: who requested each stored video (for a week), so the
   author can ban whoever downloads forbidden content.

Before botkit this lived in state.json and media_cache.json; they are
imported once and kept as *.imported.
"""

import json
import logging
import time
from pathlib import Path
from typing import Any

from botkit import KitStore, chat_kind

log = logging.getLogger("bot")

BASE = Path(__file__).parent
DB_PATH = BASE / "data" / "bot.db"
# Entries per media kind; the oldest are dropped.
MEDIA_LIMIT = 5000
# Videos remembered per group, and for how long.
RECENT_LIMIT = 50
RECENT_MAX_AGE = 7 * 24 * 60 * 60
# Who requested an upload is kept this long.
UPLOADS_MAX_AGE = 7 * 24 * 60 * 60

SCHEMA = """
CREATE TABLE IF NOT EXISTS media (
    kind     TEXT,                -- "videos" or "albums"
    key      TEXT,                -- media_key() of the post
    value    TEXT,                -- file_id, or album items as JSON
    saved_at INTEGER,
    PRIMARY KEY (kind, key)
);
CREATE TABLE IF NOT EXISTS recent (
    chat_id    INTEGER,
    key        TEXT,              -- "<topic>:<media key>"
    message_id INTEGER,
    posted_at  INTEGER,
    PRIMARY KEY (chat_id, key)
);
CREATE TABLE IF NOT EXISTS bans (
    user_id  INTEGER PRIMARY KEY,
    kind     TEXT,                -- "abuse", or "request": asked for it
    reason   TEXT,
    at       INTEGER,
    appealed INTEGER DEFAULT 0,   -- when the last appeal was sent
    lang     TEXT                 -- to answer the appeal in
);
CREATE TABLE IF NOT EXISTS blocked (
    key    TEXT PRIMARY KEY,
    reason TEXT,
    at     INTEGER
);
CREATE TABLE IF NOT EXISTS uploads (
    message_id INTEGER PRIMARY KEY,  -- in the storage channel
    user_id    INTEGER,
    at         INTEGER
);
"""


class Storage(KitStore):
    """The bot's SQLite database."""

    def __init__(self, path: Path = DB_PATH):
        """Open the database and create its tables."""
        super().__init__(path)
        self.db.executescript(SCHEMA)

    # ── Media cache ──
    def media_get(self, kind: str, key: str) -> Any:
        """Return a cached file_id (or album items), or None."""
        row = self.db.execute(
            "SELECT value FROM media WHERE kind=? AND key=?", (kind, key)
        ).fetchone()
        return json.loads(row["value"]) if row else None

    def media_put(self, kind: str, key: str, value: Any) -> None:
        """Save a file_id (or album items); drop the oldest extra."""
        self.db.execute(
            "INSERT OR REPLACE INTO media VALUES (?, ?, ?, ?)",
            (kind, key, json.dumps(value), int(time.time())),
        )
        self.db.execute(
            "DELETE FROM media WHERE kind=? AND key NOT IN ("
            "SELECT key FROM media WHERE kind=? "
            "ORDER BY saved_at DESC, rowid DESC LIMIT ?)",
            (kind, kind, MEDIA_LIMIT),
        )
        self.db.commit()

    def media_drop(self, key: str) -> None:
        """Forget the cached file_ids of a post: never reuse them."""
        self.db.execute("DELETE FROM media WHERE key=?", (key,))
        self.db.commit()

    # ── Recent videos in groups ──
    def earlier_post(self, chat_id: int, key: str) -> int | None:
        """Return the id of a recent message with the same media."""
        row = self.db.execute(
            "SELECT message_id, posted_at FROM recent "
            "WHERE chat_id=? AND key=?",
            (chat_id, key),
        ).fetchone()
        if row and time.time() - row["posted_at"] < RECENT_MAX_AGE:
            return row["message_id"]
        return None

    def remember_post(self, chat_id: int, key: str, message_id: int) -> None:
        """Save the message with some media as the latest one."""
        self.db.execute(
            "INSERT OR REPLACE INTO recent VALUES (?, ?, ?, ?)",
            (chat_id, key, message_id, int(time.time())),
        )
        self.db.execute(
            "DELETE FROM recent WHERE chat_id=? AND key NOT IN ("
            "SELECT key FROM recent WHERE chat_id=? "
            "ORDER BY posted_at DESC, rowid DESC LIMIT ?)",
            (chat_id, chat_id, RECENT_LIMIT),
        )
        self.db.commit()

    def move_recent(self, old_id: int, new_id: int) -> None:
        """Move the recent videos after a group became a supergroup.

        botkit moves the chat itself and its settings (/cleanup too).
        """
        self.db.execute(
            "UPDATE OR IGNORE recent SET chat_id=? WHERE chat_id=?",
            (new_id, old_id),
        )
        self.db.execute("DELETE FROM recent WHERE chat_id=?", (old_id,))
        self.db.commit()

    # ── Bans ──
    def ban_of(self, user_id: int | None) -> dict | None:
        """Return the ban of a user, or None if they aren't banned."""
        if user_id is None:
            return None
        row = self.db.execute(
            "SELECT * FROM bans WHERE user_id=?", (user_id,)
        ).fetchone()
        return dict(row) if row else None

    def ban(self, user_id: int, reason: str, kind: str = "abuse") -> None:
        """Put a user on the ban list.

        kind "request" is for users who asked the bot to stop
        processing their data: their settings are deleted too, and
        they can lift the ban themselves with /appeal.
        """
        self.db.execute(
            "INSERT OR REPLACE INTO bans (user_id, kind, reason, at) "
            "VALUES (?, ?, ?, ?)",
            (user_id, kind, reason, int(time.time())),
        )
        self.db.commit()
        if kind == "request":
            self.forget_chat(user_id)

    def update_ban(self, user_id: int, **fields) -> None:
        """Change fields of a ban: appealed or lang."""
        for name, value in fields.items():
            if name not in ("appealed", "lang"):
                raise ValueError(f"unknown ban field: {name}")
            self.db.execute(
                f"UPDATE bans SET {name}=? WHERE user_id=?", (value, user_id)
            )
        self.db.commit()

    def unban(self, user_id: int) -> bool:
        """Lift a ban; tell whether the user was banned."""
        cur = self.db.execute("DELETE FROM bans WHERE user_id=?", (user_id,))
        self.db.commit()
        return cur.rowcount > 0

    def bans(self, limit: int = 50) -> list[dict]:
        """Return the latest bans."""
        rows = self.db.execute(
            "SELECT * FROM bans ORDER BY at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Blocked posts ──
    def is_blocked(self, key: str) -> bool:
        """Tell whether a post is on the block list."""
        return (
            self.db.execute(
                "SELECT 1 FROM blocked WHERE key=?", (key,)
            ).fetchone()
            is not None
        )

    def block(self, key: str, reason: str) -> None:
        """Never download a post again."""
        self.db.execute(
            "INSERT OR REPLACE INTO blocked VALUES (?, ?, ?)",
            (key, reason, int(time.time())),
        )
        self.db.commit()

    def unblock(self, key: str) -> bool:
        """Allow a post again; tell whether it was blocked."""
        cur = self.db.execute("DELETE FROM blocked WHERE key=?", (key,))
        self.db.commit()
        return cur.rowcount > 0

    def blocked(self, limit: int = 50) -> list[dict]:
        """Return the latest blocked posts."""
        rows = self.db.execute(
            "SELECT * FROM blocked ORDER BY at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ── Who requested each upload ──
    def remember_upload(
        self, message_ids: list[int], user_id: int | None
    ) -> None:
        """Save who requested the media uploaded to the storage."""
        if not user_id:
            return
        now = int(time.time())
        self.db.executemany(
            "INSERT OR REPLACE INTO uploads VALUES (?, ?, ?)",
            [(m, user_id, now) for m in message_ids],
        )
        self.db.execute(
            "DELETE FROM uploads WHERE at < ?", (now - UPLOADS_MAX_AGE,)
        )
        self.db.commit()

    def uploader_of(self, message_id: int) -> int | None:
        """Return who requested a storage message, if still known."""
        row = self.db.execute(
            "SELECT user_id, at FROM uploads WHERE message_id=?",
            (message_id,),
        ).fetchone()
        if row and time.time() - row["at"] <= UPLOADS_MAX_AGE:
            return row["user_id"]
        return None

    # ── One-time import of the old JSON files ──
    def import_json(self, base: Path = BASE) -> None:
        """Import state.json and media_cache.json, once.

        The files are renamed to *.imported afterwards, so nothing is
        lost if something went wrong.
        """
        state_file = base / "state.json"
        if state_file.exists():
            try:
                self._import_state(json.loads(state_file.read_text("utf-8")))
            except Exception:
                log.exception("couldn't import %s", state_file)
            else:
                state_file.rename(state_file.with_suffix(".json.imported"))
                log.info("imported %s", state_file.name)
        cache_file = base / "media_cache.json"
        if cache_file.exists():
            try:
                data = json.loads(cache_file.read_text("utf-8"))
                now = int(time.time())
                for kind in ("videos", "albums"):
                    # Oldest first, so the newest get the latest time.
                    for i, (key, value) in enumerate(
                        data.get(kind, {}).items()
                    ):
                        self.db.execute(
                            "INSERT OR IGNORE INTO media VALUES (?, ?, ?, ?)",
                            (kind, key, json.dumps(value), now - 10**6 + i),
                        )
                self.db.commit()
            except Exception:
                log.exception("couldn't import %s", cache_file)
            else:
                cache_file.rename(cache_file.with_suffix(".json.imported"))
                log.info("imported %s", cache_file.name)

    def _import_state(self, state: dict) -> None:
        """Move the contents of the old state.json into the database."""
        now = int(time.time())

        def chat(chat_id: int, **fields) -> None:
            self.db.execute(
                "INSERT OR IGNORE INTO chats (chat_id, kind, seen_at) "
                "VALUES (?, ?, ?)",
                (chat_id, chat_kind(chat_id), now),
            )
            for name, value in fields.items():
                self.db.execute(
                    f"UPDATE chats SET {name}=? WHERE chat_id=?",
                    (value, chat_id),
                )

        bans = state.get("bans", {})
        for raw, lang in state.get("groups", {}).items():
            chat(int(raw), hint=lang)
        for raw, settings in state.get("chats", {}).items():
            fields = {}
            if settings.get("lang"):
                fields["lang"] = settings["lang"]
            if settings.get("notices") is False:
                fields["notices"] = 0
            chat(int(raw), **fields)
            if settings.get("cleanup"):
                self.db.execute(
                    "INSERT OR REPLACE INTO settings VALUES (?, ?)",
                    (f"cleanup:{raw}", settings["cleanup"]),
                )
        for raw, lang in state.get("known_users", {}).items():
            if raw not in bans:
                chat(int(raw), hint=lang)
        for raw, settings in state.get("users", {}).items():
            if raw not in bans and settings.get("lang"):
                chat(int(raw), lang=settings["lang"])
        for raw, posts in state.get("recent", {}).items():
            for key, (message_id, at) in posts.items():
                self.db.execute(
                    "INSERT OR REPLACE INTO recent VALUES (?, ?, ?, ?)",
                    (int(raw), key, message_id, at),
                )
        for raw, ban in bans.items():
            self.db.execute(
                "INSERT OR REPLACE INTO bans VALUES (?, ?, ?, ?, ?, ?)",
                (
                    int(raw),
                    ban.get("kind", "abuse"),
                    ban.get("reason", ""),
                    ban.get("at", now),
                    ban.get("appealed", 0),
                    ban.get("lang"),
                ),
            )
        for key, entry in state.get("blocked", {}).items():
            self.db.execute(
                "INSERT OR REPLACE INTO blocked VALUES (?, ?, ?)",
                (key, entry.get("reason", ""), entry.get("at", now)),
            )
        for raw, (user_id, at) in state.get("uploads", {}).items():
            self.db.execute(
                "INSERT OR REPLACE INTO uploads VALUES (?, ?, ?)",
                (int(raw), user_id, at),
            )
        notices = state.get("restart_notices", {})
        if notices:
            # The notices of the last run are deleted on the next start.
            self.db.execute(
                "INSERT OR REPLACE INTO settings VALUES (?, ?)",
                (
                    "kit:status",
                    json.dumps(
                        {
                            "kind": "reload",
                            "msgs": [[int(c), m] for c, m in notices.items()],
                        }
                    ),
                ),
            )
        self.db.commit()
