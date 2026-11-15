"""Écran « Rentrer » : détail du serveur de l'app Rentrer (ouvert depuis l'écran Serveur).

Bandeau : verdict des trajets témoins (`/v1/status`) + temps de réponse de `/health`.
Gauche : conteneurs docker (état, santé, CPU/RAM, redémarrages, démarrés depuis) lus par
`pi-monitor` ; toucher un conteneur ouvre ses courbes CPU/RAM (`server_container`). Droite : données MOTIS (import, plan IDFM) et totaux `/v1/admin/stats`.
Bas : frise des 24 h du verdict (gardée sur le Pi, `history.py`) : une période dégradée ou
en panne est hachurée ET nommée au-dessus (pas seulement colorée).
"""

from __future__ import annotations

import time

import pygame

from screen import Screen

from . import widgets as w
from .monitor import CRIT, DOCKER_WORDS, OK, UNKNOWN, WARN

BANNER = pygame.Rect(24, 58, 752, 66)
CTR_AREA = pygame.Rect(24, 152, 456, 206)
DATA_RECT = pygame.Rect(494, 134, 282, 224)
FRISE = pygame.Rect(24, 396, 752, 22)
CANARY_LEVEL = {"ok": OK, "degraded": WARN, "down": CRIT}
CANARY_WORD = {"ok": "OK", "degraded": "dégradés", "down": "en panne", "unknown": "muets"}


