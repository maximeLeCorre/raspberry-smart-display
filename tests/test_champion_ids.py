"""Id de champion des joueurs en partie : nom localisé, variantes de mode de jeu."""

from __future__ import annotations

import lcu
from riot_api import summarize_full

SUMMARY = [
    {"id": 60018, "name": "Tristana", "alias": "Jade_Tristana"},   # variante (mode de jeu)
    {"id": 18, "name": "Tristana", "alias": "Tristana"},
    {"id": 11, "name": "Master Yi", "alias": "MasterYi"},
]


class FakeResp:
    status_code = 200

    def json(self):
        return SUMMARY


def client(monkeypatch):
    monkeypatch.setattr(lcu.requests, "get", lambda *a, **k: FakeResp())
    return lcu.LcuClient()


def test_vrai_champion_prefere_a_la_variante(monkeypatch):
    c = client(monkeypatch)
    assert c.champion_id_by_name("Tristana") == 18
    assert c.champion_id_by_name("Tristana", "game_character_displayname_Tristana") == 18


def test_nom_localise_resolu_par_le_nom_technique(monkeypatch):
    c = client(monkeypatch)
    assert c.champion_id_by_name("Maître Yi") == 0                     # table en anglais
    assert c.champion_id_by_name("Maître Yi", "game_character_displayname_MasterYi") == 11


def test_scoreboard_avec_nom_technique(monkeypatch):
    c = client(monkeypatch)
    data = {"allPlayers": [{"championName": "Maître Yi", "team": "ORDER",
                            "rawChampionName": "game_character_displayname_MasterYi",
                            "riotIdGameName": "Matte mwa", "riotIdTagLine": "EUW"}],
            "activePlayer": {}, "gameData": {}, "events": {}}
    assert summarize_full(data, c.champion_id_by_name)["players"][0]["championId"] == 11
