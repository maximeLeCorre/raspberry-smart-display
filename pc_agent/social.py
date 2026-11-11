"""Friends and rewards read from the League client, for the watch.

Friends: `/lol-chat/v1/friends` -> connected friends with their game status
(`lol.gameStatus`: outOfGame, inGame, championSelect...) and its start time
(`lol.timeStamp`, ms).

Rewards: `/lol-rewards/v1/grants` in `PENDING_SELECTION` are claimed one by one
(`POST .../grants/{id}/select`); event passes (`/lol-event-hub`) only as a whole
(`claim-all`).
"""

from __future__ import annotations

import time

from chat import CONVERSATIONS_PATH, reply_path
from lcu import LcuClient
from lobby import FRIENDS_PATH

GRANTS_PATH = "/lol-rewards/v1/grants"
EVENTS_PATH = "/lol-event-hub/v1/events"
RECONNECT_PATH = "/lol-gameflow/v1/reconnect"
SEARCH_STATE_PATH = "/lol-lobby/v2/lobby/matchmaking/search-state"
REWARDS_TTL = 30.0
MAX_FRIENDS = 40
MAX_REWARDS = 20


def build_friends(lcu: LcuClient) -> list[dict]:
    """Connected friends (game client or mobile), sorted by name."""
    out = []
    for f in lcu.get_json(FRIENDS_PATH) or []:
        if not isinstance(f, dict):
            continue
        availability = (f.get("availability") or "").lower()
        if availability in ("", "offline"):
            continue
        lol = f.get("lol") or {}
        name = f.get("gameName") or f.get("name") or "?"
        try:
            since = int(lol.get("timeStamp") or 0) // 1000
        except (TypeError, ValueError):
            since = 0
        out.append({"name": name, "riotId": f"{name}#{f.get('gameTag') or ''}",
                    "summonerId": f.get("summonerId") or 0, "pid": f.get("pid") or f.get("id") or "",
                    "availability": availability, "gameStatus": lol.get("gameStatus") or "",
                    "gameMode": lol.get("gameMode") or "", "since": since})
    out.sort(key=lambda f: f["name"].lower())
    return out[:MAX_FRIENDS]


def send_message(lcu: LcuClient, pid: str, body: str) -> bool:
    """Private message. The LCU refuses it when no conversation is open with
    that friend yet: create it, then retry."""
    payload = {"body": body, "type": "chat"}
    if lcu.post(reply_path(pid), payload):
        return True
    lcu.post(CONVERSATIONS_PATH, {"id": pid, "type": "chat"})
    return lcu.post(reply_path(pid), payload)


def _grant(g: dict) -> dict | None:
    info, group = g.get("info") or {}, g.get("rewardGroup") or {}
    if info.get("status") != "PENDING_SELECTION" or not info.get("id"):
        return None
    options = [{"id": r.get("id", ""), "title": (r.get("localizations") or {}).get("title") or "?",
                "details": (r.get("localizations") or {}).get("details") or ""}
               for r in group.get("rewards") or [] if r.get("id")]
    if not options:
        return None
    limits = group.get("selectionStrategyConfig") or {}
    return {"grantId": info["id"], "rewardGroupId": group.get("id") or info.get("rewardGroupId", ""),
            "options": options, "max": max(1, int(limits.get("maxSelectionsAllowed") or 1))}


def build_rewards(lcu: LcuClient) -> dict:
    """{grants: [...], events: [{eventId, name, count}]}: what is waiting to be claimed."""
    grants = [x for x in (_grant(g) for g in lcu.get_json(GRANTS_PATH) or [] if isinstance(g, dict)) if x]
    events = []
    for e in lcu.get_json(EVENTS_PATH) or []:
        eid = (e or {}).get("eventId")
        if not eid:
            continue
        pending = lcu.get_json(f"{EVENTS_PATH}/{eid}/reward-track/unclaimed-rewards") or {}
        count = int(pending.get("rewardsCount") or 0)
        if count > 0:
            events.append({"eventId": eid, "count": count,
                           "name": (e.get("eventInfo") or {}).get("eventName") or "Événement"})
    return {"grants": grants[:MAX_REWARDS], "events": events}


def claim_grant(lcu: LcuClient, grant: dict, selections: list[str]) -> bool:
    # Request body not confirmed against a real claim yet.
    return lcu.post(f"{GRANTS_PATH}/{grant['grantId']}/select",
                    {"grantId": grant["grantId"], "rewardGroupId": grant["rewardGroupId"],
                     "selections": selections})


def claim_event(lcu: LcuClient, event_id: str) -> bool:
    return lcu.post(f"{EVENTS_PATH}/{event_id}/reward-track/claim-all")


def queue_penalty(lcu: LcuClient) -> int:
    """Seconds of queue penalty left (dodge, low priority queue), else 0."""
    state = lcu.get_json(SEARCH_STATE_PATH) or {}
    values = [e.get("penaltyTimeRemaining") for e in state.get("errors") or [] if isinstance(e, dict)]
    values.append((state.get("lowPriorityData") or {}).get("penaltyTimeRemaining"))
    return int(max([v for v in values if isinstance(v, (int, float))] + [0]))


class RewardsCache:
    """Rewards cost several LCU calls: re-read at most every `ttl` seconds
    (`invalidate` after a claim)."""

    def __init__(self, ttl: float = REWARDS_TTL):
        self.ttl = ttl
        self._value: dict | None = None
        self._at = 0.0

    def get(self, lcu: LcuClient) -> dict:
        if self._value is None or time.monotonic() - self._at >= self.ttl:
            self._value, self._at = build_rewards(lcu), time.monotonic()
        return self._value

    def invalidate(self) -> None:
        self._value = None


class StableDeadline:
    """Absolute deadline (epoch s) from a "N seconds left" value re-read every
    tick, kept while it drifts less than `slack` s: the payload does not change
    every second, so the watch is not woken for nothing."""

    def __init__(self, slack: float = 3.0):
        self.slack = slack
        self._value = 0

    def update(self, remaining: int, now: float | None = None) -> int:
        if remaining <= 0:
            self._value = 0
            return 0
        target = int((now or time.time()) + remaining)
        if abs(target - self._value) > self.slack:
            self._value = target
        return self._value
