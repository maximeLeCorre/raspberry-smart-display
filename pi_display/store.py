"""Stockage local des parties sur le Pi (SQLite).

But : garder l'historique **consultable PC éteint**. Toutes les parties viennent
de la LCU (via l'agent) et sont stockées ici ; l'écran historique lit cette base
(local, instantané, hors-ligne). Le détail complet (10 joueurs) est conservé en
JSON pour afficher le bilan sans re-fetch.

Table `participations` : une ligne par (partie, joueur) tirée des bilans 10
joueurs — de NOS parties et de celles d'un ami suivi (`[lol] compare`). Elle
permet de comparer « moi seul », « l'ami seul » et « nous deux, même équipe ».

Table `timelines` : courbes d'une partie (1 point/minute : or total exact, CS,
niveau, kills des 10 joueurs), tirées de la LCU après la partie (~6 Ko).

Thread-safe (un verrou) car les écritures arrivent depuis la boucle réseau et les
lectures depuis la boucle de rendu.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "matches.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    game_id       TEXT PRIMARY KEY,
    game_creation INTEGER,
    game_mode     TEXT,
    queue_id      INTEGER,
    queue_label   TEXT,
    duration      INTEGER,
    win           INTEGER,
    champion_id   INTEGER,
    champion_name TEXT,
    kills         INTEGER,
    deaths        INTEGER,
    assists       INTEGER,
    cs            INTEGER,
    detail_json   TEXT
);
CREATE INDEX IF NOT EXISTS idx_creation ON matches(game_creation DESC);
CREATE INDEX IF NOT EXISTS idx_mode ON matches(game_mode);
CREATE INDEX IF NOT EXISTS idx_queue ON matches(queue_id);
CREATE TABLE IF NOT EXISTS participations (
    game_id       TEXT,
    riot_key      TEXT,
    team          INTEGER,
    win           INTEGER,
    champion_id   INTEGER,
    champion_name TEXT,
    kills         INTEGER,
    deaths        INTEGER,
    assists       INTEGER,
    cs            INTEGER,
    dmg           INTEGER,
    gold          INTEGER,
    duration      INTEGER,
    game_mode     TEXT,
    queue_id      INTEGER,
    game_creation INTEGER,
    PRIMARY KEY (game_id, riot_key)
);
CREATE INDEX IF NOT EXISTS idx_part_key ON participations(riot_key);
CREATE TABLE IF NOT EXISTS timelines (
    game_id       TEXT PRIMARY KEY,
    timeline_json TEXT
);
"""

# Agrégats d'un groupe de participations (alias `p`).
_AGG = ("COUNT(*), SUM(win), SUM(kills), SUM(deaths), SUM(assists), SUM(dmg), "
        "SUM(gold), SUM(cs), SUM(duration)")


def riot_key(riot_id: str | None) -> str:
    """Clé joueur normalisée 'nom#tag' (minuscules) ; '' si pas de tag."""
    if not riot_id or "#" not in riot_id:
        return ""
    name, tag = riot_id.split("#", 1)
    return f"{name.strip().lower()}#{tag.strip().lower()}"


def _participation_rows(rec: dict) -> list[tuple]:
    """Lignes `participations` d'un enregistrement (résumé + bilan 10 joueurs).

    Victoire par joueur : champ `win` s'il existe ; sinon (bilans anciens)
    déduite de notre équipe (même équipe que `isSelf` = notre résultat)."""
    detail = rec.get("detail") or {}
    players = [p for p in (detail.get("players") or []) if isinstance(p, dict)]
    me = next((p for p in players if p.get("isSelf")), None)
    rows = []
    for p in players:
        key = riot_key(p.get("riotId"))
        if not key:
            continue
        if "win" in p:
            win = bool(p["win"])
        elif me is not None:
            win = bool(detail.get("win")) == (p.get("team") == me.get("team"))
        else:
            continue
        k, d, a = (p.get("kda") or [0, 0, 0])[:3]
        m = p.get("metrics") or {}
        rows.append((str(rec.get("gameId")), key, p.get("team", 0) or 0, 1 if win else 0,
                     p.get("championId", 0) or 0, p.get("championName", "") or "",
                     k, d, a, m.get("cs", 0) or 0, m.get("dmg", 0) or 0, m.get("gold", 0) or 0,
                     rec.get("duration", 0) or 0, rec.get("gameMode", "") or "",
                     rec.get("queueId", 0) or 0, rec.get("gameCreation", 0) or 0))
    return rows


def _agg(row) -> dict:
    n, wins, k, d, a, dmg, gold, cs, dur = (x or 0 for x in row)
    minutes = dur / 60 if dur else 0
    return {
        "games": n, "wins": wins,
        "winrate": round(100 * wins / n) if n else None,
        "kda": [round(k / n, 1), round(d / n, 1), round(a / n, 1)] if n else None,
        "kda_ratio": round((k + a) / max(1, d), 2) if n else None,
        "dmg_min": round(dmg / minutes) if minutes else None,
        "gold_min": round(gold / minutes) if minutes else None,
        "cs_min": round(cs / minutes, 1) if minutes else None,
    }


