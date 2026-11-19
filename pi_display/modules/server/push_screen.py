"""Écran « Push NexusLink » : détail du serveur de notifications iPhone de NexusLink.

Vignettes : service systemd (relevé `pi-monitor`), temps de réponse de `/health` (certificat
épinglé), envois sur 24 h, installations. Barres : envois par heure sur 24 h, historique
gardé par le Pi (`history.py`, le serveur ne donne que des compteurs depuis son démarrage) ;
la part refusée/limitée est hachurée au-dessus. Bas : compteurs et alertes du push.
"""

from __future__ import annotations

import time

import pygame

from screen import Screen

from . import widgets as w
from .monitor import CRIT, OK, UNKNOWN, WARN

TILE_Y, TILE_H = 58, 80
TILE_W = (752 - 3 * 10) // 4
CHART = pygame.Rect(24, 150, 752, 168)
PLOT = pygame.Rect(CHART.x + 48, CHART.y + 34, CHART.w - 62, CHART.h - 62)  # marge gauche = échelle
COUNTS = pygame.Rect(24, 330, 371, 140)
ALERT_BOX = pygame.Rect(405, 330, 371, 140)
SERVICE_WORD = {"active": "actif", "inactive": "arrêté", "failed": "en échec",
                "activating": "démarre", "deactivating": "s'arrête"}


