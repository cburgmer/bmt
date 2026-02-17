#!/usr/bin/env python3
# Copyright 2024 the BMT extractor project authors.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
Extract thermal and visual images from a Testo BMT file and save as BMP.

Based on reverse-engineered layout:
- Image 1 (thermal): embedded as a complete BMP at file start (offset 0, magic "BM").
- Image 2 (visual): embedded as a complete BMP at 0x2587a (magic "BM", size in header).

Both images are extracted verbatim (no conversion).
"""

import struct
import sys
from pathlib import Path

# Embedded BMP offsets (magic "BM"; file size at offset +2, 4 bytes LE)
THERMAL_BMP_OFFSET = 0
VISUAL_BMP_OFFSET = 0x2587A

# (label, bmp_offset, width, height) for display only
IMAGE_SPECS = [
    ("thermal_320x240", THERMAL_BMP_OFFSET, 320, 240),
    ("visual_640x480", VISUAL_BMP_OFFSET, 640, 480),
]


def _bmp_size_from_header(data: bytes, bmp_start: int) -> int | None:
    """Compute BMP file size from file header + DIB (BMP start). Returns None if invalid."""
    if bmp_start + 40 > len(data):
        return None
    pixel_off = struct.unpack_from("<I", data, bmp_start + 10)[0]
    width = struct.unpack_from("<i", data, bmp_start + 18)[0]
    height = struct.unpack_from("<i", data, bmp_start + 22)[0]
    bits = struct.unpack_from("<H", data, bmp_start + 28)[0]
    row = ((width * bits // 8) + 3) & ~3
    pixel_size = row * abs(height)
    return pixel_off + pixel_size


def extract_images(bmt_path: Path, out_dir: Path) -> None:
    data = bmt_path.read_bytes()
    out_dir.mkdir(parents=True, exist_ok=True)

    for label, bmp_offset, width, height in IMAGE_SPECS:
        out_name = f"{bmt_path.stem}_{label}.bmp"
        out_path = out_dir / out_name

        if data[bmp_offset : bmp_offset + 2] != b"BM":
            print(
                f"  {label}: skip (no BMP magic at 0x{bmp_offset:x})",
                file=sys.stderr,
            )
            continue
        bmp_size = struct.unpack_from("<I", data, bmp_offset + 2)[0]
        # Thermal at 0 often has whole-file size in header; use DIB to get real size
        if bmp_offset == THERMAL_BMP_OFFSET and bmp_size >= len(data):
            computed = _bmp_size_from_header(data, bmp_offset)
            if computed is not None:
                bmp_size = computed
        end = bmp_offset + bmp_size
        if end > len(data):
            print(
                f"  {label}: skip (BMP size {bmp_size} extends past file)",
                file=sys.stderr,
            )
            continue
        # Write valid BMP: fix stored size in header if we used computed size
        chunk = bytearray(data[bmp_offset:end])
        struct.pack_into("<I", chunk, 2, bmp_size)
        out_path.write_bytes(chunk)
        print(f"  {label}: {width}x{height} (embedded BMP, {bmp_size} bytes) -> {out_path}")


def write_report(out_dir: Path, stems: list[str]) -> None:
    """Write HTML report into out_dir. Single stem -> {stem}_report.html; multiple -> report.html."""
    template = Path(__file__).parent / "bmt_report.html"
    if not template.exists():
        return
    html = template.read_text()
    if len(stems) == 1:
        report_path = out_dir / f"{stems[0]}_report.html"
    else:
        report_path = out_dir / "report.html"
        # Embed stems so report can show all without fetching (stems.json still written for consistency)
        import json
        html = html.replace(
            "/* __STEMS_JSON__ */ null",
            "/* __STEMS_JSON__ */ " + json.dumps(stems),
        )
    report_path.write_text(html)
    print(f"  Report: {report_path}")


def main() -> None:
    input_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("IV_01279.BMT")
    out_dir_arg = Path(sys.argv[2]) if len(sys.argv) > 2 else None

    if not input_path.exists():
        print(f"Not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    if input_path.is_dir():
        out_dir = out_dir_arg or input_path / "extracted"
        out_dir.mkdir(parents=True, exist_ok=True)
        bmt_files = sorted(
            (p for p in input_path.iterdir() if p.suffix.upper() == ".BMT" and p.is_file()),
            key=lambda p: p.name.lower(),
        )
        if not bmt_files:
            print(f"No .BMT files in {input_path}", file=sys.stderr)
            sys.exit(1)
        print(f"Input dir: {input_path} ({len(bmt_files)} files)")
        print(f"Output dir: {out_dir}")
        stems = []
        for bmt_path in bmt_files:
            extract_images(bmt_path, out_dir)
            stems.append(bmt_path.stem)
        (out_dir / "stems.json").write_text(
            __import__("json").dumps(stems, indent=2),
            encoding="utf-8",
        )
        write_report(out_dir, stems)
    else:
        out_dir = out_dir_arg or input_path.parent / "extracted"
        print(f"Input: {input_path}")
        print(f"Output dir: {out_dir}")
        extract_images(input_path, out_dir)
        write_report(out_dir, [input_path.stem])


if __name__ == "__main__":
    main()
