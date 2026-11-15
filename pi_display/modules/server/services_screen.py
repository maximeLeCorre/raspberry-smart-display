"""Écran « Serveur » (entrée de la tuile Serveur) : vue d'ensemble de la VM et de ses services.

Trois cartes (Machine, Rentrer, push NexusLink), chacune avec son état écrit (OK /
ATTENTION / PANNE / INCONNU) et quelques chiffres ; toucher une carte ouvre son détail
(`server_machine`, `server_rentrer`, `server_push`). En bas : alertes en cours (avec « montre
prévenue » ou « écran seul »), sinon « Aucune alerte ». Données : `ServerModule` (règles
`monitor.py`, relevés SSH et HTTP) ; redessin complet seulement quand ce qui est affiché change.
"""

from __future__ import annotations

import time

import pygame

from inputs import ACTION_BACK
from screen import Screen

from . import widgets as w
from .monitor import CRIT, OK, UNKNOWN, WARN, WORDS

CARD_Y, CARD_H, CARD_GAP = 64, 266, 14
CARD_W = (752 - 2 * CARD_GAP) // 3
CARD_RECTS = {card: pygame.Rect(24 + i * (CARD_W + CARD_GAP), CARD_Y, CARD_W, CARD_H)
              for i, card in enumerate(("vm", "rentrer", "push"))}
DETAIL = {"vm": "server_machine", "rentrer": "server_rentrer", "push": "server_push"}
ALERTS_RECT = pygame.Rect(24, 344, 752, 124)


def summary(levels: list[str]) -> tuple[str, str]:
    """(niveau, texte) de l'en-tête : « tout est OK », « 1 panne · 1 avertissement »."""
    crit, warn = levels.count(CRIT), levels.count(WARN)
    if not crit and not warn:
        if UNKNOWN in levels:
            return UNKNOWN, "état inconnu"
        return OK, "tout est OK"
    parts = []
    if crit:
        parts.append(f"{crit} panne{'s' if crit > 1 else ''}")
    if warn:
        parts.append(f"{warn} avertissement{'s' if warn > 1 else ''}")
    return (CRIT if crit else WARN), " · ".join(parts)


