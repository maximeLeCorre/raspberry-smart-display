"""Écran de supervision/contrôle d'un petit serveur (code-drawn, pas de PNG).

Haut : titre + badge connexion (en ligne/hors ligne) + RETOUR. Milieu : trois
jauges (CPU, RAM, disque) + ligne uptime/température, puis courbes CPU/RAM des
dernières minutes (`ServerLink.history()`). Bas : état du service (badge
actif/inactif) et boutons Démarrer / Arrêter / Redémarrer.

Les données viennent de `ServerLink.snapshot()` (le Pi sonde le serveur en SSH,
voir `server_link.py`). Les actions partent par `App.async_call` (hors boucle de
rendu) ; pendant l'exécution les boutons sont neutralisés et une ligne d'état
affiche l'avancement puis le résultat.
"""

from __future__ import annotations

import time

import pygame

from inputs import ACTION_BACK
from screen import Screen

from .server_link import get_link

# ------------------------------------------------------------------- couleurs
BG = (10, 14, 26)
WHITE = (238, 240, 245)
GREY = (150, 165, 195)
DIM = (92, 106, 134)
GOLD = (210, 175, 95)
GREEN = (110, 210, 130)
ORANGE = (230, 170, 70)
RED = (228, 86, 86)
BLUE = (96, 150, 235)
# Courbes : paire Okabe-Ito (lisible par les daltoniens), contraste de
# luminosité en plus de la teinte ; seule la courbe CPU a une aire remplie.
CPU_COL = (240, 165, 30)       # orange
RAM_COL = (110, 195, 245)      # bleu ciel
TRACK = (30, 40, 62)
PANEL = (24, 32, 52)

# -------------------------------------------------------------------- géométrie
RETOUR_RECT = pygame.Rect(700, 8, 92, 38)
BADGE_RECT = pygame.Rect(470, 10, 210, 34)      # badge connexion (en-tête)

METRICS_AREA = pygame.Rect(0, 62, 800, 126)     # zone effaçable des jauges
LABEL_X = 40
BAR_X, BAR_W, BAR_H = 200, 360, 22
VALUE_X = BAR_X + BAR_W + 20
GAUGE_Y = (80, 114, 148)                         # centres des 3 jauges
INFO_Y = 168

CHART_AREA = pygame.Rect(0, 186, 800, 112)       # zone effaçable des courbes
CHART = pygame.Rect(40, 190, 720, 106)           # panneau des courbes
PLOT = pygame.Rect(CHART.x + 40, CHART.y + 30, CHART.w - 92, CHART.h - 38)  # marge droite = étiquettes

SVC_AREA = pygame.Rect(0, 300, 800, 180)         # zone effaçable service+boutons
SVC_LABEL_Y = 328
SVC_BADGE = pygame.Rect(520, 312, 240, 34)
BTN_W, BTN_H, BTN_Y = 190, 62, 372
START_BTN = pygame.Rect(40, BTN_Y, BTN_W, BTN_H)
STOP_BTN = pygame.Rect(305, BTN_Y, BTN_W, BTN_H)
RESTART_BTN = pygame.Rect(570, BTN_Y, BTN_W, BTN_H)
ACTION_Y = 456

_VERB = {"start": "démarrage", "stop": "arrêt", "restart": "redémarrage"}


def _fmt_bytes(n: int) -> str:
    """Octets -> Go (1 décimale)."""
    return f"{n / 1024 ** 3:.1f} Go"


