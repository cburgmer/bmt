#!/usr/bin/env python3
"""
Extract the three potential images from a Testo BMT file and save as BMP.

Based on reverse-engineered layout:
- Image 1 (320x240): 54-byte header, then 16-bit LE pixel data (thermal/SuperResolution).
- Image 2 (640x480): same 54-byte header at 153740, then 16-bit LE pixel data (visual).
- Image 3 (160x120): 160,120 found at 768293 (16-bit LE); data assumed to start
  immediately after the 4-byte dimension (768297) — no standard header in context.

Thermal images: min-max normalized, then applied to a temperature colormap (dark blue →
blue → yellow → red → whitish red) and saved as 24-bit BMP. Visual: high byte only (no
normalisation), 8-bit grayscale BMP. All images are rotated 180° to correct orientation.
"""

import struct
import sys
from pathlib import Path

# Header size used for first two images (BMP-like block header)
BMT_HEADER_SIZE = 54

# (label, file_offset, width, height, data_offset_override, "thermal" | "visual")
IMAGE_SPECS = [
    ("thermal_320x240", 0, 320, 240, None, "thermal"),
    ("visual_640x480", 153740, 640, 480, None, "visual"),
]


def _read_16bit_le_pixels(data: bytes, width: int, height: int) -> list[int]:
    n = width * height
    if len(data) < n * 2:
        data = data + b"\x00\x00" * (n - len(data) // 2)
    return [
        data[i * 2] + (data[i * 2 + 1] << 8)
        for i in range(n)
    ]


def flip_180(pixels_8: bytes, width: int, height: int) -> bytes:
    """Reverse row order (rotate image 180°)."""
    return b"".join(
        pixels_8[y * width : (y + 1) * width]
        for y in range(height - 1, -1, -1)
    )


def raw_16bit_to_grayscale_normalized(data: bytes, width: int, height: int) -> bytes:
    """16-bit LE -> 8-bit grayscale with min-max normalization (for thermal index)."""
    pixels_16 = _read_16bit_le_pixels(data, width, height)
    mn, mx = min(pixels_16), max(pixels_16)
    if mx <= mn:
        mx = mn + 1
    return bytes((int((p - mn) * 255 / (mx - mn)) for p in pixels_16))


# Temperature colormap: cold (0) = dark blue → blue → yellow → red → whitish red (255)
_COLORMAP_STOPS = [
    (0.0, (0, 0, 139)),      # dark blue
    (0.25, (0, 0, 255)),    # blue
    (0.5, (255, 255, 0)),   # yellow
    (0.75, (255, 0, 0)),    # red
    (1.0, (255, 255, 255)), # whitish red / white
]


def _thermal_color(index: int) -> tuple[int, int, int]:
    """Map normalized thermal index 0–255 to RGB (dark blue = cold, whitish red = hot)."""
    t = index / 255.0
    for i in range(len(_COLORMAP_STOPS) - 1):
        t0, (r0, g0, b0) = _COLORMAP_STOPS[i]
        t1, (r1, g1, b1) = _COLORMAP_STOPS[i + 1]
        if t0 <= t <= t1:
            u = (t - t0) / (t1 - t0) if t1 > t0 else 1.0
            return (
                int(r0 + (r1 - r0) * u),
                int(g0 + (g1 - g0) * u),
                int(b0 + (b1 - b0) * u),
            )
    return _COLORMAP_STOPS[-1][1]


def thermal_index_to_rgb(pixels_8: bytes) -> bytes:
    """Convert 8-bit thermal indices to 24-bit BGR (BMP order) using temperature colormap."""
    out = bytearray(len(pixels_8) * 3)
    for i, idx in enumerate(pixels_8):
        r, g, b = _thermal_color(idx)
        out[i * 3] = b
        out[i * 3 + 1] = g
        out[i * 3 + 2] = r
    return bytes(out)


def write_bmp_8bit(
    out_path: Path,
    width: int,
    height: int,
    pixels_8: bytes,
) -> None:
    """Write an 8-bit grayscale BMP (bottom-up, no compression). Rows already in flip-180 order."""
    row_size = (width + 3) & ~3
    image_size = row_size * height
    color_table_size = 256 * 4
    data_offset = 14 + 40 + color_table_size
    file_size = data_offset + image_size

    with open(out_path, "wb") as f:
        f.write(b"BM")
        f.write(struct.pack("<I", file_size))
        f.write(struct.pack("<HH", 0, 0))
        f.write(struct.pack("<I", data_offset))
        f.write(struct.pack("<I", 40))
        f.write(struct.pack("<ii", width, height))
        f.write(struct.pack("<HH", 1, 8))
        f.write(struct.pack("<I", 0))
        f.write(struct.pack("<I", image_size))
        f.write(struct.pack("<ii", 0, 0))
        f.write(struct.pack("<II", 256, 256))
        for i in range(256):
            f.write(bytes((i, i, i, 0)))
        # BMP is stored bottom-up; our pixels_8 is already flipped so row 0 is top
        for y in range(height - 1, -1, -1):
            row = pixels_8[y * width : (y + 1) * width]
            f.write(row + b"\x00" * (row_size - len(row)))


def write_bmp_24bit(
    out_path: Path,
    width: int,
    height: int,
    pixels_bgr: bytes,
) -> None:
    """Write a 24-bit BGR BMP (bottom-up, no compression). Rows already in flip-180 order."""
    row_size = (width * 3 + 3) & ~3
    image_size = row_size * height
    data_offset = 14 + 40
    file_size = data_offset + image_size

    with open(out_path, "wb") as f:
        f.write(b"BM")
        f.write(struct.pack("<I", file_size))
        f.write(struct.pack("<HH", 0, 0))
        f.write(struct.pack("<I", data_offset))
        f.write(struct.pack("<I", 40))
        f.write(struct.pack("<ii", width, height))
        f.write(struct.pack("<HH", 1, 24))
        f.write(struct.pack("<I", 0))
        f.write(struct.pack("<I", image_size))
        f.write(struct.pack("<ii", 0, 0))
        f.write(struct.pack("<II", 0, 0))
        for y in range(height - 1, -1, -1):
            row = pixels_bgr[y * width * 3 : (y + 1) * width * 3]
            f.write(row + b"\x00" * (row_size - len(row)))


def extract_images(bmt_path: Path, out_dir: Path) -> None:
    data = bmt_path.read_bytes()
    out_dir.mkdir(parents=True, exist_ok=True)

    for spec in IMAGE_SPECS:
        label, header_offset, width, height, data_offset_override, kind = spec
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
        pixels_8 = raw_16bit_to_grayscale_normalized(raw, width, height)

        pixels_8 = flip_180(pixels_8, width, height)

        out_name = f"{bmt_path.stem}_{label}.bmp"
        out_path = out_dir / out_name
        if kind == "thermal":
            bgr = thermal_index_to_rgb(pixels_8)
            write_bmp_24bit(out_path, width, height, bgr)
        else:
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
