"""Cache disque des icônes : servi au même patch, repris au patch suivant,
servi tel quel hors ligne."""

from __future__ import annotations

import riot_web
from icon_cache import IconCache


def setup(monkeypatch, patch):
    downloads = []
    monkeypatch.setattr(riot_web, "current_patch", lambda: patch["v"])
    monkeypatch.setattr(riot_web, "_download_icon",
                        lambda cid: downloads.append(cid) or f"img{len(downloads)}".encode())
    return downloads


def test_icone_servie_depuis_le_disque_au_meme_patch(tmp_path, monkeypatch):
    patch = {"v": "16.21"}
    downloads = setup(monkeypatch, patch)
    cache = IconCache(tmp_path / "i.db")
    assert riot_web.icon_bytes(21, cache) == b"img1"
    assert riot_web.icon_bytes(21, IconCache(tmp_path / "i.db")) == b"img1"   # redémarrage
    assert downloads == [21]


def test_icone_reprise_au_patch_suivant(tmp_path, monkeypatch):
    patch = {"v": "16.21"}
    downloads = setup(monkeypatch, patch)
    cache = IconCache(tmp_path / "i.db")
    riot_web.icon_bytes(21, cache)
    patch["v"] = "16.22"
    assert riot_web.icon_bytes(21, cache) == b"img2"
    assert cache.get(21) == (b"img2", "16.22")


def test_hors_ligne_le_cache_suffit(tmp_path, monkeypatch):
    patch = {"v": "16.21"}
    downloads = setup(monkeypatch, patch)
    cache = IconCache(tmp_path / "i.db")
    riot_web.icon_bytes(21, cache)
    patch["v"] = ""                                  # patch inconnu (réseau coupé)
    assert riot_web.icon_bytes(21, cache) == b"img1"
    monkeypatch.setattr(riot_web, "_download_icon", lambda cid: None)
    patch["v"] = "16.22"                             # nouveau patch mais CDN injoignable
    assert riot_web.icon_bytes(21, cache) == b"img1"
    assert downloads == [21]


def test_nouveau_patch_vide_le_cache_memoire_des_ecrans(monkeypatch):
    from modules.league import icons

    class League:
        def __init__(self):
            self.asked = []

        def request_icon(self, cid):
            self.asked.append(cid)

    patch = {"v": ""}
    monkeypatch.setattr(icons, "known_patch", lambda: patch["v"])
    league = League()
    cache = icons.ChampionIcons(league, 34)
    cache.get(18)
    patch["v"] = "16.21"                  # 1re lecture du patch : rien à vider
    cache._cache[18] = object()
    assert cache.get(18) is not None and league.asked == [18]
    patch["v"] = "16.22"                  # nouveau patch : image redemandée
    assert cache.get(18) is None and league.asked == [18, 18]
