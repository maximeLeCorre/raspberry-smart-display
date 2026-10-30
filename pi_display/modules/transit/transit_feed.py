"""Prochains trains d'une gare + info trafic, via l'API PRIM d'Île-de-France Mobilités.

Le Pi interroge lui-même PRIM (marche PC éteint), avec la clé ``IDFM_API_KEY``
du ``.env`` (hors Git, copiée par deploy). Même schéma que ``rss_feed`` : un
thread de fond rafraîchit ; l'écran lit un ``snapshot()`` thread-safe.

  - prochains passages : ``/stop-monitoring?MonitoringRef=STIF:StopArea:SP:<zda>:``
    (réponse SIRI Lite : ``Siri.ServiceDelivery.StopMonitoringDelivery[0]
    .MonitoredStopVisit[]``) toutes les ``refresh_seconds`` ;
  - info trafic de chaque ligne : ``/general-message?LineRef=STIF:Line::<id>:``
    (``…GeneralMessageDelivery[0].InfoMessage[]``, vide = rien à signaler)
    toutes les ``messages_minutes``.

Identifiants (open data IDFM, jeux « zones-d-arrets » / « referentiel-des-lignes ») :
Chaville Rive Droite = zone d'arrêt 43241, desservie par la L (C01740, Saint-Lazare ↔
Versailles RD) **et la U** (C01741, La Défense ↔ La Verrière).
Tolérant : en cas d'erreur, garde les dernières données et expose ``error``.

⚠️ **Quota PRIM : 1 000 requêtes/jour PAR endpoint** (compteurs séparés), remis à
zéro à minuit UTC. Une requête/min (1 440/j) l'épuise vers 17 h 40. Le rythme des
départs est donc **calé sur le quota** : chaque réponse donne le reste du jour
(``x-ratelimit-remaining-day``) et le délai avant remise à zéro (``ratelimit-reset``),
d'où un intervalle = temps restant / requêtes restantes (jamais sous
``refresh_seconds``), en gardant une réserve (redémarrages). La nuit
(``night_hours``), un relevé toutes les ``night_refresh_minutes``. Sur un 429, plus
aucune requête jusqu'à la remise à zéro (``retry-after``).
"""

from __future__ import annotations

import html
import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime

BASE_URL = "https://prim.iledefrance-mobilites.fr/marketplace"
STOP_PATH, MSG_PATH = "stop-monitoring", "general-message"
QUOTA_RESERVE = 40          # requêtes gardées pour les redémarrages / imprévus
MAX_INTERVAL = 900.0        # jamais plus de 15 min sans relevé (hors quota épuisé)
_TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class Departure:
    when: float           # départ attendu (epoch) ; théorique si pas de temps réel
    aimed: float | None   # départ théorique (epoch)
    destination: str
    mission: str          # code mission SNCF (ex. « PEBU »), vide si absent
    platform: str         # voie, vide si inconnue
    status: str           # onTime / delayed / cancelled / early / noReport…
    at_stop: bool         # train à quai
    to_paris: bool
    line: str = ""        # lettre de la ligne (« L », « U »), via [transit.lines]
    arrival: float | None = None   # arrivée en gare attendue (epoch), si connue

    @property
    def cancelled(self) -> bool:
        return self.status == "cancelled"

    @property
    def delay_min(self) -> int:
        """Retard en minutes (0 si à l'heure ou inconnu)."""
        if self.aimed is None:
            return 0
        return max(0, round((self.when - self.aimed) / 60))


@dataclass(frozen=True)
class TrafficMessage:
    channel: str          # « Perturbation », « Information », « Commercial »…
    text: str
    line: str = ""        # lettre de la ligne concernée

    @property
    def is_disruption(self) -> bool:
        return self.channel.lower().startswith("perturbation")


def _value(obj) -> str:
    """SIRI Lite : ``{"value": x}`` ou liste ``[{"value": x}]`` -> x (ou '')."""
    if isinstance(obj, list):
        obj = obj[0] if obj else None
    if isinstance(obj, dict):
        return str(obj.get("value") or "").strip()
    return str(obj or "").strip()


def _epoch(stamp: str | None) -> float | None:
    if not stamp:
        return None
    try:
        return datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _clean(text: str) -> str:
    text = html.unescape(_TAG_RE.sub(" ", text))
    for ch in (" ", " ", " "):
        text = text.replace(ch, " ")
    return " ".join(text.split())


def line_id(ref: str) -> str:
    """« STIF:Line::C01740: » -> « C01740 »."""
    return ref.strip(":").rsplit(":", 1)[-1] if ref else ""


