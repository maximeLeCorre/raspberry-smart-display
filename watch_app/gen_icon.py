"""Génère l'icône 1024×1024 de l'app montre (requise par App Store Connect).

Fond opaque (Apple refuse la transparence ; la montre découpe un cercle) :
anneau doré + coche = « partie acceptée ». Relancer après modification :
    .\\.venv\\Scripts\\python watch_app\\gen_icon.py
"""
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame  # noqa: E402

SIZE = 1024
OUT = os.path.join(os.path.dirname(__file__), "LolRemote", "Assets.xcassets",
                   "AppIcon.appiconset", "icon.png")

BG_TOP, BG_BOTTOM = (16, 28, 48), (6, 12, 24)
GOLD = (200, 170, 110)


def _thick_segment(surf, a, b, width) -> None:
    # draw.line épais est irrégulier en diagonale : quadrilatère exact.
    direction = pygame.Vector2(b) - pygame.Vector2(a)
    normal = pygame.Vector2(-direction.y, direction.x).normalize() * (width / 2)
    pa, pb = pygame.Vector2(a), pygame.Vector2(b)
    pygame.draw.polygon(surf, GOLD, [pa + normal, pb + normal, pb - normal, pa - normal])


def main() -> None:
    pygame.init()
    surf = pygame.Surface((SIZE, SIZE))
    for y in range(SIZE):
        t = y / (SIZE - 1)
        color = [round(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM)]
        pygame.draw.line(surf, color, (0, y), (SIZE, y))
    center = (SIZE // 2, SIZE // 2)
    pygame.draw.circle(surf, GOLD, center, 360, width=44)
    check = [(330, 530), (460, 655), (700, 395)]
    for a, b in zip(check, check[1:]):
        _thick_segment(surf, a, b, 70)
    for point in check:  # bouts et coude arrondis
        pygame.draw.circle(surf, GOLD, point, 35)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    pygame.image.save(surf, OUT)
    print(OUT)


if __name__ == "__main__":
    main()
