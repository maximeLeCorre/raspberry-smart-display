"""Génère les fonds (PNG 800x480) pour chaque mode.

Style : sombre et sobre, inspiré UI « hextech » — dégradé vertical, halo
d'accent coloré, fine grille, vignette sur les bords. Chaque mode a sa teinte.
Les fonds laissent les zones de contenu lisibles (pas de ligne en travers).

Usage :  python tools/gen_backgrounds.py
L'appli sait fonctionner sans ces PNG (repli couleur unie), mais ils rendent
l'affichage bien plus agréable.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

WIDTH, HEIGHT = 800, 480
ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"


def gradient(top: tuple[int, int, int], bottom: tuple[int, int, int]) -> Image.Image:
    img = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(img)
    for y in range(HEIGHT):
        r = y / (HEIGHT - 1)
        draw.line([(0, y), (WIDTH, y)],
                  fill=tuple(int(top[i] + (bottom[i] - top[i]) * r) for i in range(3)))
    return img


def add_glow(img: Image.Image, center, color, radius: int, alpha: int) -> Image.Image:
    """Ajoute un halo coloré diffus (profondeur)."""
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    cx, cy = center
    d.ellipse([cx - radius, cy - radius, cx + radius, cy + radius],
              fill=color + (alpha,))
    overlay = overlay.filter(ImageFilter.GaussianBlur(radius // 2))
    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


def add_grid(img: Image.Image, step: int = 40, alpha: int = 9) -> Image.Image:
    """Fine grille régulière, très discrète."""
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(overlay)
    for x in range(0, WIDTH, step):
        d.line([(x, 0), (x, HEIGHT)], fill=(255, 255, 255, alpha))
    for y in range(0, HEIGHT, step):
        d.line([(0, y), (WIDTH, y)], fill=(255, 255, 255, alpha))
    return Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


def add_vignette(img: Image.Image) -> Image.Image:
    """Assombrit les bords pour recentrer le regard."""
    mask = Image.new("L", (WIDTH, HEIGHT), 0)
    d = ImageDraw.Draw(mask)
    d.ellipse([-WIDTH * 0.15, -HEIGHT * 0.25, WIDTH * 1.15, HEIGHT * 1.25], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(130))
    dark = Image.new("RGB", (WIDTH, HEIGHT), (0, 0, 0))
    return Image.composite(img, dark, mask)


def top_accent(img: Image.Image, color: tuple[int, int, int]) -> Image.Image:
    """Fine ligne d'accent tout en haut (hairline)."""
    d = ImageDraw.Draw(img)
    d.line([(0, 0), (WIDTH, 0)], fill=color, width=3)
    return img


def compose(base_top, base_bottom, glow_color, accent) -> Image.Image:
    img = gradient(base_top, base_bottom)
    img = add_glow(img, (WIDTH // 2, -40), glow_color, 420, 70)
    img = add_grid(img)
    img = add_vignette(img)
    img = top_accent(img, accent)
    return img


def main():
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    # default : navy profond, halo bleu froid.
    compose((14, 20, 36), (20, 28, 48), (60, 100, 185), (120, 150, 210)
            ).save(ASSETS_DIR / "default.png")
    # champselect : navy + or, halo doré.
    compose((12, 16, 30), (24, 22, 40), (150, 120, 55), (210, 175, 95)
            ).save(ASSETS_DIR / "champselect.png")
    # lol : plus sombre, halo rouge discret (ambiance partie).
    compose((8, 12, 22), (18, 14, 26), (120, 55, 55), (180, 90, 80)
            ).save(ASSETS_DIR / "lol.png")
    print(f"Fonds générés dans {ASSETS_DIR}")


if __name__ == "__main__":
    main()