def parse_departures(data: dict, paris_words: tuple[str, ...],
                     lines: dict[str, str] | None = None) -> list[Departure]:
    """Réponse stop-monitoring -> départs triés (ceux sans horaire sont ignorés).
    ``lines`` : id IDFM -> lettre affichée (id brut si absent)."""
    lines = lines or {}
    deliveries = (data.get("Siri", {}).get("ServiceDelivery", {})
                  .get("StopMonitoringDelivery") or [])
    out: list[Departure] = []
    for visit in (deliveries[0].get("MonitoredStopVisit") or []) if deliveries else []:
        mvj = visit.get("MonitoredVehicleJourney") or {}
        call = mvj.get("MonitoredCall") or {}
        aimed = _epoch(call.get("AimedDepartureTime"))
        when = _epoch(call.get("ExpectedDepartureTime")) or aimed
        if when is None:
            continue              # terminus d'arrivée : pas de départ
        dest = (_value(mvj.get("DestinationName")) or _value(call.get("DestinationDisplay"))
                or "?")
        low = dest.lower()
        out.append(Departure(
            when=when,
            aimed=aimed,
            destination=dest,
            mission=_value(mvj.get("JourneyNote")),
            platform=(_value(call.get("DeparturePlatformName"))
                      or _value(call.get("ArrivalPlatformName"))),
            status=str(call.get("DepartureStatus") or ""),
            at_stop=bool(call.get("VehicleAtStop")),
            to_paris=any(w in low for w in paris_words),
            line=lines.get(line_id(_value(mvj.get("LineRef"))), ""),
            arrival=(_epoch(call.get("ExpectedArrivalTime"))
                     or _epoch(call.get("AimedArrivalTime"))),
        ))
    out.sort(key=lambda d: d.when)
    return out


def parse_messages(data: dict, line: str = "") -> list[TrafficMessage]:
    """Réponse general-message -> messages (perturbations d'abord), sans doublon."""
    deliveries = (data.get("Siri", {}).get("ServiceDelivery", {})
                  .get("GeneralMessageDelivery") or [])
    out: list[TrafficMessage] = []
    seen = set()
    for info in (deliveries[0].get("InfoMessage") or []) if deliveries else []:
        texts = []
        for msg in (info.get("Content") or {}).get("Message") or []:
            raw = _value(msg.get("MessageText"))
            if raw:
                texts.append((msg.get("MessageType") == "SHORT_MESSAGE", _clean(raw)))
        if not texts:
            continue
        # Le texte le plus complet (les messages courts ne servent qu'à défaut).
        text = max(texts, key=lambda t: (not t[0], len(t[1])))[1]
        if text in seen:
            continue
        seen.add(text)
        out.append(TrafficMessage(_value(info.get("InfoChannelRef")) or "Information",
                                  text, line))
    out.sort(key=lambda m: not m.is_disruption)
    return out


