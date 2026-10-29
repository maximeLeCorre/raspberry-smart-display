"""Écran « Trains » : parse des réponses SIRI Lite de l'API PRIM (IDFM)."""

from __future__ import annotations

from modules.transit.transit_feed import Departure, parse_departures, parse_messages
from modules.transit.transit_screen import minutes_label, status_text


def _visit(dest, aimed, expected=None, status="onTime", at_stop=False, mission="PEBU",
           platform="1"):
    """Un MonitoredStopVisit au format réel (cf. exemple de réponse PRIM)."""
    call = {"VehicleAtStop": at_stop, "DestinationDisplay": [{"value": dest}],
            "DepartureStatus": status, "DeparturePlatformName": {"value": platform}}
    if aimed:
        call["AimedDepartureTime"] = aimed
    if expected:
        call["ExpectedDepartureTime"] = expected
    return {"MonitoredVehicleJourney": {
        "LineRef": {"value": "STIF:Line::C01740:"},
        "DestinationName": [{"value": dest}], "DirectionName": [],
        "JourneyNote": [{"value": mission}], "MonitoredCall": call}}


def _stop_monitoring(visits):
    return {"Siri": {"ServiceDelivery": {"StopMonitoringDelivery": [
        {"MonitoredStopVisit": visits}]}}}


def test_parse_departures_trie_et_range_par_direction():
    deps = parse_departures(_stop_monitoring([
        _visit("Versailles Rive Droite", "2026-10-29T10:20:00.000Z"),
        _visit("Paris Saint-Lazare", "2026-10-29T10:10:00.000Z",
               "2026-10-29T10:13:00.000Z", status="delayed"),
        _visit("Paris Saint-Lazare", None),          # pas de départ (arrivée)
    ]), ("saint-lazare",))
    assert [d.destination for d in deps] == ["Paris Saint-Lazare", "Versailles Rive Droite"]
    paris, versailles = deps
    assert paris.to_paris and not versailles.to_paris
    assert paris.delay_min == 3 and paris.mission == "PEBU" and paris.platform == "1"
    assert versailles.delay_min == 0


def test_parse_departures_reponse_vide_ou_inattendue():
    assert parse_departures({}, ("saint-lazare",)) == []
    assert parse_departures({"Siri": {"ServiceDelivery": {}}}, ()) == []


def test_parse_messages_perturbations_d_abord_sans_doublon():
    def info(channel, *texts):
        return {"InfoChannelRef": {"value": channel}, "Content": {"Message": [
            {"MessageType": t[0], "MessageText": {"value": t[1]}} for t in texts]}}
    data = {"Siri": {"ServiceDelivery": {"GeneralMessageDelivery": [{"InfoMessage": [
        info("Information", ("TEXT_ONLY", "Ascenseur hors service")),
        info("Perturbation", ("SHORT_MESSAGE", "Travaux"),
             ("TEXT_ONLY", "<p>Travaux&nbsp;: trafic interrompu</p>")),
        info("Information", ("TEXT_ONLY", "Ascenseur hors service")),
    ]}]}}}
    msgs = parse_messages(data)
    assert [m.channel for m in msgs] == ["Perturbation", "Information"]
    assert msgs[0].text == "Travaux : trafic interrompu"     # texte long, HTML nettoyé
    assert msgs[0].is_disruption and not msgs[1].is_disruption


def _dep(**kw):
    base = dict(when=1000.0, aimed=1000.0, destination="Paris Saint-Lazare", mission="",
                platform="", status="onTime", at_stop=False, to_paris=True)
    base.update(kw)
    return Departure(**base)


def test_libelles_ecrits_pas_seulement_colores():
    assert minutes_label(_dep(when=1000 + 9 * 60), 1000) == "9 min"
    assert minutes_label(_dep(when=1020), 1000) == "proche"
    assert minutes_label(_dep(at_stop=True), 1000) == "à quai"
    assert minutes_label(_dep(status="cancelled"), 1000) == "suppr."
    assert status_text(_dep(when=1180, status="delayed"))[0] == "retard +3 min"
    assert status_text(_dep(status="cancelled"))[0] == "supprimé"
    assert status_text(_dep())[0] == "à l'heure"


def test_lettre_de_ligne_et_abreviations():
    from modules.transit.transit_feed import line_id
    from modules.transit.transit_screen import short_destination
    assert line_id("STIF:Line::C01741:") == "C01741"
    visit = _visit("La Défense", "2026-10-29T10:16:00.000Z")
    visit["MonitoredVehicleJourney"]["LineRef"] = {"value": "STIF:Line::C01741:"}
    dep, = parse_departures(_stop_monitoring([visit]), ("saint-lazare", "la défense"),
                            {"C01740": "L", "C01741": "U"})
    assert dep.line == "U" and dep.to_paris
    assert short_destination("Paris Saint-Lazare") == "Paris St-Lazare"
    assert short_destination("Versailles Rive Droite") == "Versailles RD"


def test_prochain_train_pour_paris_a_l_arrivee_en_gare():
    """Accueil : temps avant l'ENTRÉE en gare du prochain St-Lazare (pas La Défense,
    pas un train supprimé ni déjà reparti)."""
    from modules.transit.transit_screen import arrival_label, next_arrival
    now = 10_000.0
    deps = [
        _dep(destination="Paris Saint-Lazare", when=now - 100, arrival=now - 160),  # parti
        _dep(destination="La Défense", when=now + 60, arrival=now + 30),
        _dep(destination="Paris Saint-Lazare", when=now + 300, arrival=now + 240,
             status="cancelled"),
        _dep(destination="Paris Saint-Lazare", when=now + 600, arrival=now + 540),
    ]
    dep = next_arrival(deps, "saint-lazare", now)
    assert dep is deps[3] and arrival_label(dep, now) == "9 min"
    assert arrival_label(_dep(at_stop=True), now) == "à quai"
    assert next_arrival([], "saint-lazare", now) is None