def _fmt_uptime(sec: int) -> str:
    if sec <= 0:
        return "—"
    j, rem = divmod(int(sec), 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    return f"{j} j {h:02d}:{m:02d}" if j else f"{h:02d}:{m:02d}"


class ServerScreen(Screen):
    name = "server"
    background_name = None
    bg_color = BG
    cycle = True

    def __init__(self, app):
        super().__init__(app)
        self.font_title = pygame.font.Font(None, 40)
        self.font_label = pygame.font.Font(None, 30)
        self.font_value = pygame.font.Font(None, 28)
        self.font_btn = pygame.font.Font(None, 30)
        self.font_small = pygame.font.Font(None, 24)
        self.font_tiny = pygame.font.Font(None, 20)

        self.link = get_link(app)
        self.service = self.link.services[0] if (self.link and self.link.services) else None

        self._pending = False            # une action est en cours
        self._action_msg = ""            # dernier message d'action
        self._action_ts = 0.0            # horodatage du dernier résultat

        self._chrome_drawn = False
        self._badge_key = None
        self._metrics_key = None
        self._chart_key = None
        self._svc_key = None
        self._action_key = None

    def enter(self) -> None:
        self._chrome_drawn = False
        self._badge_key = None
        self._metrics_key = None
        self._chart_key = None
        self._svc_key = None
        self._action_key = None

    # ------------------------------------------------------------------- rendu
    def draw(self, surface: pygame.Surface) -> list[pygame.Rect]:
        dirty: list[pygame.Rect] = []
        snap = self.link.snapshot() if self.link else {"online": False}

        if not self._chrome_drawn:
            dirty.append(self._draw_chrome(surface))
            self._chrome_drawn = True

        # Badge de connexion.
        online = bool(snap.get("online"))
        badge_key = (online, self.link is not None)
        if badge_key != self._badge_key:
            dirty.append(self._draw_badge(surface, online))
            self._badge_key = badge_key

        # Jauges + infos (redessinées quand une valeur change).
        mkey = (
            round(snap.get("cpu_pct") or -1),
            snap.get("mem_used", 0) >> 24, snap.get("mem_total", 0) >> 24,
            snap.get("disk_used", 0) >> 28, snap.get("disk_total", 0) >> 28,
            int(snap.get("uptime", 0)), snap.get("temp_c"),
            online, self.link is not None, self._backup_text(),
        )
        if mkey != self._metrics_key:
            dirty.append(self._draw_metrics(surface, snap, online))
            self._metrics_key = mkey

        # Courbes CPU/RAM : redessinées à chaque nouveau point.
        hist = self.link.history() if self.link else []
        ckey = (len(hist), hist[-1][0] if hist else 0, online, self.link is not None)
        if ckey != self._chart_key:
            dirty.append(self._draw_chart(surface, hist, online))
            self._chart_key = ckey

        # Service : badge d'état + boutons.
        status = self._status(snap)
        skey = (status, self._pending, online)
        if skey != self._svc_key:
            dirty.append(self._draw_service(surface, status, online))
            self._svc_key = skey

        # Ligne d'action (avec « il y a Ns » qui défile).
        akey = (self._action_msg, self._pending,
                int(time.monotonic() - self._action_ts) if self._action_ts else -1)
        if akey != self._action_key:
            dirty.append(self._draw_action_line(surface))
            self._action_key = akey

        return dirty

    def _draw_chrome(self, surface: pygame.Surface) -> pygame.Rect:
        title = "SERVEUR"
        snap = self.link.snapshot() if self.link else {}
        if snap.get("host"):
            title = f"SERVEUR · {snap['host']}"
        surface.blit(self.font_title.render(title, True, WHITE), (24, 14))
        pygame.draw.rect(surface, GOLD, RETOUR_RECT, width=2, border_radius=8)
        label = self.font_small.render("RETOUR", True, GOLD)
        surface.blit(label, label.get_rect(center=RETOUR_RECT.center))
        return pygame.Rect(0, 0, 800, 54)

    def _draw_badge(self, surface: pygame.Surface, online: bool) -> pygame.Rect:
        self.clear_region(surface, BADGE_RECT)
        if self.link is None:
            text, color = "non configuré", DIM
        elif online:
            text, color = "en ligne", GREEN
        else:
            text, color = "hors ligne", RED
        pygame.draw.circle(surface, color, (BADGE_RECT.right - 90, BADGE_RECT.centery), 7)
        surf = self.font_small.render(text, True, color)
        surface.blit(surf, (BADGE_RECT.right - 76, BADGE_RECT.centery - surf.get_height() // 2))
        return BADGE_RECT

    def _draw_metrics(self, surface, snap: dict, online: bool) -> pygame.Rect:
        self.clear_region(surface, METRICS_AREA)
        if self.link is None:
            msg = self.font_label.render(
                "Serveur non configuré — renseigne [server] dans config.toml.", True, DIM)
            surface.blit(msg, (LABEL_X, GAUGE_Y[0] - 12))
            return METRICS_AREA

        cpu = snap.get("cpu_pct")
        cpu_frac = (cpu or 0) / 100.0
        cpu_val = f"{cpu:.0f} %" if cpu is not None else "—"
        if cpu is not None:
            cpu_val += f"  ({snap.get('nproc', 1)} cœurs)"
        self._gauge(surface, GAUGE_Y[0], "CPU", cpu_frac, cpu_val,
                    self._load_color(cpu_frac))

        mem_used, mem_total = snap.get("mem_used", 0), snap.get("mem_total", 0)
        mem_frac = mem_used / mem_total if mem_total else 0
        self._gauge(surface, GAUGE_Y[1], "RAM", mem_frac,
                    f"{_fmt_bytes(mem_used)} / {_fmt_bytes(mem_total)}" if mem_total else "—",
                    self._load_color(mem_frac))

        dsk_used, dsk_total = snap.get("disk_used", 0), snap.get("disk_total", 0)
        dsk_frac = dsk_used / dsk_total if dsk_total else 0
        self._gauge(surface, GAUGE_Y[2], "DISQUE", dsk_frac,
                    f"{_fmt_bytes(dsk_used)} / {_fmt_bytes(dsk_total)}" if dsk_total else "—",
                    self._load_color(dsk_frac))

        # Ligne uptime / température.
        info = f"uptime {_fmt_uptime(snap.get('uptime', 0))}"
        if snap.get("temp_c") is not None:
            info += f"        temp {snap['temp_c']:.0f} °C"
        color = GREY if online else DIM
        surface.blit(self.font_small.render(info, True, color), (LABEL_X, INFO_Y))

        # Sauvegarde quotidienne des bases du Pi (à droite de la même ligne).
        backup = self._backup_text()
        if backup:
            text, failed = backup
            surf = self.font_small.render(text, True, RED if failed else GREY)
            surface.blit(surf, surf.get_rect(topright=(760, INFO_Y)))
        return METRICS_AREA

    def _backup_text(self):
        """(texte, en_échec) de la dernière sauvegarde, ou None si désactivée."""
        backup = getattr(self.link, "backup", None)
        if backup is None:
            return None
        st = backup.status()
        if st["ok"] is False:
            return "sauvegarde en échec", True
        last = st["last"]
        if not last:
            return "sauvegarde : aucune", False
        if last == time.strftime("%Y-%m-%d") and st["ts"]:
            return f"sauvegarde : auj. {time.strftime('%H:%M', time.localtime(st['ts']))}", False
        return f"sauvegarde : {last[8:10]}/{last[5:7]}", False

    def _draw_chart(self, surface, hist: list, online: bool) -> pygame.Rect:
        """Courbes CPU (orange, aire remplie) et RAM (bleu ciel, trait seul) en %."""
        self.clear_region(surface, CHART_AREA)
        if self.link is None:
            return CHART_AREA
        pygame.draw.rect(surface, PANEL, CHART, border_radius=8)

        # Grille 0/50/100 % (seul 50 % est légendé : 0 et 100 vont de soi).
        for pct in (0, 50, 100):
            y = PLOT.bottom - round(PLOT.h * pct / 100)
            pygame.draw.line(surface, TRACK, (PLOT.x, y), (PLOT.right, y))
        lab = self.font_tiny.render("50%", True, DIM)
        surface.blit(lab, (PLOT.x - lab.get_width() - 6, PLOT.centery - lab.get_height() // 2))

        # Légende (dernières valeurs) + fenêtre.
        last = hist[-1] if hist else (0, None, None)
        x = CHART.x + 12
        for name, val, color in (("CPU", last[1], CPU_COL), ("RAM", last[2], RAM_COL)):
            text = f"{name} {val:.0f} %" if val is not None else f"{name} —"
            surf = self.font_small.render(text, True, color if online else DIM)
            pygame.draw.circle(surface, color, (x + 5, CHART.y + 13), 5)
            surface.blit(surf, (x + 16, CHART.y + 13 - surf.get_height() // 2))
            x += 16 + surf.get_width() + 24
        span = self.link.history_seconds
        win = self.font_tiny.render(f"{span // 60} dernières min", True, DIM)
        surface.blit(win, (CHART.right - win.get_width() - 12, CHART.y + 6))

        if len(hist) < 2:
            msg = self.font_small.render(
                "collecte en cours…" if online else "aucune donnée (hors ligne)", True, DIM)
            surface.blit(msg, msg.get_rect(center=PLOT.center))
            return CHART_AREA

        # Abscisse = temps, ancrée sur le dernier point ; trou (hors ligne) si
        # deux points sont trop espacés, ou valeur absente (1er relevé CPU).
        t_end = hist[-1][0]
        max_gap = 3 * self.link.poll_seconds
        series = []
        for idx, color, name in ((1, CPU_COL, "CPU"), (2, RAM_COL, "RAM")):
            segments, cur, prev_t = [], [], None
            for p in hist:
                t, v = p[0], p[idx]
                if v is None or t < t_end - span or (prev_t is not None and t - prev_t > max_gap):
                    if cur:
                        segments.append(cur)
                    cur = []
                if v is not None and t >= t_end - span:
                    px = PLOT.right - (t_end - t) / span * PLOT.w
                    py = PLOT.bottom - max(0.0, min(100.0, v)) / 100.0 * PLOT.h
                    cur.append((px, py))
                prev_t = t
            if cur:
                segments.append(cur)
            series.append((segments, color, name))

        # Aire translucide sous la courbe CPU seulement (repère non coloré).
        overlay = pygame.Surface(PLOT.size, pygame.SRCALPHA)
        for seg in series[0][0]:
            if len(seg) >= 2:
                pts = [(x - PLOT.x, y - PLOT.y) for x, y in seg]
                poly = pts + [(pts[-1][0], PLOT.h), (pts[0][0], PLOT.h)]
                pygame.draw.polygon(overlay, (*CPU_COL, 55), poly)
        surface.blit(overlay, PLOT.topleft)

        # Traits, puis nom de la courbe au bout du dernier segment.
        ends = []
        for segments, color, name in series:
            if not online:
                color = DIM
            for seg in segments:
                if len(seg) >= 2:
                    pygame.draw.lines(surface, color, False, seg, 3)
                else:
                    pygame.draw.circle(surface, color, (round(seg[0][0]), round(seg[0][1])), 2)
            if segments:
                ends.append([segments[-1][-1][1], name, color])
        # Écarte les deux étiquettes si les courbes finissent au même niveau.
        if len(ends) == 2 and abs(ends[0][0] - ends[1][0]) < 16:
            mid = (ends[0][0] + ends[1][0]) / 2
            lo, hi = sorted(ends, key=lambda e: e[0])
            lo[0], hi[0] = mid - 8, mid + 8
        for y, name, color in ends:
            lab = self.font_small.render(name, True, color)
            y = max(PLOT.y, min(PLOT.bottom, y))
            surface.blit(lab, (PLOT.right + 6, round(y) - lab.get_height() // 2))
        return CHART_AREA

    def _gauge(self, surface, cy, label, frac, value_text, color):
        frac = max(0.0, min(1.0, frac))
        surface.blit(self.font_label.render(label, True, GREY),
                     (LABEL_X, cy - self.font_label.get_height() // 2))
        track = pygame.Rect(BAR_X, cy - BAR_H // 2, BAR_W, BAR_H)
        pygame.draw.rect(surface, TRACK, track, border_radius=6)
        if frac > 0:
            fill = pygame.Rect(track.x, track.y, max(4, int(BAR_W * frac)), BAR_H)
            pygame.draw.rect(surface, color, fill, border_radius=6)
        pygame.draw.rect(surface, PANEL, track, width=1, border_radius=6)
        surface.blit(self.font_value.render(value_text, True, WHITE),
                     (VALUE_X, cy - self.font_value.get_height() // 2))

    @staticmethod
    def _load_color(frac: float):
        if frac >= 0.9:
            return RED
        if frac >= 0.7:
            return ORANGE
        return GREEN

    def _draw_service(self, surface, status: str, online: bool) -> pygame.Rect:
        self.clear_region(surface, SVC_AREA)
        if self.service is None:
            surface.blit(self.font_label.render("Aucun service configuré.", True, DIM),
                         (LABEL_X, SVC_LABEL_Y))
            return SVC_AREA

        surface.blit(self.font_label.render(f"Service : {self.service['label']}", True, WHITE),
                     (LABEL_X, SVC_LABEL_Y))
        # Badge d'état du service.
        text, color = self._status_text(status)
        pygame.draw.circle(surface, color, (SVC_BADGE.x + 12, SVC_BADGE.centery), 7)
        surf = self.font_value.render(text, True, color)
        surface.blit(surf, (SVC_BADGE.x + 28, SVC_BADGE.centery - surf.get_height() // 2))

        # Boutons neutralisés si une action est en cours ou le serveur injoignable.
        active = status == "active"
        ready = online and not self._pending
        self._button(surface, START_BTN, "Démarrer", enabled=ready and not active)
        self._button(surface, STOP_BTN, "Arrêter", enabled=ready and active)
        self._button(surface, RESTART_BTN, "Redémarrer", enabled=ready and active)
        return SVC_AREA

    def _button(self, surface, rect, label, enabled: bool):
        fill = PANEL if enabled else (18, 22, 34)
        border = GOLD if enabled else DIM
        text_col = WHITE if enabled else DIM
        pygame.draw.rect(surface, fill, rect, border_radius=10)
        pygame.draw.rect(surface, border, rect, width=2, border_radius=10)
        surf = self.font_btn.render(label, True, text_col)
        surface.blit(surf, surf.get_rect(center=rect.center))

    def _draw_action_line(self, surface) -> pygame.Rect:
        band = pygame.Rect(0, ACTION_Y - 4, 800, 28)
        self.clear_region(surface, band)
        if not self._action_msg:
            return band
        text = self._action_msg
        color = GOLD if self._pending else GREY
        if not self._pending and self._action_ts:
            text += f"   (il y a {int(time.monotonic() - self._action_ts)} s)"
        surface.blit(self.font_small.render(text, True, color), (LABEL_X, ACTION_Y))
        return band

    # --------------------------------------------------------------- helpers
    def _status(self, snap: dict) -> str:
        if self.service is None:
            return ""
        return snap.get("services", {}).get(self.service["unit"], "")

    @staticmethod
    def _status_text(status: str):
        if status == "active":
            return "actif", GREEN
        if status in ("inactive", "failed", "deactivating", "activating"):
            label = {"inactive": "arrêté", "failed": "en échec",
                     "deactivating": "arrêt…", "activating": "démarrage…"}[status]
            return label, (RED if status in ("inactive", "failed") else ORANGE)
        return "inconnu", DIM

    # ---------------------------------------------------------------- entrées
    def handle_touch(self, pos: tuple[int, int]) -> str | None:
        if RETOUR_RECT.collidepoint(pos):
            return ACTION_BACK
        if self.service is None or self.link is None or self._pending:
            return None
        snap = self.link.snapshot()
        if not snap.get("online"):
            return None
        active = self._status(snap) == "active"
        if START_BTN.collidepoint(pos) and not active:
            self._trigger("start")
        elif STOP_BTN.collidepoint(pos) and active:
            self._trigger("stop")
        elif RESTART_BTN.collidepoint(pos) and active:
            self._trigger("restart")
        return None

    def _trigger(self, action: str) -> None:
        self._pending = True
        self._action_msg = f"{_VERB[action]}…"
        self._action_ts = 0.0
        service = self.service

        def work():
            return self.link.run_action(service, action)

        def done(res):
            self._pending = False
            self._action_ts = time.monotonic()
            if res and res.get("ok"):
                self._action_msg = f"{_VERB[action]} OK"
            else:
                err = (res or {}).get("error") or "serveur injoignable"
                self._action_msg = f"échec du {_VERB[action]} : {err}"

        self.app.async_call(work, done)
