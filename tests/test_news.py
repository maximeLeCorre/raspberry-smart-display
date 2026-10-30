"""Écran France Info : extraction de l'article complet et pagination."""

from __future__ import annotations

import pygame

from modules.system import news_screen as ns
from modules.system.article_text import parse_article
from modules.system.rss_feed import Article

PAGE = """<html><body>
<nav><p>Menu</p></nav>
<p class="c-chapo ">  Le chapô&nbsp;de l'article. </p>
<div class="c-body">
  <p class="c-body__title">Ce qu'il faut savoir</p>
  <p>Premier <a href="/x">paragraphe</a> avec <em>lien</em>.</p>
  <figure><img src="a.jpg"><figcaption>Légende à ignorer</figcaption></figure>
  <script>var pub = 1;</script>
  <div class="c-related"><p>À lire aussi : autre chose</p></div>
  <h2>Un intertitre</h2>
  <ul><li><strong>Point clé.</strong> Détail du point.</li></ul>
  <blockquote><p>Une citation.</p></blockquote>
  <p>Dernier paragraphe.</p>
</div>
<footer><p>Mentions légales</p></footer>
</body></html>"""


def test_extraction_du_corps_de_l_article():
    assert parse_article(PAGE) == [
        ("chapo", "Le chapô de l'article."),
        ("h", "Ce qu'il faut savoir"),
        ("p", "Premier paragraphe avec lien."),
        ("h", "Un intertitre"),
        ("li", "Point clé. Détail du point."),
        ("quote", "Une citation."),
        ("p", "Dernier paragraphe."),
    ]
    assert parse_article("<html><p>Pas de corps</p></html>") is None


def test_pagination_sans_ecart_en_haut_de_page():
    lines = [(0, 30), (10, 30), (0, 30), (10, 30)]
    assert ns.paginate(lines, 70) == [0, 2]      # 30+10+30 tient ; la 3e ouvre une page
    assert ns.paginate([], 70) == [0]


class FakeApp:
    width, height = 800, 480
    config = {"rss": {"url": ""}}

    def __init__(self):
        self.calls = []

    def async_call(self, fn, cb):
        self.calls.append(cb)


def test_article_complet_charge_puis_feuillete(monkeypatch):
    pygame.init()
    monkeypatch.setattr(ns, "get_feed", lambda app: None)
    app = FakeApp()
    screen = ns.NewsScreen(app)
    art = Article("Titre", "Résumé du flux.", "https://exemple/a", "30 oct. · 10:00")

    screen.show_detail(art)
    assert screen._status() == "loading" and len(app.calls) == 1
    app.calls[0]([("p", "Très long paragraphe. " * 400)])     # livraison async
    assert screen._status() == "full" and len(screen._pages) > 2

    screen.handle_touch(ns.PAGE_UP.center)                     # déjà en haut
    assert screen.page == 0
    screen.handle_touch(ns.PAGE_DOWN.center)
    assert screen.page == 1
    screen.draw(pygame.Surface((800, 480)))

    # Échec réseau : résumé affiché, nouvel essai à la réouverture.
    other = Article("Autre", "Résumé.", "https://exemple/b", "")
    screen.show_detail(other)
    app.calls[1](None)
    assert screen._status() == "summary"
    screen.show_detail(other)
    assert len(app.calls) == 3
