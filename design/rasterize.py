"""Rasterise les fonds SVG de backgrounds.html en PNG 800x480.

Usage :  python design/rasterize.py [--preview]
  (défaut) écrit pi_display/assets/{default,champselect,lol}.png
  --preview : écrit aussi design/_preview_<mode>.png pour inspection

Nécessite : pip install playwright  &&  python -m playwright install chromium
"""

from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
HTML = (HERE / "backgrounds.html").as_uri()
ASSETS = HERE.parent / "pi_display" / "assets"
MODES = ["default", "champselect", "lol"]


def main():
    preview = "--preview" in sys.argv
    ASSETS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(device_scale_factor=1)
        page.goto(HTML)
        page.wait_for_timeout(200)  # laisse le script générer les SVG
        for mode in MODES:
            el = page.locator(f"#bg-{mode}")
            el.screenshot(path=str(ASSETS / f"{mode}.png"))
            if preview:
                el.screenshot(path=str(HERE / f"_preview_{mode}.png"))
            print(f"  {mode}.png écrit")
        browser.close()
    print(f"Fonds rasterisés dans {ASSETS}")


if __name__ == "__main__":
    main()
