"""Generate placeholder PNG icons without Pillow. Run: python extension/icons/make_icons.py"""

import struct
import zlib
from pathlib import Path

BLUE = (29, 78, 216)
WHITE = (255, 255, 255)


def _chunk(tag: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def shield_png(size: int) -> bytes:
    rows = []
    for y in range(size):
        row = bytearray([0])  # filter byte
        for x in range(size):
            # Rounded square with a white vertical bar as a crude shield mark.
            cx, cy = x - size / 2 + 0.5, y - size / 2 + 0.5
            inside = abs(cx) < size * 0.46 and abs(cy) < size * 0.46
            bar = abs(cx) < size * 0.08 and -size * 0.3 < cy < size * 0.3
            color = WHITE if (inside and bar) else BLUE if inside else (0, 0, 0)
            alpha = 255 if inside else 0
            row.extend((*color, alpha))
        rows.append(bytes(row))
    raw = b"".join(rows)
    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", zlib.compress(raw, 9)) + _chunk(b"IEND", b"")


if __name__ == "__main__":
    here = Path(__file__).parent
    for s in (16, 48, 128):
        (here / f"icon{s}.png").write_bytes(shield_png(s))
        print(f"wrote icon{s}.png")
