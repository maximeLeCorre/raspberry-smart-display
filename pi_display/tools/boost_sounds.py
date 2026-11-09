"""Rend les sons des kills plus forts (haut-parleur de la montre, petit et faible).

Lit `pi_display/sounds/originals/killN.*` (mp3…), écrit `pi_display/sounds/killN.wav` :
mono 22 kHz, graves coupés (passe-haut 400 Hz), volume normalisé puis poussé avec un écrêtage doux (tanh) — plus fort
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


def highpass(samples: array.array, rate: int, cutoff: float) -> list[float]:
    """Passe-haut (biquad RBJ, Q 0,707) : le haut-parleur de la montre ne rend pas les
    graves, qui mangeaient la marge ; sans eux, le même pic sonne bien plus fort."""
    w = 2 * math.pi * cutoff / rate
    alpha = math.sin(w) / (2 * 0.7071)
    cos = math.cos(w)
    a0 = 1 + alpha
    b0, b1, b2 = (1 + cos) / 2 / a0, -(1 + cos) / a0, (1 + cos) / 2 / a0
    a1, a2 = -2 * cos / a0, (1 - alpha) / a0
    out, x1, x2, y1, y2 = [], 0.0, 0.0, 0.0, 0.0
    for x in samples:
        y = b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        x2, x1, y2, y1 = x1, x, y1, y
        out.append(y)
    return out


def rms_db(samples) -> float:
    return 20 * math.log10(max(1e-9, math.sqrt(sum(s * s for s in samples) / max(1, len(samples))) / 32767))


def boost(samples, gain: float) -> array.array:
    peak = max(1, max(abs(s) for s in samples))
    scale = gain * 32767 / peak                      # normalisé, puis gain
    soft = math.tanh(gain)                           # le pic final reste à ~100 %
    return array.array("h", (int(32767 * math.tanh(s * scale / 32767) / soft) for s in samples))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gain", type=float, default=4.0, help="1 = normalisé seulement")
    parser.add_argument("--highpass", type=float, default=400, help="Hz ; 0 = sans filtre")
    args = parser.parse_args()
    pygame.mixer.init(frequency=RATE, size=-16, channels=2)
    for src in sorted((SOUNDS / "originals").glob("kill[1-5].*")):
        raw = array.array("h", pygame.mixer.Sound(str(src)).get_raw())
        # Stéréo → mono, et 1 échantillon sur 2 (moyenne) : 22 050 Hz.
        mono = array.array("h", ((raw[i] + raw[i + 1] + raw[i + 2] + raw[i + 3]) // 4
                                 for i in range(0, len(raw) - 3, 4)))
        out = SOUNDS / f"{src.stem}.wav"
        filtered = highpass(mono, RATE // 2, args.highpass) if args.highpass else mono
        loud = boost(filtered, args.gain)
        with wave.open(str(out), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE // 2)
            w.writeframes(loud.tobytes())
        print(f"{out.name}  {out.stat().st_size // 1024} Ko  niveau moyen {rms_db(loud):.1f} dBFS")


if __name__ == "__main__":
    main()
