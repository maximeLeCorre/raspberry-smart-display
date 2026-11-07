"""Dernier message privé reçu (chat du client League), pour la notification
« Message de X » sur la montre (`conv` = conversation, pour y répondre). Seulement les messages privés (`chat`), pas les
salons de lobby/sélection, ni nos propres messages."""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote

from lcu import LcuClient

CONVERSATIONS_PATH = "/lol-chat/v1/conversations"
ME_PATH = "/lol-chat/v1/me"
MAX_BODY = 200


def _timestamp(value: str) -> float:
    """ISO 8601 de la LCU (« 2026-11-07T12:00:00.000Z ») → secondes ; 0 si illisible."""
    try:
        return datetime.fromisoformat((value or "").replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def build_last_message(lcu: LcuClient, since: float) -> dict | None:
    """Message privé non lu le plus récent, reçu après `since` (epoch s), sinon None.
    `since` évite de notifier au démarrage de l'agent un vieux message non lu."""
    me = (lcu.get_json(ME_PATH) or {}).get("id")
    best = None
    for conv in lcu.get_json(CONVERSATIONS_PATH) or []:
        msg = conv.get("lastMessage") or {}
        if (conv.get("type") != "chat" or not conv.get("unreadMessageCount")
                or not msg.get("id") or msg.get("fromId") == me or msg.get("isHistorical")):
            continue
        sent = _timestamp(msg.get("timestamp", ""))
        if sent < since or (best and sent <= best["t"]):
            continue
        best = {"id": str(msg["id"]), "t": sent, "conv": str(conv.get("id") or ""),
                "from": conv.get("gameName") or conv.get("name") or "?",
                "body": (msg.get("body") or "")[:MAX_BODY]}
    return best


def reply_path(conversation_id: str) -> str:
    """POST {"body", "type": "chat"} ici = message envoyé dans la conversation."""
    return f"{CONVERSATIONS_PATH}/{quote(conversation_id, safe='')}/messages"


def now() -> float:
    return datetime.now(timezone.utc).timestamp()
