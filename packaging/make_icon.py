"""Write packaging/lookup.ico from the in-app logo."""

from __future__ import annotations

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import PySide6  # noqa: F401
from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtWidgets import QApplication

from pdflookup.view import make_logo


def _png(size: int) -> bytes:
    pixmap = make_logo(size)
    buffer = QBuffer()
    buffer.open(QIODevice.WriteOnly)
    pixmap.save(buffer, "PNG")
    return bytes(buffer.data())


def _ico(images: list[tuple[int, bytes]]) -> bytes:
    header = struct.pack("<HHH", 0, 1, len(images))
    entries = b""
    payload = b""
    offset = 6 + 16 * len(images)
    for size, png in images:
        shown = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", shown, shown, 0, 0, 1, 32, len(png), offset)
        offset += len(png)
        payload += png
    return header + entries + payload


def main() -> None:
    app = QApplication.instance() or QApplication([])
    sizes = (16, 24, 32, 48, 64, 256)
    images = [(size, _png(size)) for size in sizes]
    destination = Path(__file__).resolve().parent / "lookup.ico"
    destination.write_bytes(_ico(images))
    app.exit(0)


if __name__ == "__main__":
    main()
