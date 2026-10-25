"""Génère des fonds placeholder (PNG 800x480) pour chaque mode.

Usage :
    python tools/gen_backgrounds.py

Ces fonds sont volontairement simples (dégradé + titre). Ils seront remplacés
plus tard par de vrais visuels. L'appli sait fonctionner même sans ces PNG
(repli sur une couleur unie), mais les générer donne un rendu plus lisible.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

WIDTH, HEIGHT = 800, 480
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"


def gradient(top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    """Crée un dégradé vertical."""
    img = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(img)
    for y in range(HEIGHT):
        ratio = y / (HEIGHT - 1)
        color = tuple(int(top[i] + (bottom[i] - top[i]) * ratio) for i in range(3))
        draw.line([(0, y), (WIDTH, y)], fill=color)
    return img


def make_default() -> Image.Image:
    img = gradient((15, 23, 42), (30, 41, 70))
    return img


def make_lol() -> Image.Image:
    img = gradient((8, 12, 24), (20, 16, 10))
    draw = ImageDraw.Draw(img)
    # Fine ligne dorée sous le titre, pour délimiter l'en-tête.
    draw.line([(40, 78), (WIDTH - 40, 78)], fill=(120, 95, 40), width=2)
    return img


def make_champselect() -> Image.Image:
    img = gradient((10, 14, 26), (18, 22, 40))
    draw = ImageDraw.Draw(img)
    draw.line([(40, 70), (WIDTH - 40, 70)], fill=(120, 95, 40), width=2)
    return img


def main():
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    make_default().save(ASSETS_DIR / "default.png")
    make_lol().save(ASSETS_DIR / "lol.png")
    make_champselect().save(ASSETS_DIR / "champselect.png")
    print(f"Fonds générés dans {ASSETS_DIR}")


if __name__ == "__main__":
    main()
