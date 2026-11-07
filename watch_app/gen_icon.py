"""Génère l'icône 1024×1024 de l'app montre (requise par App Store Connect).

Fond opaque (Apple refuse la transparence ; la montre découpe un cercle) :
anneau bleu acier (accent de l'app, Theme.swift) + coche = « partie acceptée ».
Écrite pour la montre ET la coquille iOS (icône affichée par TestFlight).
Relancer après modification :
    .\\.venv\\Scripts\\python watch_app\\gen_icon.py
"""
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
import pygame  # noqa: E402

SIZE = 1024
HERE = os.path.dirname(__file__)
OUTS = [os.path.join(HERE, folder, "Assets.xcassets", "AppIcon.appiconset", "icon.png")
        for folder in ("LolRemote", "Container")]

BG_TOP, BG_BOTTOM = (22, 32, 46), (6, 10, 16)
ACCENT = (143, 169, 200)   # #8FA9C8


def _thick_segment(surf, a, b, width) -> None:
    # draw.line épais est irrégulier en diagonale : quadrilatère exact.
    direction = pygame.Vector2(b) - pygame.Vector2(a)
    normal = pygame.Vector2(-direction.y, direction.x).normalize() * (width / 2)
    pa, pb = pygame.Vector2(a), pygame.Vector2(b)
    pygame.draw.polygon(surf, ACCENT, [pa + normal, pb + normal, pb - normal, pa - normal])


def main() -> None:
    pygame.init()
    surf = pygame.Surface((SIZE, SIZE))
    for y in range(SIZE):
        t = y / (SIZE - 1)
        color = [round(a + (b - a) * t) for a, b in zip(BG_TOP, BG_BOTTOM)]
        pygame.draw.line(surf, color, (0, y), (SIZE, y))
    center = (SIZE // 2, SIZE // 2)
    pygame.draw.circle(surf, ACCENT, center, 360, width=44)
    check = [(330, 530), (460, 655), (700, 395)]
    for a, b in zip(check, check[1:]):
        _thick_segment(surf, a, b, 70)
    for point in check:  # bouts et coude arrondis
        pygame.draw.circle(surf, ACCENT, point, 35)
    for out in OUTS:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        pygame.image.save(surf, out)
        print(out)


if __name__ == "__main__":
    main()
