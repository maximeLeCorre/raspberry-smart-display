"""Client API Web Riot du Pi : caches et limite de débit."""

from __future__ import annotations

import io
import json
import urllib.error

import riot_web
from riot_web import RiotWeb


class FakeResp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(code, retry_after=None):
    hdrs = {"Retry-After": retry_after} if retry_after else {}
    return urllib.error.HTTPError("u", code, "err", hdrs, None)


def test_echec_de_resolution_non_mis_en_cache(monkeypatch):
    riot = RiotWeb("cle", "euw1", "europe")
    answers = [None, {"puuid": "abc"}]
    monkeypatch.setattr(riot, "_get", lambda host, path: answers.pop(0))
    assert riot.resolve_puuid("Nom", "TAG") is None      # coupure réseau
    assert riot.resolve_puuid("Nom", "TAG") == "abc"     # réessayé, pas figé
    assert riot.resolve_puuid("Nom", "TAG") == "abc"     # réussite en cache
    assert answers == []


def test_429_attend_retry_after_puis_reessaie(monkeypatch):
    calls, sleeps = [], []

    def urlopen(req, timeout):
        calls.append(req.full_url)
        if len(calls) == 1:
            raise http_error(429, "2")
        return FakeResp(json.dumps({"ok": 1}).encode())
    monkeypatch.setattr(riot_web.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(riot_web.time, "sleep", sleeps.append)
    assert riot_web._http_get("https://x") == b'{"ok": 1}'
    assert len(calls) == 2 and sleeps == [2.0]


def test_429_persistant_abandonne(monkeypatch):
    def urlopen(req, timeout):
        raise http_error(429, "999")
    sleeps = []
    monkeypatch.setattr(riot_web.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(riot_web.time, "sleep", sleeps.append)
    assert riot_web._http_get("https://x") is None
    assert sleeps == [riot_web.RATE_LIMIT_MAX_WAIT] * riot_web.RATE_LIMIT_RETRIES


def test_cache_des_parties_borne(monkeypatch):
    riot = RiotWeb("cle", "euw1", "europe")
    monkeypatch.setattr(riot, "_get", lambda host, path: {"id": path})
    for i in range(riot_web.MATCH_CACHE_SIZE + 10):
        riot.match(f"EUW_{i}")
    assert len(riot._match_cache) == riot_web.MATCH_CACHE_SIZE
    assert "EUW_0" not in riot._match_cache


def test_tuile_du_skin_joue_chroma_compris():
    from riot_web import CDRAGON_ASSETS, skin_asset_url
    detail = {"id": 21, "skins": [
        {"id": 21000, "tilePath": "/lol-game-data/assets/ASSETS/Characters/MissFortune/"
                                  "Skins/Base/Images/missfortune_splash_tile_0.jpg"},
        {"id": 21007, "tilePath": "/lol-game-data/assets/ASSETS/Characters/MissFortune/"
                                  "Skins/Skin07/Images/missfortune_splash_tile_7.jpg",
         "chromas": [{"id": 21014, "tilePath": "/lol-game-data/assets/v1/champion-chroma-images/21/21014.png"}]},
    ]}
    tile7 = CDRAGON_ASSETS + "assets/characters/missfortune/skins/skin07/images/missfortune_splash_tile_7.jpg"
    assert skin_asset_url(detail, 7) == tile7
    assert skin_asset_url(detail, 14) == tile7         # chroma -> art du skin parent
    assert skin_asset_url(detail, 99) is None
    assert skin_asset_url(detail, 7, "loadScreenPath") is None   # champ absent
