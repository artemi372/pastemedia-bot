"""Test the bot's database: the media cache, bans, the JSON import."""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import storage  # noqa: E402
from storage import Storage  # noqa: E402


def test_media_cache_keeps_the_newest(tmp_path, monkeypatch):
    """The cache is limited; the oldest entries go first."""
    monkeypatch.setattr(storage, "MEDIA_LIMIT", 2)
    db = Storage(tmp_path / "bot.db")
    for i in range(3):
        db.media_put("videos", f"k{i}", f"file{i}")
    assert db.media_get("videos", "k0") is None
    assert db.media_get("videos", "k2") == "file2"
    db.media_put("albums", "a", [["photo", "p1"], ["video", "v1"]])
    assert db.media_get("albums", "a") == [["photo", "p1"], ["video", "v1"]]
    db.media_drop("a")
    assert db.media_get("albums", "a") is None


def test_recent_posts(tmp_path, monkeypatch):
    """A repeated link finds the earlier video; supergroups keep it."""
    monkeypatch.setattr(storage, "RECENT_LIMIT", 2)
    db = Storage(tmp_path / "bot.db")
    for i in range(3):
        db.remember_post(-5, f"0:k{i}", 100 + i)
    assert db.earlier_post(-5, "0:k0") is None
    assert db.earlier_post(-5, "0:k2") == 102
    db.move_recent(-5, -1001)
    assert db.earlier_post(-1001, "0:k2") == 102


def test_bans(tmp_path):
    """A ban the user asked for also deletes their settings."""
    db = Storage(tmp_path / "bot.db")
    db.update_chat(42, lang="ru")
    db.set_setting("x:42", "1")
    db.ban(42, "request: privacy", "request")
    assert db.ban_of(42)["kind"] == "request"
    assert db.chat(42) is None and db.get_setting("x:42") == ""
    db.update_ban(42, appealed=5, lang="ru")
    assert db.ban_of(42)["appealed"] == 5
    assert db.unban(42) and not db.unban(42)
    db.block("tiktok:1", "spam")
    assert db.is_blocked("tiktok:1") and db.blocked()[0]["key"] == "tiktok:1"
    assert db.unblock("tiktok:1") and not db.is_blocked("tiktok:1")


def test_warnings(tmp_path):
    """Warnings add up, can be taken back and go away on unban."""
    db = Storage(tmp_path / "bot.db")
    assert db.add_warning(42, "spam", message_id=7)
    # The same rule for the same media is one warning, not two.
    assert not db.add_warning(42, "spam", message_id=7)
    assert db.add_warning(42, "copyright", message_id=7)
    assert db.add_warning(42, "other", "rude comment")
    assert [w["rule"] for w in db.warnings(42)] == [
        "spam",
        "copyright",
        "other",
    ]
    assert db.warned()[0]["count"] == 3
    assert db.drop_last_warning(42)["note"] == "rude comment"
    assert len(db.warnings(42)) == 2
    db.ban(42, "warnings", "warnings")
    # Warnings stay while banned (the ban message lists them)...
    assert len(db.warnings(42)) == 2
    db.unban(42)
    # ...and an unbanned user starts from zero.
    assert db.warnings(42) == [] and db.drop_last_warning(42) is None


def test_warnings_expire(tmp_path, monkeypatch):
    """Warnings go after 90 days, but not those that led to a ban."""
    db = Storage(tmp_path / "bot.db")
    db.add_warning(1, "spam")
    db.add_warning(2, "spam")
    db.ban(2, "warnings", "warnings")
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now + 91 * 24 * 60 * 60)
    db.add_warning(1, "hate")
    assert [w["rule"] for w in db.warnings(1)] == ["hate"]
    assert len(db.warnings(2)) == 1


def test_uploads_expire(tmp_path, monkeypatch):
    """Who requested an upload is known for a week only."""
    db = Storage(tmp_path / "bot.db")
    db.remember_upload([1, 2], 42)
    assert db.uploader_of(2) == 42
    monkeypatch.setattr(storage, "UPLOADS_MAX_AGE", -1)
    assert db.uploader_of(2) is None


def test_import_json(tmp_path):
    """state.json and media_cache.json move into the database once."""
    now = int(time.time())
    state = {
        "users": {"42": {"lang": "et"}, "13": {"lang": "ru"}},
        "known_users": {"42": "et", "77": "ru", "13": "ru"},
        "chats": {
            "-1001": {"lang": "ru", "notices": False, "cleanup": "user"}
        },
        "groups": {"-1001": "en", "-5": "et"},
        "restart_notices": {"-1001": 55},
        "recent": {"-1001": {"0:tiktok:1": [9, now]}},
        "moved": {},
        "bans": {"13": {"kind": "abuse", "reason": "spam", "at": now}},
        "blocked": {"tiktok:2": {"reason": "", "at": now}},
        "uploads": {"300": [42, now]},
    }
    (tmp_path / "state.json").write_text(json.dumps(state), "utf-8")
    cache = {
        "videos": {"tiktok:1": "F1"},
        "albums": {"ig:1": [["photo", "P"]]},
    }
    (tmp_path / "media_cache.json").write_text(json.dumps(cache), "utf-8")
    db = Storage(tmp_path / "data" / "bot.db")
    db.import_json(tmp_path)

    assert db.chat(42)["lang"] == "et" and db.chat(77)["hint"] == "ru"
    assert db.chat(13) is None  # banned users aren't kept
    group = db.chat(-1001)
    assert group["lang"] == "ru" and group["notices"] == 0
    assert group["hint"] == "en" and db.chat(-5)["hint"] == "et"
    assert db.get_setting("cleanup:-1001") == "user"
    assert db.earlier_post(-1001, "0:tiktok:1") == 9
    assert db.ban_of(13)["reason"] == "spam"
    assert db.is_blocked("tiktok:2") and db.uploader_of(300) == 42
    assert db.media_get("videos", "tiktok:1") == "F1"
    assert db.media_get("albums", "ig:1") == [["photo", "P"]]
    status = json.loads(db.get_setting("kit:status"))
    assert status == {"kind": "reload", "msgs": [[-1001, 55]]}
    assert not (tmp_path / "state.json").exists()
    assert (tmp_path / "state.json.imported").exists()
    assert (tmp_path / "media_cache.json.imported").exists()