class ServicesScreen(Screen):
    name = "server"
    background_name = None
    bg_color = w.BG
    cycle = True

    def __init__(self, app):
        super().__init__(app)
        self.fonts = w.Fonts()
        self.module = app.modules.get("server")
        self._key = None
        self._drawn_at = 0.0

    def enter(self) -> None:
        self._key = None

    # ------------------------------------------------------------------ données
    def _view(self) -> dict:
        mod = self.module
        mon = mod.monitor
        link = mod.link
        snap = link.snapshot() if link else {}
        probes = mod.probes.snapshot() if mod.probes else {}
        rep = (link.report() if link else {}) or {}
        data = rep.get("data") or {}
        now = time.time()
        cards = {}
        for card in CARD_RECTS:
            level = mon.card_level(card) if link else UNKNOWN
            alerts = [a.text for a in mon.alerts(card)]
            cards[card] = (level, tuple(alerts[:2]), tuple(self._lines(card, snap, probes, data, now)))
        alerts = tuple((a.level, a.raised, a.text, a.level in mon.settings.notify) for a in mon.alerts())
        gauges = ()
        if snap.get("online"):
            gauges = tuple((name, used / total) for name, used, total in (
                ("CPU", snap.get("cpu_pct") or 0, 100), ("RAM", snap.get("mem_used", 0), snap.get("mem_total", 0)),
                ("Disque", snap.get("disk_used", 0), snap.get("disk_total", 0))) if total)
            gauges = tuple((n, round(v, 2)) for n, v in gauges)
        return {"cards": cards, "alerts": alerts, "offline": mon.offline, "host": snap.get("host", ""),
                "gauges": gauges,
                "ts": probes.get("ts") or snap.get("ts") or 0, "configured": link is not None}

    def _lines(self, card, snap, probes, data, now) -> list[str]:
        if card == "vm":
            if not snap.get("online"):
                return [snap.get("error") or "hors ligne"]
            lines = []
            mod = self.module
            svc = mod.link.services[0] if mod.link and mod.link.services else None
            if svc:
                st = snap.get("services", {}).get(svc["unit"], "")
                word = {"active": "actif", "inactive": "arrêté", "failed": "en échec"}.get(st, st or "…")
                text = f"{svc['label']} : {word}"
                players = mod.link.players(svc["unit"]) if svc.get("minecraft_port") else None
                if st == "active" and players and "error" not in players:
                    n = players["online"]
                    text += f" · {n} joueur{'s' if n > 1 else ''}"
                lines.append(text)
            return lines
        if card == "rentrer":
            rp = probes.get("rentrer") or {}
            lines = []
            status = rp.get("status") or {}
            if status.get("state"):
                lines.append(f"Témoins : {WORDS.get({'ok': OK, 'degraded': WARN, 'down': CRIT}.get(status['state'], UNKNOWN))}"
                             f" depuis {w.hhmm(status.get('since'))}")
            ctrs = data.get("containers") or {}
            want = self.module.monitor.settings.services
            if ctrs:
                up = sum(1 for s in want if (ctrs.get(s) or {}).get("state") == "running")
                lines.append(f"{up} / {len(want)} conteneurs actifs")
            plan = data.get("plan") or {}
            if data:
                lines.append("Plan IDFM : nouveau, pas importé" if plan.get("pending")
                             else f"Plan IDFM à jour ({w.hhmm(plan.get('imported_at'))})")
            st = rp.get("stats") or {}
            if st:
                lines.append(f"{(st.get('today') or {}).get('pushSent', 0)} notifs aujourd'hui")
            return lines or [rp.get("error") or "en attente du relevé…"]
        pp = probes.get("push") or {}
        lines = []
        if pp.get("up"):
            lines.append(f"actif · répond en {pp.get('ms')} ms")
        hours = self.module.history.push_hours(now) if self.module.history else []
        if pp.get("stats"):
            lines.append(f"{sum(h['delivered'] for h in hours)} envois / 24 h")
            st = pp["stats"]
            lines.append(f"{sum(h['refused'] for h in hours)} refus · {st.get('banned', 0)} banni")
        if pp.get("cert_days") is not None:
            lines.append(f"certificat : {pp['cert_days']} j")
        return lines or [pp.get("error") or "en attente du relevé…"]

    # ------------------------------------------------------------------ rendu
    def draw(self, surface: pygame.Surface) -> list[pygame.Rect]:
        # Relevés lents (SQLite, sondes) : recalcul au plus 1×/s (Pi 3), sauf juste après l'entrée.
        if self._key is not None and time.monotonic() - self._drawn_at < 1.0:
            return []
        self._drawn_at = time.monotonic()
        view = self._view()
        key = (view["cards"], view["alerts"], view["offline"], int(view["ts"]), view["configured"],
               view["host"], view["gauges"])
        if key == self._key:
            return []
        self._key = key
        surface.blit(self.bg, (0, 0))
        f = self.fonts
        w.header(surface, f, f"SERVEUR · {view['host']}" if view["host"] else "SERVEUR")
        if not view["configured"]:
            w.blit(surface, f.label, "Serveur non configuré — SERVER_HOST dans le .env du Pi.",
                   w.GREY, (40, 120))
            return [surface.get_rect()]
        levels = [c[0] for c in view["cards"].values()]
        level, text = summary(levels)
        if view["offline"]:
            level, text = UNKNOWN, "le Pi n'a plus internet"
        r = w.blit(surface, f.small, text, w.LEVEL_COLOR[level], (684, 27), anchor="midright")
        w.state_icon(surface, level, (r.x - 14, 27), 18)

        titles = {"vm": ("MACHINE", "VM"), "rentrer": ("RENTRER", "API trajets"),
                  "push": ("NEXUSLINK", "Serveur de push")}
        for card, rect in CARD_RECTS.items():
            level, alerts, lines = view["cards"][card]
            w.panel(surface, rect, level if level in (WARN, CRIT) else None)
            x, y, max_w = rect.x + 14, rect.y + 12, rect.w - 28
            w.blit(surface, f.tiny, titles[card][0], w.GREY, (x, y))
            w.blit(surface, f.label, titles[card][1], w.WHITE, (x, y + 18), max_w)
            w.state_word(surface, f.big, level, (x, y + 64), 24)
            y += 88
            for text in alerts:
                y = self._wrap(surface, text, w.LEVEL_COLOR[CRIT if level == CRIT else WARN], x, y, max_w, 2)
            if card == "vm" and view["gauges"]:
                y = self._gauges(surface, view["gauges"], x, y, max_w)
            for text in lines[: max(0, 5 - len(alerts) * 2)]:
                if y > rect.bottom - 44:
                    break
                w.blit(surface, f.small, text, w.SOFT, (x, y), max_w)
                y += 22
            r = w.blit(surface, f.small, "DÉTAIL", w.GOLD, (x, rect.bottom - 26))
            w.arrow(surface, w.GOLD, (r.right + 10, r.centery))

        self._draw_alerts(surface, view)
        return [surface.get_rect()]

    def _gauges(self, surface, gauges, x, y, max_w) -> int:
        """CPU / RAM / disque : libellé, % écrit et barre (couleur = repère seulement)."""
        f = self.fonts
        for name, frac in gauges:
            w.blit(surface, f.tiny, name, w.GREY, (x, y))
            w.blit(surface, f.tiny, f"{frac * 100:.0f} %", w.SOFT, (x + max_w, y), anchor="topright")
            color = w.RED_LINE if frac >= 0.9 else (w.ORANGE if frac >= 0.7 else w.GREEN)
            w.bar(surface, pygame.Rect(x, y + 15, max_w, 6), frac, color)
            y += 27
        return y + 2

    def _wrap(self, surface, text, color, x, y, max_w, max_lines) -> int:
        from modules.system.news_screen import wrap_text
        for line in wrap_text(text, self.fonts.small, max_w, max_lines):
            w.blit(surface, self.fonts.small, line, color, (x, y), max_w)
            y += 20
        return y + 4

    def _draw_alerts(self, surface, view) -> None:
        f = self.fonts
        rect = ALERTS_RECT
        pygame.draw.rect(surface, w.PANEL_DARK, rect, border_radius=12)
        pygame.draw.rect(surface, w.BORDER, rect, width=1, border_radius=12)
        stamp = f"relevé {time.strftime('%H:%M:%S', time.localtime(view['ts']))}" if view["ts"] else "en attente du 1er relevé"
        if not view["alerts"]:
            w.state_icon(surface, OK if not view["offline"] else UNKNOWN, (rect.x + 22, rect.y + 24), 18)
            w.blit(surface, f.text, "Aucune alerte en cours" if not view["offline"]
                   else "Pi sans internet : supervision suspendue", w.SOFT, (rect.x + 40, rect.y + 24), anchor="midleft")
            w.blit(surface, f.tiny, f"touche une carte pour son détail · {stamp}", w.DIM,
                   (rect.right - 14, rect.bottom - 14), anchor="bottomright")
            return
        w.blit(surface, f.tiny, "ALERTES EN COURS", w.GREY, (rect.x + 14, rect.y + 10))
        if len(view["alerts"]) <= 3:
            w.blit(surface, f.tiny, stamp, w.DIM, (rect.right - 14, rect.y + 10), anchor="topright")
        y = rect.y + 40
        for level, raised, text, notified in view["alerts"][:3]:
            tag = "PANNE" if level == CRIT else "ATTENTION"
            surf = f.tiny.render(tag, True, w.BG)
            pill = pygame.Rect(rect.x + 14, y - 11, 112, 22)
            pygame.draw.rect(surface, w.RED_LINE if level == CRIT else w.ORANGE, pill, border_radius=5)
            w.mark(surface, level, (pill.x + 10, pill.centery), w.BG)
            surface.blit(surf, surf.get_rect(midleft=(pill.x + 20, pill.centery)))
            w.blit(surface, f.small, w.hhmm(raised), w.DIM, (pill.right + 12, y), anchor="midleft")
            note = "montre prévenue" if notified else "écran seul"
            nr = w.blit(surface, f.tiny, note, w.GREY, (rect.right - 14, y), anchor="midright")
            w.blit(surface, f.small, text, w.WHITE, (pill.right + 66, y), anchor="midleft",
                   max_w=nr.x - pill.right - 76)
            y += 28
        if len(view["alerts"]) > 3:
            n = len(view["alerts"]) - 3
            w.blit(surface, f.tiny, f"+ {n} autre{'s' if n > 1 else ''} : voir les détails", w.DIM,
                   (rect.right - 14, rect.y + 10), anchor="topright")

    # ---------------------------------------------------------------- entrées
    def handle_touch(self, pos: tuple[int, int]) -> str | None:
        if w.RETOUR_RECT.collidepoint(pos):
            return ACTION_BACK
        for card, rect in CARD_RECTS.items():
            if rect.collidepoint(pos):
                self.app.manual_screen = DETAIL[card]
                self.app.set_screen(DETAIL[card])
                return None
        return None
