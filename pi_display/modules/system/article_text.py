"""Texte complet d'un article France Info (le flux RSS n'a qu'un résumé).

Le Pi télécharge la page de l'article (hors boucle de rendu : `App.async_call`)
et en extrait le texte lisible, sans dépendance (stdlib `html.parser`) :
  - le chapô : ``<p class="c-chapo">`` ;
  - le corps : ``<div class="c-body">`` → paragraphes, intertitres, listes,
    citations ; on saute figures, vidéos, scripts, encarts « à lire aussi »…

Résultat : liste de blocs ``(type, texte)`` avec type ∈ chapo / h / p / li / quote.
Tolérant : page illisible ou structure inconnue → None (l'écran garde le résumé).
"""

from __future__ import annotations

import urllib.request
from html.parser import HTMLParser

_USER_AGENT = "Mozilla/5.0 (X11; Linux armv7l) PiDisplay/1.0"
_MAX_BYTES = 3_000_000

BLOCKS = {"p": "p", "li": "li", "h2": "h", "h3": "h", "h4": "h", "blockquote": "quote"}
SKIP = {"script", "style", "figure", "figcaption", "aside", "button", "noscript",
        "svg", "iframe", "form", "video", "audio", "picture", "template"}
# Encarts du corps qui ne sont pas du texte d'article (classes France Info).
SKIP_CLASSES = ("related", "c-signature", "ad-", "pub", "newsletter", "c-embed",
                "tooltip", "share", "c-read-more", "o-widget")


def _classes(attrs) -> list[str]:
    return (dict(attrs).get("class") or "").split()


class _ArticleParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, str]] = []
        self._div_depth = 0
        self._body_depth = None        # profondeur de div du c-body (None = hors corps)
        self._done = False
        self._skip: list[str] = []     # pile des balises ignorées (avec leur contenu)
        self._kind: str | None = None  # bloc en cours
        self._buf: list[str] = []

    # ------------------------------------------------------------------ blocs
    def _open(self, kind: str) -> None:
        self._flush()
        self._kind = kind

    def _flush(self) -> None:
        text = " ".join("".join(self._buf).split())
        if self._kind and text:
            if self._kind == "p" and self.blocks and self.blocks[-1] == ("p", text):
                pass                    # doublon (version mobile/desktop)
            else:
                self.blocks.append((self._kind, text))
        self._kind, self._buf = None, []

    # ---------------------------------------------------------------- parseur
    def handle_starttag(self, tag, attrs):
        if self._done:
            return
        cls = _classes(attrs)
        if tag == "div":
            self._div_depth += 1
        if self._skip:
            if tag == self._skip[0]:
                self._skip.append(tag)
            return
        in_body = self._body_depth is not None
        if tag in SKIP or (in_body and tag in ("div", "section", "aside", "ul")
                           and any(k in c for c in cls for k in SKIP_CLASSES)):
            self._skip.append(tag)
            return
        if tag == "div" and "c-body" in cls and not in_body:
            self._body_depth = self._div_depth
            return
        if tag == "p" and "c-chapo" in cls and not in_body:
            self._open("chapo")
            return
        if in_body:
            if tag == "p" and "c-body__title" in cls:
                self._open("h")
            elif tag in BLOCKS and not (tag == "p" and self._kind in ("li", "quote")):
                self._open(BLOCKS[tag])
            elif tag == "br" and self._kind:
                self._buf.append(" ")

    def handle_endtag(self, tag):
        if self._done:
            return
        if self._skip:
            if tag == self._skip[0]:
                self._skip.pop()
            if tag == "div":
                self._div_depth -= 1
            return
        if tag in BLOCKS and self._kind is not None:
            if self._kind != "li" or tag == "li":
                if self._kind != "quote" or tag == "blockquote":
                    self._flush()
        if tag == "div":
            if self._body_depth is not None and self._div_depth == self._body_depth:
                self._flush()
                self._done = True
            self._div_depth -= 1

    def handle_data(self, data):
        if self._kind and not self._skip and not self._done:
            self._buf.append(data)


def parse_article(html_text: str) -> list[tuple[str, str]] | None:
    """Blocs (type, texte) du chapô + corps ; None si aucun corps trouvé."""
    parser = _ArticleParser()
    try:
        parser.feed(html_text)
        parser.close()
    except Exception:
        return None
    blocks = [(k, t.replace(" ", " ").replace(" ", " ")) for k, t in parser.blocks]
    return blocks if any(k != "chapo" for k, _ in blocks) else None


def fetch_article(url: str, timeout: float = 10.0) -> list[tuple[str, str]] | None:
    """Télécharge et extrait l'article (bloquant : à lancer via App.async_call)."""
    if not url.startswith(("http://", "https://")):
        return None
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT,
                                               "Accept-Language": "fr-FR,fr;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read(_MAX_BYTES)
            charset = resp.headers.get_content_charset() or "utf-8"
    except Exception as exc:
        print(f"[news] Article indisponible : {exc}")
        return None
    return parse_article(raw.decode(charset, "replace"))
