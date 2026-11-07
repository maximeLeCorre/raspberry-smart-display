"""Rend les sons des kills plus forts (haut-parleur de la montre, petit et faible).

Lit `pi_display/sounds/originals/killN.*` (mp3…), écrit `pi_display/sounds/killN.wav` :
mono 22 kHz, volume normalisé puis poussé avec un écrêtage doux (tanh) — plus fort
à l'oreille sans grésiller. Sans numpy ni ffmpeg : décodage par pygame (SDL_mixer).
Dossier gitignoré (extraits sans licence). Relancer puis redéployer le Pi :
    .\\.venv\\Scripts\\python pi_display\\tools\\boost_sounds.py [--gain 2.5]
"""
import argparse
import array
import math
import os
import wave
from pathlib import Path

os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
import pygame  # noqa: E402

SOUNDS = Path(__file__).resolve().parents[1] / "sounds"
RATE = 44100            # décodage (réduit ensuite à 22 050 Hz : la voix n'a pas besoin de plus)


def boost(samples: array.array, gain: float) -> array.array:
    peak = max(1, max(abs(s) for s in samples))
    scale = gain * 32767 / peak                      # normalisé, puis gain
    soft = math.tanh(gain)                           # le pic final reste à ~100 %
    return array.array("h", (int(32767 * math.tanh(s * scale / 32767) / soft) for s in samples))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gain", type=float, default=2.5, help="1 = normalisé seulement")
    args = parser.parse_args()
    pygame.mixer.init(frequency=RATE, size=-16, channels=2)
    for src in sorted((SOUNDS / "originals").glob("kill[1-5].*")):
        raw = array.array("h", pygame.mixer.Sound(str(src)).get_raw())
        # Stéréo → mono, et 1 échantillon sur 2 (moyenne) : 22 050 Hz.
        mono = array.array("h", ((raw[i] + raw[i + 1] + raw[i + 2] + raw[i + 3]) // 4
                                 for i in range(0, len(raw) - 3, 4)))
        out = SOUNDS / f"{src.stem}.wav"
        with wave.open(str(out), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE // 2)
            w.writeframes(boost(mono, args.gain).tobytes())
        print(f"{out.name}  {out.stat().st_size // 1024} Ko")


if __name__ == "__main__":
    main()