def _when(ms) -> str:
    try:
        return time.strftime("%d/%m %H:%M", time.localtime((ms or 0) / 1000))
    except (TypeError, ValueError, OSError):
        return ""


class Store:
    def __init__(self, path: Path = DB_PATH):
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self._backfill_participations()

    def _backfill_participations(self) -> None:
        """1re exécution après ajout de la table : la remplit depuis les bilans
        déjà stockés (nos parties d'avant la mise à jour)."""
        with self._lock:
            if self._conn.execute("SELECT 1 FROM participations LIMIT 1").fetchone():
                return
            rows = self._conn.execute(
                "SELECT game_id, game_mode, queue_id, duration, game_creation, detail_json "
                "FROM matches WHERE detail_json != ''").fetchall()
            for gid, mode, qid, dur, created, raw in rows:
                try:
                    detail = json.loads(raw)
                except ValueError:
                    continue
                rec = {"gameId": gid, "gameMode": mode, "queueId": qid, "duration": dur,
                       "gameCreation": created, "detail": detail}
                self._insert_participations(_participation_rows(rec))
            self._conn.commit()

    def _insert_participations(self, rows: list[tuple]) -> int:
        """(Verrou déjà pris.) Insère en ignorant les doublons ; renvoie le nombre ajouté."""
        n = 0
        for row in rows:
            n += self._conn.execute(
                "INSERT OR IGNORE INTO participations VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", row).rowcount
        return n

    # ------------------------------------------------------------ écriture
    def upsert_matches(self, records: list[dict]) -> int:
        """Insère des parties (ignore les doublons par game_id). Renvoie le
        nombre de nouvelles lignes."""
        new = 0
        with self._lock:
            for r in records:
                kda = r.get("kda") or [0, 0, 0]
                detail = r.get("detail")
                cur = self._conn.execute(
                    "INSERT OR IGNORE INTO matches VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (str(r.get("gameId")), r.get("gameCreation", 0) or 0,
                     r.get("gameMode", "") or "", r.get("queueId", 0) or 0,
                     r.get("queue", "") or "", r.get("duration", 0) or 0,
                     1 if r.get("win") else 0, r.get("championId", 0) or 0,
                     r.get("championName", "") or "",
                     kda[0], kda[1], kda[2], r.get("cs", 0) or 0,
                     json.dumps(detail, ensure_ascii=False) if detail else ""))
                new += cur.rowcount
                self._insert_participations(_participation_rows(r))
            self._conn.commit()
        return new

    def upsert_player_games(self, records: list[dict]) -> int:
        """Parties d'un AMI suivi : seulement ses participations (et celles des
        9 autres), pas dans l'historique affiché. Renvoie les lignes ajoutées."""
        with self._lock:
            n = sum(self._insert_participations(_participation_rows(r)) for r in records)
            self._conn.commit()
        return n

    def set_detail(self, game_id, detail: dict) -> None:
        """Mémorise le bilan complet d'une partie (récupéré à la demande)."""
        with self._lock:
            self._conn.execute("UPDATE matches SET detail_json = ? WHERE game_id = ?",
                               (json.dumps(detail or {}, ensure_ascii=False), str(game_id)))
            self._conn.commit()

    # ------------------------------------------------------------ lecture
    def newest_id(self) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT game_id FROM matches ORDER BY game_creation DESC LIMIT 1").fetchone()
        return row[0] if row else None

    def fill_champion_names(self, name_of) -> int:
        """Complète les noms de champion vides depuis leur id (`name_of(id)`, ex.
        `Champions.name`) : résumés, participations et bilans 10 joueurs. Arrive
        quand l'agent n'avait pas sa table de noms (démarré avant le réseau).
        `name_of` peut faire du réseau : appelé hors verrou. Renvoie le nb de lignes."""
        empty = "(champion_name IS NULL OR champion_name = '')"
        with self._lock:
            ids = {r[0] for t in ("participations", "matches") for r in self._conn.execute(
                f"SELECT DISTINCT champion_id FROM {t} WHERE {empty} AND champion_id > 0")}
            details = self._conn.execute(
                "SELECT game_id, detail_json FROM matches WHERE detail_json LIKE ?",
                ('%"championName": ""%',)).fetchall()
        for _gid, raw in details:
            try:
                ids |= {p.get("championId") for p in json.loads(raw).get("players", [])
                        if not p.get("championName") and p.get("championId")}
            except (ValueError, AttributeError):
                pass
        names = {cid: name_of(cid) for cid in ids}
        names = {cid: n for cid, n in names.items() if n}
        if not names:
            return 0
        changed = 0
        with self._lock:
            for table in ("participations", "matches"):
                for cid, n in names.items():
                    changed += self._conn.execute(
                        f"UPDATE {table} SET champion_name = ? WHERE champion_id = ? AND {empty}",
                        (n, cid)).rowcount
            for gid, raw in details:
                try:
                    detail = json.loads(raw)
                except ValueError:
                    continue
                for p in detail.get("players", []):
                    if not p.get("championName") and names.get(p.get("championId")):
                        p["championName"] = names[p["championId"]]
                self._conn.execute("UPDATE matches SET detail_json = ? WHERE game_id = ?",
                                   (json.dumps(detail, ensure_ascii=False), gid))
            self._conn.commit()
        return changed

    def oldest_creation(self) -> int | None:
        """Date (ms) de la plus ancienne de nos parties stockées, ou None."""
        with self._lock:
            row = self._conn.execute(
                "SELECT MIN(game_creation) FROM matches WHERE game_creation > 0").fetchone()
        return row[0] if row else None

    def total(self) -> int:
        with self._lock:
            return self._conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0]

    def query(self, where_sql: str = "", params: tuple = (),
              limit: int = 10, offset: int = 0) -> list[dict]:
        """Lignes de liste (résumé) pour l'écran, triées récent→ancien."""
        sql = ("SELECT game_id, champion_id, champion_name, win, kills, deaths, "
               "assists, cs, queue_label, duration, game_creation FROM matches")
        if where_sql:
            sql += " WHERE " + where_sql
        sql += " ORDER BY game_creation DESC LIMIT ? OFFSET ?"
        with self._lock:
            rows = self._conn.execute(sql, (*params, limit, offset)).fetchall()
        return [{
            "gameId": r[0], "championId": r[1], "championName": r[2],
            "win": bool(r[3]), "kda": [r[4], r[5], r[6]], "cs": r[7],
            "queue": r[8], "duration": r[9], "when": _when(r[10]),
        } for r in rows]

    def known_games(self, riot_id: str, limit: int = 300) -> list[str]:
        """Ids des parties (récentes) où ce joueur apparaît déjà."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT game_id FROM participations WHERE riot_key = ? "
                "ORDER BY game_creation DESC LIMIT ?", (riot_key(riot_id), limit)).fetchall()
        return [r[0] for r in rows]

    def compare(self, me: str, other: str, where_sql: str = "", params: tuple = ()) -> dict:
        """Stats comparées : moi seul, l'autre seul, et nous deux (même équipe).

        « Seul » = parties sans l'autre DANS SON ÉQUIPE. En duo, chacun a ses
        propres stats (`duo_me` / `duo_other`) ; la victoire est commune."""
        me_k, ot_k = riot_key(me), riot_key(other)
        extra = f" AND ({where_sql})" if where_sql else ""
        groups = {
            "me_solo": (me_k, ot_k, "NOT EXISTS"),
            "other_solo": (ot_k, me_k, "NOT EXISTS"),
            "duo_me": (me_k, ot_k, "EXISTS"),
            "duo_other": (ot_k, me_k, "EXISTS"),
        }
        out: dict = {"top": {}}
        with self._lock:
            for name, (who, mate, exists) in groups.items():
                base = (f"FROM participations p WHERE p.riot_key = ? AND {exists} "
                        "(SELECT 1 FROM participations o WHERE o.game_id = p.game_id "
                        "AND o.riot_key = ? AND o.team = p.team)" + extra)
                args = (who, mate, *params)
                out[name] = _agg(self._conn.execute(f"SELECT {_AGG} {base}", args).fetchone())
                out["top"][name] = [
                    {"championId": r[0], "championName": r[1], "games": r[2],
                     "winrate": round(100 * r[3] / r[2])}
                    for r in self._conn.execute(
                        f"SELECT champion_id, champion_name, COUNT(*), SUM(win) {base} "
                        "GROUP BY champion_id "
                        "ORDER BY COUNT(*) DESC, SUM(win) * 1.0 / COUNT(*) DESC LIMIT 3",
                        args).fetchall()]
        return out

    def set_timeline(self, game_id, timeline: dict) -> None:
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO timelines VALUES (?, ?)",
                               (str(game_id), json.dumps(timeline, ensure_ascii=False)))
            self._conn.commit()

    def timeline(self, game_id) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT timeline_json FROM timelines WHERE game_id = ?",
                                     (str(game_id),)).fetchone()
        try:
            return json.loads(row[0]) if row and row[0] else None
        except ValueError:
            return None

    def without_timeline(self, game_ids) -> list[str]:
        """Parmi ces parties (stockées), celles dont on n'a pas encore les courbes."""
        ids = [str(g) for g in game_ids if g]
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        with self._lock:
            have = {r[0] for r in self._conn.execute(
                f"SELECT game_id FROM timelines WHERE game_id IN ({marks})", ids)}
        return [g for g in ids if g not in have]

    def detail(self, game_id) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT detail_json FROM matches WHERE game_id = ?",
                (str(game_id),)).fetchone()
        if not row or not row[0]:
            return None
        try:
            return json.loads(row[0])
        except ValueError:
            return None
