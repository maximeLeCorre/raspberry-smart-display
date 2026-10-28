"""Retouche le fond de l'écran d'accueil : bake les panneaux par-dessus l'art.

Part de `assets/default_base.png` (l'illustration d'origine, chat à gauche) et
dessine les cadres de la mise en page de l'accueil :
  - panneau horloge/date (haut droite) ;
  - bandeau d'actualité (une ligne, sous l'horloge) ;
  - dock des tuiles (bas) — les tuiles elles-mêmes sont dessinées par le code.

Les panneaux recouvrent les anciens cadres présents dans la base.
Écrit `assets/default.png`. Idempotent (toujours régénéré depuis la base).
Lancer : `.\.venv\Scripts\python pi_display\tools\gen_default_bg.py`

⚠️ Si tu changes une géométrie ici, réaligne les constantes correspondantes en
tête de `modules/system/default_screen.py` (elles doivent rester identiques).
"""

from pathlib import Path

from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parent.parent / "assets"

# Panneaux : (x0, y0, x1, y1).
CLOCK_PANEL = (240, 12, 792, 282)
NEWS_STRIP = (240, 292, 792, 350)
DOCK = (240, 360, 792, 472)

FILL = (11, 17, 32)
BORDER = (44, 58, 90)
RADIUS = 18


def main() -> None:
    base = ASSETS / "default_base.png"
    if not base.exists():
        raise SystemExit(f"Base introuvable : {base} (copie default.png -> default_base.png)")
    img = Image.open(base).convert("RGB")
    draw = ImageDraw.Draw(img)

    draw.rounded_rectangle(CLOCK_PANEL, radius=RADIUS, fill=FILL, outline=BORDER, width=2)
    draw.rounded_rectangle(NEWS_STRIP, radius=14, fill=FILL, outline=BORDER, width=2)
    # Dock : fond plein sans bordure (les tuiles portent leur propre cadre).
    draw.rounded_rectangle(DOCK, radius=RADIUS, fill=FILL)

    out = ASSETS / "default.png"
    img.save(out)
    print(f"[gen] écrit {out}")


if __name__ == "__main__":
    main()
