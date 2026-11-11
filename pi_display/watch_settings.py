"""Settings made from the watch, kept on the Pi (`watch.db`): followed friends
(notifications) and the Play button (queue + invited friends). Stored as one
JSON row, rewritten on every change. Main-thread only.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "watch.db"
MAX_FOLLOWS = 30
MAX_INVITES = 4
FOLLOW_EVENTS = ("online", "leave", "enter")    # what can notify for a followed friend


def _clean_riot_id(value) -> str:
    text = str(value or "").strip()
    return text if 3 <= len(text) <= 40 and "#" in text else ""


def _clean_invite(value) -> str:
    """Riot ID, or a bare name (legacy `[lol] lobby_invite`)."""
    text = str(value or "").strip()
    return text if 0 < len(text) <= 40 else ""


class WatchSettings:
    def __init__(self, default_queue: int, default_invites: list[str], db_path: Path | None = None):
        self._db = sqlite3.connect(str(db_path or DB_PATH), check_same_thread=False)
        self._db.execute("CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT)")
        self._db.commit()
        self.follows: dict[str, dict] = {}       # lowercase riotId -> {riotId, online, leave, enter}
        self.queue_id = default_queue
        self.invites = [r for r in default_invites if r]
        row = self._db.execute("SELECT value FROM kv WHERE key = 'settings'").fetchone()
        if row:
            try:
                saved = json.loads(row[0])
            except ValueError:
                saved = {}
            self.follows = {k: v for k, v in (saved.get("follows") or {}).items() if isinstance(v, dict)}
            self.queue_id = int(saved.get("queueId") or default_queue)
            self.invites = [r for r in saved.get("invites") or [] if isinstance(r, str)]

    def _save(self) -> None:
        data = json.dumps({"follows": self.follows, "queueId": self.queue_id, "invites": self.invites})
        self._db.execute("INSERT OR REPLACE INTO kv VALUES ('settings', ?)", (data,))
        self._db.commit()

    def set_follow(self, riot_id, events: dict) -> bool:
        """Follows a friend (`events`: online/leave/enter -> bool); all False = unfollow."""
        rid = _clean_riot_id(riot_id)
        if not rid:
            return False
        flags = {e: bool(events.get(e)) for e in FOLLOW_EVENTS}
        key = rid.lower()
        if not any(flags.values()):
            self.follows.pop(key, None)
        elif key in self.follows or len(self.follows) < MAX_FOLLOWS:
            self.follows[key] = {"riotId": rid, **flags}
        else:
            return False
        self._save()
        return True

    def set_play(self, queue_id: int, invites) -> bool:
        clean = [_clean_invite(r) for r in invites or []]
        if any(not r for r in clean) or len(clean) > MAX_INVITES:
            return False
        self.queue_id, self.invites = int(queue_id), list(dict.fromkeys(clean))
        self._save()
        return True

    def resolve_invites(self, riot_ids: list[str]) -> None:
        """Upgrades bare-name invites to full Riot IDs once the friend is seen."""
        by_name = {r.split("#")[0].lower(): r for r in riot_ids if "#" in r}
        resolved = [by_name.get(i.lower(), i) if "#" not in i else i for i in self.invites]
        resolved = list(dict.fromkeys(resolved))
        if resolved != self.invites:
            self.invites = resolved
            self._save()

    def follow(self, riot_id: str) -> dict | None:
        return self.follows.get((riot_id or "").lower())