class RentrerScreen(Screen):
    name = "server_rentrer"
    background_name = None
    bg_color = w.BG
    cycle = False

    def __init__(self, app):
        super().__init__(app)
        self.fonts = w.Fonts()
        self.module = app.modules.get("server")
        self._key = None
        self._drawn_at = 0.0
        self._names: list[str] = []      # conteneurs affichés, dans l'ordre des cartes

    def enter(self) -> None:
        self._key = None

    def draw(self, surface: pygame.Surface) -> list[pygame.Rect]:
        # Relevés lents (SQLite, sondes) : recalcul au plus 1×/s (Pi 3), sauf juste après l'entrée.
        if self._key is not None and time.monotonic() - self._drawn_at < 1.0:
            return []
        self._drawn_at = time.monotonic()
        mod = self.module
        probes = mod.probes.snapshot() if mod.probes else {}
        rp = probes.get("rentrer") or {}
        rep = (mod.link.report() if mod.link else {}) or {}
        now = time.time()
        segments = mod.history.canary_segments(now - 86400) if mod.history else []
        alerts = tuple(a.text for a in mod.monitor.alerts("rentrer"))
        key = (repr(rp), repr(rep.get("data")), rep.get("error"), len(segments),
               segments[-1] if segments else None, alerts, int(now // 60))
        if key == self._key:
            return []
        self._key = key
        surface.blit(self.bg, (0, 0))
        w.header(surface, self.fonts, "RENTRER · API trajets")
        self._banner(surface, rp, alerts, probes.get("ts"), now)
        self._containers(surface, rep)
        self._data(surface, rep.get("data") or {}, rp.get("stats") or {}, rp)
        self._frise(surface, segments, now)
        return [surface.get_rect()]

    # ------------------------------------------------------------------ parties
    def _banner(self, surface, rp, alerts, ts, now) -> None:
        f = self.fonts
        status = rp.get("status") or {}
        state = status.get("state") or ("injoignable" if rp and not rp.get("up") else "")
        level = CANARY_LEVEL.get(state, CRIT if state == "injoignable" else UNKNOWN)
        w.panel(surface, BANNER, level if level in (WARN, CRIT) else None)
        w.state_icon(surface, level, (BANNER.x + 30, BANNER.centery), 32)
        x = BANNER.x + 58
        word = CANARY_WORD.get(state, "API injoignable" if state == "injoignable" else "—")
        r = w.blit(surface, f.label, "Trajets témoins : ", w.WHITE, (x, BANNER.y + 10))
        w.blit(surface, f.label, word, w.LEVEL_COLOR[level], (r.right, BANNER.y + 10))
        second = alerts[0] if alerts else (status.get("message") or "")
        if second:
            color = w.LEVEL_COLOR[CRIT if level == CRIT else WARN] if alerts else w.GREY
            w.blit(surface, f.small, second, color, (x, BANNER.y + 40), max_w=430)
        right = BANNER.right - 14
        w.blit(surface, f.small, f"depuis {w.hhmm(status.get('since'))}", w.GREY, (right, BANNER.y + 12),
               anchor="topright")
        health = f"/health {rp['ms']} ms" if rp.get("ms") is not None else "/health —"
        w.blit(surface, f.small, f"{health} · relevé {w.ago(ts, now)}", w.GREY, (right, BANNER.y + 40),
               anchor="topright")

    def _containers(self, surface, rep) -> None:
        f = self.fonts
        data = rep.get("data") or {}
        ctrs = data.get("containers") or {}
        want = list(self.module.monitor.settings.services)
        names = want + [s for s, c in sorted(ctrs.items()) if s not in want and c.get("state") == "running"]
        up = sum(1 for s in want if (ctrs.get(s) or {}).get("state") == "running")
        title = f"CONTENEURS · {up} / {len(want)} actifs" if data else "CONTENEURS"
        w.blit(surface, f.tiny, title, w.GREY, (CTR_AREA.x, CTR_AREA.y - 18))
        self._names = names[:6] if data else []
        if not data:
            msg = rep.get("error") or "en attente du relevé SSH…"
            from modules.system.news_screen import wrap_text
            y = CTR_AREA.y + 10
            for line in wrap_text(msg, f.small, CTR_AREA.w - 20, 4):
                w.blit(surface, f.small, line, w.GREY, (CTR_AREA.x + 10, y))
                y += 22
            return
        now = time.time()
        for i, svc in enumerate(self._names):
            c = ctrs.get(svc)
            rect = self._card_rect(i)
            running = c is not None and c.get("state") == "running"
            bad = not running or c.get("health") == "unhealthy"
            level = (CRIT if not running else WARN) if bad else None
            w.panel(surface, rect, level, fill=w.PANEL_DARK)
            x, y = rect.x + 10, rect.y + 8
            w.blit(surface, f.text, svc, w.WHITE, (x, y), rect.w - 20)
            if c is None:
                word = "absent"
            else:
                word = DOCKER_WORDS.get(c.get("state"), c.get("state") or "?")
                if c.get("health") == "healthy":
                    word += " · sain"
                elif c.get("health") == "unhealthy":
                    word += " · malade"
                elif c.get("health") == "starting":
                    word += " · démarre"
            st_level = OK if running and c.get("health") != "unhealthy" else (WARN if running else CRIT)
            w.state_icon(surface, st_level, (x + 7, y + 34), 14)
            w.blit(surface, f.small, word, w.LEVEL_COLOR[st_level], (x + 20, y + 34), rect.w - 34,
                   anchor="midleft")
            if c is not None:
                w.blit(surface, f.small, f"CPU {w.cpu_text(c.get('cpu'))} · {w.size_text(c.get('mem'))}", w.SOFT,
                       (x, y + 50), rect.w - 20)
                w.arrow(surface, w.DIM, (rect.right - 12, y + 9))
                since = w.duration(now - c["started"]) if c.get("started") else "—"
                w.blit(surface, f.tiny, f"{c.get('restarts', 0)} redém. · depuis {since}", w.DIM,
                       (x, y + 72), rect.w - 20)

    @staticmethod
    def _card_rect(i: int) -> pygame.Rect:
        cw, ch, gap = (CTR_AREA.w - 16) // 3, (CTR_AREA.h - 8) // 2, 8
        return pygame.Rect(CTR_AREA.x + (i % 3) * (cw + gap), CTR_AREA.y + (i // 3) * (ch + gap), cw, ch)

    def _data(self, surface, data, stats, rp) -> None:
        f = self.fonts
        rect = DATA_RECT
        pygame.draw.rect(surface, w.PANEL, rect, border_radius=12)
        w.blit(surface, f.tiny, "DONNÉES", w.GREY, (rect.x + 12, rect.y + 10))
        y = rect.y + 32
        rows = []
        imp = data.get("import") or {}
        if imp.get("running"):
            rows.append(("Import MOTIS", f"en cours depuis {w.hhmm(imp.get('lock_at'))}", w.ORANGE))
        elif imp.get("started"):
            ok = imp.get("ok") and imp["ok"] >= imp["started"]
            rows.append(("Import MOTIS", f"{w.hhmm(imp.get('ok') if ok else imp['started'])} · "
                         + ("réussi" if ok else "ÉCHEC"), w.WHITE if ok else w.RED))
        plan = data.get("plan") or {}
        if data:
            pub = plan.get("published", "")
            rows.append(("Plan IDFM", f"publié {pub[11:16]}" if len(pub) >= 16 else "—", w.WHITE))
            if plan.get("failed"):
                rows.append(("", "import en ÉCHEC", w.RED))
            elif plan.get("pending"):
                rows.append(("", f"pas importé ({w.ago(plan.get('bridge_at'))})", w.ORANGE))
            else:
                rows.append(("", f"importé {w.hhmm(plan.get('imported_at'))}", w.GREEN))
            if plan.get("networks_failed") is not None:
                rows.append(("Réseaux en échec", str(plan["networks_failed"]),
                             w.ORANGE if plan["networks_failed"] else w.WHITE))
        if stats:
            today = stats.get("today") or {}
            rows.append(("Utilisateurs", f"{stats.get('users', 0)} · {stats.get('destinations', 0)} destin.", w.WHITE))
            failed = today.get("pushFailed", 0)
            rows.append(("Notifs aujourd'hui", f"{today.get('pushSent', 0)} · {failed} refusée{'s' if failed > 1 else ''}",
                         w.ORANGE if failed else w.WHITE))
            if stats.get("liveActivities"):
                rows.append(("Live Activities", str(stats["liveActivities"]), w.WHITE))
        elif rp.get("stats_error"):
            rows.append(("Totaux", rp["stats_error"], w.GREY))
        if rp.get("cert_days") is not None:
            rows.append(("Certificat", f"expire dans {rp['cert_days']} j", w.WHITE))
        if not rows:
            rows.append(("", "en attente des relevés…", w.GREY))
        for key, value, color in rows[:9]:
            w.kv(surface, f, rect, y, key, value, color)
            y += 21

    def _frise(self, surface, segments, now) -> None:
        f = self.fonts
        start = now - 86400
        w.blit(surface, f.tiny, "TRAJETS TÉMOINS · 24 H", w.GREY, (FRISE.x, FRISE.y - 22))
        pygame.draw.rect(surface, w.PANEL_DARK, FRISE)
        worst = None
        for a, b, state in segments:
            x0 = FRISE.x + int((a - start) / 86400 * FRISE.w)
            x1 = FRISE.x + int((b - start) / 86400 * FRISE.w)
            rect = pygame.Rect(x0, FRISE.y, max(2, x1 - x0), FRISE.h)
            if state == "ok":
                pygame.draw.rect(surface, (31, 74, 48), rect)
            elif state == "degraded":
                w.hatch(surface, rect, w.ORANGE, (58, 42, 16))
            elif state in ("down", "injoignable"):
                w.hatch(surface, rect, w.RED_LINE, (60, 20, 24))
                pygame.draw.line(surface, w.RED_LINE, (rect.x, rect.centery), (rect.right, rect.centery), 2)
            else:
                pygame.draw.rect(surface, w.TRACK, rect)
            if state != "ok":
                worst = (a, b, state)
        pygame.draw.rect(surface, w.BORDER, FRISE, width=1)
        if worst:
            a, b, state = worst
            word = {"degraded": "dégradé", "down": "panne", "injoignable": "API injoignable"}.get(state, "inconnu")
            level = WARN if state == "degraded" else (CRIT if state in ("down", "injoignable") else UNKNOWN)
            r = w.blit(surface, f.tiny, f"dernier incident : {word} {w.hhmm(a)}–{w.hhmm(b)}",
                       w.LEVEL_COLOR[level], (FRISE.right, FRISE.y - 22), anchor="topright")
            w.state_icon(surface, level, (r.x - 10, r.centery), 12)
        elif not segments:
            w.blit(surface, f.tiny, "historique en cours de collecte", w.DIM, (FRISE.right, FRISE.y - 22),
                   anchor="topright")
        for i in range(9):
            label = "maint." if i == 8 else f"{time.localtime(start + i * 3 * 3600).tm_hour} h"
            anchor = "midtop" if 0 < i < 8 else ("topleft" if i == 0 else "topright")
            w.blit(surface, f.tiny, label, w.DIM,
                   (FRISE.x + i * FRISE.w // 8, FRISE.bottom + 6), anchor=anchor)
        legend = "vert = OK · hachuré = dégradé · barré = panne · gris = inconnu"
        w.blit(surface, f.tiny, legend, w.DIM, (FRISE.x, FRISE.bottom + 26))

    def handle_touch(self, pos: tuple[int, int]) -> str | None:
        if w.RETOUR_RECT.collidepoint(pos):
            self.app.manual_screen = "server"
            self.app.set_screen("server")
            return None
        for i, svc in enumerate(self._names):
            if self._card_rect(i).collidepoint(pos):
                self.module.selected_container = svc
                self.app.manual_screen = "server_container"
                self.app.set_screen("server_container")
                break
        return None
