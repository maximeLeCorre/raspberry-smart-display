"""Flux RSS d'actualité (France Info par défaut) pour le module système.

Le Pi récupère lui-même le flux (il n'a pas besoin du PC pour ça, et l'écran
par défaut doit fonctionner même agent déconnecté). Un thread de fond rafraîchit
périodiquement la liste des articles ; les écrans lisent cette liste (copie
thread-safe) pour l'afficher.

Parseur stdlib (urllib + xml.etree) : gère RSS (``item``) et Atom (``entry``),
sans dépendance supplémentaire. Tolérant : en cas d'erreur réseau/parse, conserve
les derniers articles connus.

Le flux est **partagé** entre l'accueil (3 derniers titres) et l'écran France
Info (liste complète) via ``get_feed(app)`` : une seule instance par application.
"""

from __future__ import annotations

import html
import re
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from email.utils import parsedate_to_datetime

_USER_AGENT = "PiDisplay/1.0 (+raspberry-smart-display)"
_TAG_RE = re.compile(r"<[^>]+>")
_MOIS_ABBR = ["janv.", "févr.", "mars", "avr.", "mai", "juin",
              "juil.", "août", "sept.", "oct.", "nov.", "déc."]


@dataclass(frozen=True)
class Article:
    title: str
    summary: str
    link: str
    published: str   # ex. "25 oct. · 19:34" (vide si absent/illisible)


def _localname(tag: str) -> str:
    """Nom de balise sans namespace (Atom préfixe tout par ``{...}``)."""
    return tag.rsplit("}", 1)[-1]


def _clean(text: str, *, strip_tags: bool = False) -> str:
    """Décode les entités HTML, retire éventuellement les balises, et normalise
    les espaces (dont insécables fins français que la police rend mal)."""
    if strip_tags:
        text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    for ch in (" ", " ", " "):
        text = text.replace(ch, " ")
    return " ".join(text.split())


def _format_date(raw: str) -> str:
    """'Sun, 25 Oct 2026 19:34:21 +0100' -> '25 oct. · 19:34' (heure locale)."""
    try:
        dt = parsedate_to_datetime(raw).astimezone()
        return f"{dt.day} {_MOIS_ABBR[dt.month - 1]} · {dt:%H:%M}"
    except Exception:
        return ""


def _child_text(item, names: tuple[str, ...]) -> str:
    for child in item:
        if _localname(child.tag) in names:
            return (child.text or "").strip()
    return ""


def _child_link(item) -> str:
    """Lien : texte (RSS) ou attribut href (Atom)."""
    for child in item:
        if _localname(child.tag) != "link":
            continue
        if child.text and child.text.strip():
            return child.text.strip()
        href = child.attrib.get("href")
        if href:
            return href.strip()
    return ""


def parse_articles(data: bytes, max_items: int) -> list[Article]:
    """Extrait jusqu'à ``max_items`` articles d'un flux RSS ou Atom."""
    root = ET.fromstring(data)
    articles: list[Article] = []
    for el in root.iter():
        if _localname(el.tag) not in ("item", "entry"):
            continue
        title = _clean(_child_text(el, ("title",)))
        if not title:
            continue
        summary = _clean(_child_text(el, ("description", "summary", "content")),
                         strip_tags=True)
        published = _format_date(_child_text(el, ("pubDate", "published", "updated")))
        articles.append(Article(title, summary, _child_link(el), published))
        if len(articles) >= max_items:
            break
    return articles


class RssFeed:
    """Récupère et tient à jour les articles d'un flux, en arrière-plan."""

    def __init__(self, url: str, *, refresh_interval: float = 900.0,
                 max_items: int = 15, timeout: float = 10.0):
        self.url = url
        self.refresh_interval = max(60.0, refresh_interval)
        self.max_items = max_items
        self.timeout = timeout
        self._lock = threading.Lock()
        self._articles: list[Article] = []
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def articles(self) -> list[Article]:
        with self._lock:
            return list(self._articles)

    # ----------------------------------------------------------------- interne
    def _loop(self) -> None:
        while True:
            items = self._fetch()
            if items:  # garde les anciens articles si le fetch échoue
                with self._lock:
                    self._articles = items
            time.sleep(self.refresh_interval)

    def _fetch(self) -> list[Article]:
        try:
            req = urllib.request.Request(self.url, headers={"User-Agent": _USER_AGENT})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = resp.read()
            return parse_articles(data, self.max_items)
        except Exception as exc:  # réseau, parse, etc. : on ne casse jamais l'UI
            print(f"[rss] échec du flux {self.url!r} : {exc}")
            return []


def get_feed(app):
    """Instance unique du flux pour l'app (partagée accueil ↔ France Info).

    Lit la config ``[rss]`` ; renvoie None si aucune URL n'est configurée.
    """
    if not hasattr(app, "_news_feed"):
        rss_cfg = app.config.get("rss", {})
        url = str(rss_cfg.get("url", "")).strip()
        feed = None
        if url:
            feed = RssFeed(
                url,
                refresh_interval=float(rss_cfg.get("refresh_minutes", 15)) * 60,
                max_items=int(rss_cfg.get("max_items", 15)),
            )
            feed.start()
        app._news_feed = feed
    return app._news_feed
