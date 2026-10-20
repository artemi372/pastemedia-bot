"""Keep the shared bot state in SQLite (data/bot.db).

The bot's own storage class extends KitStore, so the bot and botkit
share one database file and one connection. KitStore keeps:

1. chats: every group and private chat the bot knows, with its
   language, whether it wants restart notices and whether the bot can
   still write there. Broadcasts and notices go to these chats.
2. settings: small key-value settings. Per-chat settings are named
   "<name>:<chat_id>", so they move along when a group becomes a
   supergroup.
3. deletions: the auto-deletion queue (what to delete and when). It
   lives in the database, so a restart doesn't forget anything.
"""

import sqlite3
import time
from pathlib import Path

KIT_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);
CREATE TABLE IF NOT EXISTS deletions (
    chat_id    INTEGER,
    message_id INTEGER,
    delete_at  INTEGER,
    PRIMARY KEY (chat_id, message_id)
);
CREATE TABLE IF NOT EXISTS chats (
    chat_id INTEGER PRIMARY KEY,
    kind    TEXT NOT NULL,       -- private, group or supergroup
    lang    TEXT,                -- chosen with /language; NULL if not
    hint    TEXT,                -- guessed from the Telegram app
    notices INTEGER DEFAULT 1,   -- restart and shutdown notices
    active  INTEGER DEFAULT 1,   -- 0: the bot was removed or blocked
    seen_at INTEGER
);
"""


def chat_kind(chat_id: int) -> str:
    """Guess the kind of a chat from its ID."""
    if chat_id > 0:
        return "private"
    return "supergroup" if chat_id <= -1_000_000_000_000 else "group"


class KitStore:
    """The database connection with the shared tables."""

    def __init__(self, path: Path):
        """Open the database and create the shared tables."""
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(KIT_SCHEMA)

    def _add_columns(self, table: str, columns: dict[str, str]) -> None:
        """Add columns that newer versions need to an old table."""
        have = {
            r["name"] for r in self.db.execute(f"PRAGMA table_info({table})")
        }
        for name, kind in columns.items():
            if name not in have:
                self.db.execute(
                    f"ALTER TABLE {table} ADD COLUMN {name} {kind}"
                )
        self.db.commit()

    # ── Settings ──
    def get_setting(self, key: str, default: str = "") -> str:
        """Return the value of a setting, or default."""
        row = self.db.execute(
            "SELECT value FROM settings WHERE key=?", (key,)
        ).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        """Set the value of a setting."""
        self.db.execute(
            "INSERT OR REPLACE INTO settings VALUES (?, ?)", (key, value)
        )
        self.db.commit()

    def del_setting(self, key: str) -> None:
        """Remove a setting."""
        self.db.execute("DELETE FROM settings WHERE key=?", (key,))
        self.db.commit()

    def settings_with_prefix(self, prefix: str) -> list[tuple[str, str]]:
        """Return all settings whose key starts with prefix."""
        escaped = (
            prefix.replace("\\", "\\\\")
            .replace("%", r"\%")
            .replace("_", r"\_")
        )
        rows = self.db.execute(
            "SELECT key, value FROM settings WHERE key LIKE ? ESCAPE '\\'",
            (escaped + "%",),
        ).fetchall()
        return [(r["key"], r["value"]) for r in rows]

    # ── Auto-deletion ──
    def schedule_delete(
        self, chat_id: int, message_id: int, delete_at: int
    ) -> None:
        """Schedule a message for deletion (or move its time)."""
        self.db.execute(
            "INSERT OR REPLACE INTO deletions VALUES (?, ?, ?)",
            (chat_id, message_id, delete_at),
        )
        self.db.commit()

    def due_deletions(self, now: int) -> list[tuple[int, int]]:
        """Return the messages whose deletion time has come."""
        rows = self.db.execute(
            "SELECT chat_id, message_id FROM deletions WHERE delete_at <= ?",
            (now,),
        ).fetchall()
        return [(r["chat_id"], r["message_id"]) for r in rows]

    def remove_deletion(self, chat_id: int, message_id: int) -> None:
        """Remove a message from the deletion queue."""
        self.db.execute(
            "DELETE FROM deletions WHERE chat_id=? AND message_id=?",
            (chat_id, message_id),
        )
        self.db.commit()

    def is_scheduled(self, chat_id: int, message_id: int) -> bool:
        """Return True if the message is queued for deletion."""
        return (
            self.db.execute(
                "SELECT 1 FROM deletions WHERE chat_id=? AND message_id=?",
                (chat_id, message_id),
            ).fetchone()
            is not None
        )

    # ── Chats ──
    def chat(self, chat_id: int) -> sqlite3.Row | None:
        """Return a known chat, or None."""
        return self.db.execute(
            "SELECT * FROM chats WHERE chat_id=?", (chat_id,)
        ).fetchone()

    def see_chat(
        self, chat_id: int, kind: str, hint: str | None = None
    ) -> None:
        """Remember a chat the bot got a message from.

        The chat becomes active again if the bot was blocked there. A
        private chat follows the user's app language; a group keeps the
        language of the first person seen there.
        """
        self.db.execute(
            "INSERT INTO chats (chat_id, kind, hint, seen_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(chat_id) DO UPDATE SET kind=excluded.kind, "
            "active=1, seen_at=excluded.seen_at, "
            "hint=CASE WHEN excluded.kind='private' "
            "THEN COALESCE(excluded.hint, hint) "
            "ELSE COALESCE(hint, excluded.hint) END",
            (chat_id, kind, hint, int(time.time())),
        )
        self.db.commit()

    def update_chat(self, chat_id: int, **fields) -> None:
        """Change fields of a chat: lang, notices or active.

        A chat the bot hasn't seen yet is added first.
        """
        self.db.execute(
            "INSERT OR IGNORE INTO chats (chat_id, kind, seen_at) "
            "VALUES (?, ?, ?)",
            (chat_id, chat_kind(chat_id), int(time.time())),
        )
        for name, value in fields.items():
            if name not in ("lang", "hint", "notices", "active", "kind"):
                raise ValueError(f"unknown chat field: {name}")
            self.db.execute(
                f"UPDATE chats SET {name}=? WHERE chat_id=?", (value, chat_id)
            )
        self.db.commit()

    def chats(self, active: bool = True) -> list[sqlite3.Row]:
        """Return the known chats: groups first, then private chats."""
        return self.db.execute(
            "SELECT * FROM chats WHERE active=? "
            "ORDER BY kind='private', chat_id",
            (int(active),),
        ).fetchall()

    def move_chat(self, old_id: int, new_id: int) -> bool:
        """Move a group's data to its new ID (it became a supergroup).

        Settings chosen in the new chat win. Messages waiting for
        deletion stay behind: the old chat can't be used any more.
        Return False if there was nothing to move.
        """
        old = self.chat(old_id)
        moved = old is not None
        if old is not None:
            self.update_chat(new_id, kind="supergroup")
            new = self.chat(new_id)
            for name in ("lang", "hint"):
                if new[name] is None and old[name] is not None:
                    self.update_chat(new_id, **{name: old[name]})
            if old["notices"] == 0:
                self.update_chat(new_id, notices=0)
            self.db.execute("DELETE FROM chats WHERE chat_id=?", (old_id,))
        suffix = f":{old_id}"
        for key, value in self.settings_with_prefix(""):
            if key.endswith(suffix):
                new_key = key[: -len(suffix)] + f":{new_id}"
                self.db.execute(
                    "INSERT OR IGNORE INTO settings VALUES (?, ?)",
                    (new_key, value),
                )
                self.db.execute("DELETE FROM settings WHERE key=?", (key,))
                moved = True
        self.db.execute("DELETE FROM deletions WHERE chat_id=?", (old_id,))
        self.db.commit()
        return moved

    def forget_chat(self, chat_id: int) -> None:
        """Delete everything botkit keeps about a chat."""
        self.db.execute("DELETE FROM chats WHERE chat_id=?", (chat_id,))
        self.db.execute(
            "DELETE FROM settings WHERE key LIKE ?", (f"%:{chat_id}",)
        )
        self.db.commit()