class TransitFeed:
    """Rafraîchit départs + info trafic en arrière-plan."""

    def __init__(self, api_key: str, *, stop_area: str, lines: dict[str, str],
                 paris_words: tuple[str, ...], refresh_seconds: float = 60.0,
                 messages_minutes: float = 5.0, timeout: float = 15.0,
                 night_hours: tuple[int, int] = (1, 5), night_refresh_minutes: float = 15.0):
        self.api_key = api_key
        self.stop_ref = f"STIF:StopArea:SP:{stop_area}:"
        self.lines = dict(lines)      # id IDFM -> lettre
        self.paris_words = tuple(w.lower() for w in paris_words)
        self.refresh_seconds = max(30.0, refresh_seconds)
        self.messages_seconds = max(60.0, messages_minutes * 60)
        self.night_hours = (int(night_hours[0]), int(night_hours[1]))
        self.night_seconds = max(self.refresh_seconds, night_refresh_minutes * 60)
        self.timeout = timeout
        # Par endpoint : (requêtes restantes du jour, epoch de remise à zéro), et
        # epoch avant lequel on ne requête plus (429 reçu).
        self._quota: dict[str, tuple[int, float]] = {}
        self._blocked_until: dict[str, float] = {}
        self._lock = threading.Lock()
        self._departures: list[Departure] = []
        self._messages: list[TrafficMessage] = []
        self._updated = 0.0          # epoch du dernier relevé réussi des départs
        self._error = ""
        self._msg_ts = 0.0
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def snapshot(self) -> dict:
        """Départs encore à venir (30 s de marge), messages, fraîcheur, erreur."""
        now = time.time()
        with self._lock:
            return {
                "departures": [d for d in self._departures if d.when >= now - 30],
                "messages": list(self._messages),
                "updated": self._updated,
                "error": self._error,
            }

    # ----------------------------------------------------------------- interne
    def _get(self, path: str, params: dict) -> dict:
        url = f"{BASE_URL}/{path}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"apikey": self.api_key,
                                                   "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                self._note_quota(path, resp.headers)
                return json.load(resp)
        except urllib.error.HTTPError as exc:
            self._note_quota(path, exc.headers)
            if exc.code == 429:
                wait = _to_float(exc.headers.get("retry-after")) or 3600.0
                self._blocked_until[path] = time.time() + wait
            raise

    def _note_quota(self, path: str, headers) -> None:
        """Mémorise le quota restant du jour d'après les en-têtes PRIM."""
        if headers is None:
            return
        remaining = _to_float(headers.get("x-ratelimit-remaining-day"))
        reset = _to_float(headers.get("ratelimit-reset"))
        if remaining is not None and reset is not None:
            self._quota[path] = (int(remaining), time.time() + reset)

    def _blocked(self, path: str, now: float) -> bool:
        return self._blocked_until.get(path, 0.0) > now

    def _is_night(self, now: float) -> bool:
        start, end = self.night_hours
        hour = time.localtime(now).tm_hour
        return start <= hour < end if start <= end else (hour >= start or hour < end)

    def next_delay(self, now: float | None = None) -> float:
        """Attente avant le prochain relevé des départs (voir docstring du module)."""
        now = time.time() if now is None else now
        until = self._blocked_until.get(STOP_PATH, 0.0)
        if until > now:                          # 429 : attendre la remise à zéro
            return until - now + 5
        if self._is_night(now):
            return self.night_seconds
        quota = self._quota.get(STOP_PATH)
        if quota is None:
            return self.refresh_seconds
        remaining, reset_at = quota
        horizon = max(0.0, reset_at - now)
        budget = remaining - QUOTA_RESERVE
        if budget <= 0:                          # on garde la réserve : on attend
            return horizon + 5
        return min(MAX_INTERVAL, max(self.refresh_seconds, horizon / budget))

    def _loop(self) -> None:
        while True:
            self._poll()
            time.sleep(self.next_delay())

    def _poll(self) -> None:
        now = time.time()
        if not self._blocked(STOP_PATH, now):
            try:
                deps = parse_departures(self._get(STOP_PATH, {"MonitoringRef": self.stop_ref}),
                                        self.paris_words, self.lines)
                with self._lock:
                    self._departures, self._updated, self._error = deps, time.time(), ""
            except urllib.error.HTTPError as exc:
                if exc.code == 429:
                    label = "quota du jour atteint, reprise à " + time.strftime(
                        "%H:%M", time.localtime(self._blocked_until[STOP_PATH]))
                elif exc.code in (401, 403):
                    label = "clé API refusée"
                else:
                    label = f"erreur {exc.code}"
                self._fail(label, exc)
            except Exception as exc:  # réseau, parse… : on ne casse jamais l'UI
                self._fail("réseau indisponible", exc)
        if (self.lines and not self._blocked(MSG_PATH, now)
                and time.time() - self._msg_ts >= self.messages_seconds):
            try:
                msgs = []
                for lid, name in self.lines.items():
                    msgs += parse_messages(self._get(
                        MSG_PATH, {"LineRef": f"STIF:Line::{lid}:"}), name)
                msgs.sort(key=lambda m: not m.is_disruption)
                with self._lock:
                    self._messages = msgs
                self._msg_ts = time.time()
            except Exception as exc:
                print(f"[trains] échec de l'info trafic : {exc}")

    def _fail(self, label: str, exc: Exception) -> None:
        print(f"[trains] échec des prochains passages : {exc}")
        with self._lock:
            self._error = label


def _to_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def get_transit(app):
    """Instance unique pour l'app (config ``[transit]``) ; None sans clé."""
    if not hasattr(app, "_transit_feed"):
        from config import load_idfm_key
        cfg = app.config.get("transit", {})
        key = load_idfm_key()
        feed = None
        if key and cfg.get("stop_area"):
            feed = TransitFeed(
                key,
                stop_area=str(cfg["stop_area"]),
                lines={str(k): str(v) for k, v in (cfg.get("lines") or {}).items()},
                paris_words=tuple(cfg.get("paris_destinations", ["saint-lazare"])),
                refresh_seconds=float(cfg.get("refresh_seconds", 60)),
                messages_minutes=float(cfg.get("messages_minutes", 5)),
                night_hours=tuple(cfg.get("night_hours", (1, 5))),
                night_refresh_minutes=float(cfg.get("night_refresh_minutes", 15)),
            )
            feed.start()
        app._transit_feed = feed
    return app._transit_feed
