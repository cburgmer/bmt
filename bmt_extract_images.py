#!/usr/bin/env python3
"""
Extract the three potential images from a Testo BMT file and save as BMP.

Based on reverse-engineered layout:
- Image 1 (320x240): 54-byte header, then 16-bit LE pixel data (thermal/SuperResolution).
- Image 2 (640x480): same 54-byte header at 153740, then 16-bit LE pixel data (visual).
- Image 3 (160x120): 160,120 found at 768293 (16-bit LE); data assumed to start
  immediately after the 4-byte dimension (768297) — no standard header in context.

All images are treated as 16-bit little-endian grayscale, scaled to 8-bit for BMP.
"""

import struct
import sys
from pathlib import Path

# Header size used for first two images (BMP-like block header)
BMT_HEADER_SIZE = 54

# (label, file_offset_of_header_or_data, width, height, data_offset_override)
# If data_offset_override is None, data starts at file_offset + BMT_HEADER_SIZE.
IMAGE_SPECS = [
    ("thermal_320x240", 0, 320, 240, None),           # header at 0, data at 54
    ("visual_640x480", 153740, 640, 480, None),      # header at 153740, data at 153794
    ("thermal_160x120", 768293, 160, 120, 768297),   # dims at 768293, data at 768297 (no 54-byte header)
]


def raw_16bit_le_to_grayscale(data: bytes, width: int, height: int) -> bytes:
    """
    Convert 16-bit LE pixel data to 8-bit grayscale for BMP.
    Normalize by min-max over the image so something visible appears even if range is small.
    """
    n = width * height
    if len(data) < n * 2:
        # Pad with zeros if we have less data (wrong offset)
        data = data + b"\x00\x00" * (n - len(data) // 2)
    pixels_16 = []
    for i in range(n):
        idx = i * 2
        lo, hi = data[idx], data[idx + 1]
        pixels_16.append(lo + (hi << 8))
    mn, mx = min(pixels_16), max(pixels_16)
    if mx <= mn:
        mx = mn + 1
    return bytes((int((p - mn) * 255 / (mx - mn)) for p in pixels_16))


def write_bmp_8bit(
    out_path: Path,
    width: int,
    height: int,
    pixels_8: bytes,
) -> None:
    """Write an 8-bit grayscale BMP (bottom-up, no compression)."""
    row_size = (width + 3) & ~3
    image_size = row_size * height
    color_table_size = 256 * 4
    data_offset = 14 + 40 + color_table_size
    file_size = data_offset + image_size

    with open(out_path, "wb") as f:
        # FILE HEADER (14 bytes)
        f.write(b"BM")
        f.write(struct.pack("<I", file_size))
        f.write(struct.pack("<HH", 0, 0))
        f.write(struct.pack("<I", data_offset))

        # INFO HEADER (40 bytes)
        f.write(struct.pack("<I", 40))           # header size
        f.write(struct.pack("<ii", width, height))
        f.write(struct.pack("<HH", 1, 8))        # planes, bits per pixel
        f.write(struct.pack("<I", 0))             # compression
        f.write(struct.pack("<I", image_size))
        f.write(struct.pack("<ii", 0, 0))
        f.write(struct.pack("<II", 256, 256))

        # COLOR TABLE (256 x 4 bytes) — grayscale
        for i in range(256):
            f.write(bytes((i, i, i, 0)))

        # IMAGE DATA (bottom-up, rows padded to 4 bytes)
        for y in range(height - 1, -1, -1):
            row = pixels_8[y * width : (y + 1) * width]
            row_padded = row + b"\x00" * (row_size - len(row))
            f.write(row_padded)


def extract_images(bmt_path: Path, out_dir: Path) -> None:
    data = bmt_path.read_bytes()
    out_dir.mkdir(parents=True, exist_ok=True)

    for label, header_offset, width, height, data_offset_override in IMAGE_SPECS:
        if data_offset_override is not None:
            data_offset = data_offset_override
        else:
            data_offset = header_offset + BMT_HEADER_SIZE

        pixel_bytes = width * height * 2
        end = data_offset + pixel_bytes

        if data_offset < 0 or end > len(data):
            print(
                f"  {label}: skip (data range {data_offset}-{end} outside file size {len(data)})",
                file=sys.stderr,
            )
            continue

        raw = data[data_offset:end]
        pixels_8 = raw_16bit_le_to_grayscale(raw, width, height)
        out_name = f"{bmt_path.stem}_{label}.bmp"
        out_path = out_dir / out_name
        write_bmp_8bit(out_path, width, height, pixels_8)
        print(f"  {label}: {width}x{height} -> {out_path}")


def main() -> None:
    bmt_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("IV_01279.BMT")
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else bmt_path.parent / "extracted"

    if not bmt_path.exists():
        print(f"File not found: {bmt_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Input: {bmt_path}")
    print(f"Output dir: {out_dir}")
    extract_images(bmt_path, out_dir)


if __name__ == "__main__":
    main()
