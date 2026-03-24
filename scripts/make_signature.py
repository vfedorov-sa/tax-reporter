"""Рисует условную подпись для демонстрации и тестов.

Настоящий скан подписи — персональные данные и реквизит документа, в репозитории
ему не место. Этот файл выдаёт росчерк на белом фоне: рендерер вычищает белое
в прозрачность ровно так же, как делал бы со сканом.

    python scripts/make_signature.py
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw

WIDTH, HEIGHT = 420, 140


def draw(path: Path) -> None:
    image = Image.new("RGB", (WIDTH, HEIGHT), "white")
    pen = ImageDraw.Draw(image)

    curve = []
    for step in range(260):
        t = step / 259
        x = 30 + t * (WIDTH - 70)
        y = HEIGHT / 2 - 34 * math.sin(t * math.pi * 2.6) * (1 - t * 0.45) + 18 * t
        curve.append((x, y))
    pen.line(curve, fill=(18, 26, 88), width=4, joint="curve")

    tail = [(WIDTH - 150, HEIGHT - 34), (WIDTH - 60, HEIGHT - 52), (WIDTH - 34, HEIGHT - 20)]
    pen.line(tail, fill=(18, 26, 88), width=3, joint="curve")

    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("samples/signature.png"))
    args = parser.parse_args()
    draw(args.out)
    print(f"подпись: {args.out}")


if __name__ == "__main__":
    main()