class PushScreen(Screen):
    name = "server_push"
    background_name = None
    bg_color = w.BG
    cycle = False

    def __init__(self, app):
        super().__init__(app)
        self.fonts = w.Fonts()
        self.module = app.modules.get("server")
        self._key = None
        self._drawn_at = 0.0

    def enter(self) -> None:
        self._key = None

    def draw(self, surface: pygame.Surface) -> list[pygame.Rect]:
        # Relevés lents (SQLite, sondes) : recalcul au plus 1×/s (Pi 3), sauf juste après l'entrée.
        if self._key is not None and time.monotonic() - self._drawn_at < 1.0:
            return []
        self._drawn_at = time.monotonic()
        mod = self.module
        now = time.time()
        probes = mod.probes.snapshot() if mod.probes else {}
        pp = probes.get("push") or {}
        rep = (mod.link.report() if mod.link else {}) or {}
        svc = ((rep.get("data") or {}).get("push")) or {}
        hours = mod.history.push_hours(now) if mod.history else []
        alerts = tuple((a.level, a.text) for a in mod.monitor.alerts("push"))
        level = mod.monitor.card_level("push")
        key = (repr(pp), repr(svc), tuple(tuple(h.values()) for h in hours), alerts, level, int(now // 60))
        if key == self._key:
            return []
        self._key = key
        surface.blit(self.bg, (0, 0))
        f = self.fonts
        w.header(surface, f, "PUSH · NexusLink")
        n = len(alerts)
        r = w.blit(surface, f.small, {OK: "tout est OK", WARN: f"{n} avertissement{'s' if n > 1 else ''}",
                                      CRIT: "panne", UNKNOWN: "état inconnu"}[level],
                   w.LEVEL_COLOR[level], (684, 27), anchor="midright")
        w.state_icon(surface, level, (r.x - 14, 27), 18)
        self._tiles(surface, pp, svc, hours, now)
        self._chart(surface, hours, bool(pp.get("stats")), pp)
        self._counts(surface, pp, hours)
        self._alerts(surface, alerts, level)
        return [surface.get_rect()]

    def _tile(self, surface, i, title, value, sub, color=w.WHITE) -> None:
        f = self.fonts
        rect = pygame.Rect(24 + i * (TILE_W + 10), TILE_Y, TILE_W, TILE_H)
        pygame.draw.rect(surface, w.PANEL, rect, border_radius=12)
        w.blit(surface, f.small, title, w.GREY, (rect.x + 12, rect.y + 8), rect.w - 24)
        w.blit(surface, f.big, value, color, (rect.x + 12, rect.y + 30), rect.w - 24)
        w.blit(surface, f.tiny, sub, w.DIM, (rect.x + 12, rect.y + 60), rect.w - 24)

    def _tiles(self, surface, pp, svc, hours, now) -> None:
        state = svc.get("state", "")
        word = SERVICE_WORD.get(state, state or "—")
        color = w.GREEN if state == "active" else (w.GREY if not state else w.RED)
        since = f"wardlink-push · {w.duration(now - svc['since'])}" if svc.get("since") else "wardlink-push"
        self._tile(surface, 0, "Service", word, since, color)
        if pp.get("up"):
            self._tile(surface, 1, "/health", f"{pp.get('ms')} ms", "depuis le Pi · :8443")
        else:
            self._tile(surface, 1, "/health", "KO", pp.get("error") or "en attente…", w.RED if pp else w.GREY)
        st = pp.get("stats") or {}
        if st:
            sent = sum(h["delivered"] for h in hours)
            last = next((h["hour"] for h in reversed(hours) if h["pushed"]), None)
            self._tile(surface, 2, "Envois 24 h", str(sent),
                       f"dernier vers {w.hhmm(last * 3600)}" if last else "aucun envoi")
            # installs = relais PC (Wardlink) ; grants = jetons APNs attestés, pas des iPhones :
            # un jeton remplacé (app réinstallée, build Xcode/TestFlight) reste valide 90 j.
            n = st.get("grants", 0)
            self._tile(surface, 3, "Relais PC", str(st.get("installs", 0)),
                       f"{n} jeton{'s' if n > 1 else ''} iPhone valide{'s' if n > 1 else ''}")
        else:
            msg = pp.get("stats_error") or "PUSH_STATS_TOKEN absent"
            self._tile(surface, 2, "Envois 24 h", "—", msg, w.GREY)
            self._tile(surface, 3, "Relais PC", "—", msg, w.GREY)

    def _chart(self, surface, hours, have_stats, pp) -> None:
        f = self.fonts
        pygame.draw.rect(surface, w.PANEL, CHART, border_radius=12)
        w.blit(surface, f.tiny, "ENVOIS PAR HEURE · 24 H", w.GREY, (CHART.x + 14, CHART.y + 10))
        top = max([h["delivered"] + h["refused"] + h["limited"] + h["failed"] for h in hours] + [0])
        w.blit(surface, f.tiny, f"max {top} / h · hachuré = refusé ou limité", w.DIM,
               (CHART.right - 14, CHART.y + 10), anchor="topright")
        # Échelle verticale en envois / h : pas entier 1/2/5 × 10^k, au plus 4 graduations.
        step = w.nice_step(max(top, 1))
        axis_top = step * max(1, -(-top // step))
        w.y_axis(surface, f.tiny, PLOT, axis_top, step, lambda v: f"{v:.0f}")
        pygame.draw.line(surface, w.BORDER, (PLOT.x, PLOT.bottom), (PLOT.right, PLOT.bottom))
        if not hours or not have_stats and top == 0:
            w.blit(surface, f.small, "historique en cours de collecte (relevé toutes les 5 min)", w.DIM,
                   PLOT.center, anchor="center")
        n = max(1, len(hours))
        slot = PLOT.w / n
        scale = PLOT.h / axis_top
        for i, h in enumerate(hours):
            x = PLOT.x + int(i * slot) + 2
            bw = max(2, int(slot) - 5)
            ok_h = int(h["delivered"] * scale)
            bad_h = int((h["refused"] + h["limited"] + h["failed"]) * scale)
            if not ok_h and not bad_h:
                pygame.draw.rect(surface, w.TRACK, (x, PLOT.bottom - 2, bw, 2))
                continue
            if ok_h:
                pygame.draw.rect(surface, w.BLUE, (x, PLOT.bottom - ok_h, bw, ok_h),
                                 border_top_left_radius=3, border_top_right_radius=3)
            if bad_h:
                w.hatch(surface, pygame.Rect(x, PLOT.bottom - ok_h - bad_h, bw, bad_h), w.ORANGE, (58, 42, 16))
        if hours:
            for i in range(0, 9):
                idx = min(len(hours) - 1, i * 3)
                label = "maint." if i == 8 else f"{time.localtime(hours[idx]['hour'] * 3600).tm_hour} h"
                anchor = "midtop" if 0 < i < 8 else ("topleft" if i == 0 else "topright")
                w.blit(surface, f.tiny, label, w.DIM, (PLOT.x + i * PLOT.w // 8, PLOT.bottom + 6), anchor=anchor)

    def _counts(self, surface, pp, hours) -> None:
        f = self.fonts
        rect = COUNTS
        pygame.draw.rect(surface, w.PANEL, rect, border_radius=12)
        st = pp.get("stats") or {}
        rows = [("Refus d'Apple (24 h)", str(sum(h["refused"] for h in hours))),
                ("Limités, anti-abus (24 h)", str(sum(h["limited"] for h in hours))),
                ("Échecs (24 h)", str(sum(h["failed"] for h in hours))),
                ("Bannis", f"{st.get('banned', 0)} relais" if st else "—"),
                ("Certificat TLS", f"{pp['cert_days']} j" if pp.get("cert_days") is not None else "—")]
        if st.get("started"):
            rows.append(("Compteurs depuis", time.strftime("%d/%m %H:%M", time.localtime(st["started"]))))
        y = rect.y + 12
        for key, value in rows:
            w.kv(surface, f, rect, y, key, value)
            y += 21

    def _alerts(self, surface, alerts, level) -> None:
        f = self.fonts
        rect = ALERT_BOX
        from modules.system.news_screen import wrap_text
        if not alerts:
            w.panel(surface, rect)
            w.state_word(surface, f.label, level, (rect.x + 14, rect.y + 26), 22,
                         word="Aucun problème" if level == OK else "État inconnu")
            w.blit(surface, f.small, "Droits App Attest, service, refus : rien à signaler"
                   if level == OK else "relevés pas encore reçus", w.GREY, (rect.x + 14, rect.y + 52), rect.w - 28)
            return
        top = CRIT if any(lv == CRIT for lv, _ in alerts) else WARN
        w.panel(surface, rect, top)
        w.state_word(surface, f.label, top, (rect.x + 14, rect.y + 24), 22,
                     word="PANNE" if top == CRIT else "AVERTISSEMENT")
        y = rect.y + 46
        for lv, text in alerts[:3]:
            for line in wrap_text(text, f.small, rect.w - 28, 2):
                w.blit(surface, f.small, line, w.WHITE, (rect.x + 14, y), rect.w - 28)
                y += 20
            y += 4

    def handle_touch(self, pos: tuple[int, int]) -> str | None:
        if w.RETOUR_RECT.collidepoint(pos):
            self.app.manual_screen = "server"
            self.app.set_screen("server")
        return None
