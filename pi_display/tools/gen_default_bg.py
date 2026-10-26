"""Retouche le fond de l'écran d'accueil : bake les panneaux par-dessus l'art.

Part de `assets/default_base.png` (l'illustration d'origine) et dessine les
cadres de la mise en page actuelle de l'accueil :
  - panneau horloge/date (haut droite) ;
  - panneau actualité à 3 lignes (sous l'horloge) avec séparateurs ;
  - onglet « France Info » (haut gauche).

Écrit `assets/default.png`. Idempotent (toujours régénéré depuis la base).
Lancer : `.\.venv\Scripts\python pi_display\tools\gen_default_bg.py`

⚠️ Si tu changes une géométrie ici, réaligne les constantes correspondantes en
tête de `modules/system/default_screen.py` (elles doivent rester identiques).
"""

from pathlib import Path

from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parent.parent / "assets"

# Panneaux : (x0, y0, x1, y1). Doivent recouvrir les anciens panneaux du fond.
CLOCK_PANEL = (250, 48, 792, 286)
NEWS_PANEL = (312, 290, 792, 476)
TAB = (18, 12, 204, 52)

# Séparateurs internes du panneau actu (bornes des 3 lignes).
NEWS_INNER_X = (330, 774)
NEWS_HEADER_UNDERLINE_Y = 323
NEWS_DIVIDER_Y = (375, 424)

FILL = (11, 17, 32)
BORDER = (44, 58, 90)
LINE = (34, 46, 74)
RADIUS = 18


def main() -> None:
    base = ASSETS / "default_base.png"
    if not base.exists():
        raise SystemExit(f"Base introuvable : {base} (copie default.png -> default_base.png)")
    img = Image.open(base).convert("RGB")
    draw = ImageDraw.Draw(img)

    for rect in (CLOCK_PANEL, NEWS_PANEL):
        draw.rounded_rectangle(rect, radius=RADIUS, fill=FILL, outline=BORDER, width=2)
    draw.rounded_rectangle(TAB, radius=12, fill=FILL, outline=BORDER, width=2)

    # Séparateurs du panneau actu.
    x0, x1 = NEWS_INNER_X
    draw.line((x0, NEWS_HEADER_UNDERLINE_Y, x1, NEWS_HEADER_UNDERLINE_Y), fill=LINE, width=1)
    for y in NEWS_DIVIDER_Y:
        draw.line((x0, y, x1, y), fill=LINE, width=1)

    out = ASSETS / "default.png"
    img.save(out)
    print(f"[gen] écrit {out}")


if __name__ == "__main__":
    main()
