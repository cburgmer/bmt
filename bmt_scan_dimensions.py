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
Scan a Testo BMT (thermal camera) file for potential image dimension headers.

Known resolutions for Testo 875-1i:
- 160 x 120 (infrared)
- 320 x 240 (SuperResolution)
- 640 x 480 (visual)

Searches for these dimension pairs as 16- or 32-bit integers, little- and
big-endian, and reports file offset and surrounding bytes as candidates.
"""

import struct
import sys
from pathlib import Path

# Known dimension pairs (width, height) for Testo 875-1i
KNOWN_RESOLUTIONS = [
    (160, 120),   # IR
    (320, 240),   # SuperResolution
    (640, 480),   # visual
]


def find_dimension_candidates(data: bytes) -> list[tuple[int, str, int, int, bytes]]:
    """
    Scan data for (width, height) pairs matching known resolutions.
    Returns list of (offset, encoding, width, height, context_snippet).
    """
    candidates = []
    encodings = [
        ("32-bit LE", lambda w, h: (struct.pack("<II", w, h), 8)),
        ("32-bit BE", lambda w, h: (struct.pack(">II", w, h), 8)),
        ("16-bit LE", lambda w, h: (struct.pack("<HH", w, h), 4)),
        ("16-bit BE", lambda w, h: (struct.pack(">HH", w, h), 4)),
    ]
    context_radius = 8

    for width, height in KNOWN_RESOLUTIONS:
        for enc_name, enc_fn in encodings:
            pattern, plen = enc_fn(width, height)
            offset = 0
            while True:
                offset = data.find(pattern, offset)
                if offset == -1:
                    break
                start = max(0, offset - context_radius)
                end = min(len(data), offset + plen + context_radius)
                context = data[start:end]
                candidates.append((offset, enc_name, width, height, context))
                offset += 1

    return candidates


def dump_header(data: bytes, length: int = 64) -> None:
    """Print a hex/ASCII dump of the first bytes (likely header)."""
    chunk = data[:length]
    print("--- First bytes (likely header) ---")
    for i in range(0, len(chunk), 16):
        line = chunk[i : i + 16]
        hex_part = " ".join(f"{b:02x}" for b in line)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in line)
        print(f"  {i:08x}  {hex_part:<48}  {ascii_part}")
    print()

    # Parse as potential BMP-like header (BMA + byte, then fields)
    if len(data) >= 30:
        print("--- Parsed header (BMP-like interpretation) ---")
        print(f"  Magic: {data[0:3]!r}  ('BMA')  + 1 byte: 0x{data[3]:02x}")
        u32_le = lambda i: struct.unpack_from("<I", data, i)[0]
        u16_le = lambda i: struct.unpack_from("<H", data, i)[0]
        print(f"  @ 0x04  u32 LE: {u32_le(4)}")
        print(f"  @ 0x08  u32 LE: {u32_le(8)}")
        print(f"  @ 0x0A  u32 LE: {u32_le(10)}  (header size)")
        print(f"  @ 0x0E  u32 LE: {u32_le(14)}  (sub-header size? = 40)")
        print(f"  @ 0x12  u32 LE: {u32_le(18)}  <- width")
        print(f"  @ 0x16  u32 LE: {u32_le(22)}  <- height")
        print(f"  @ 0x1A  u16 LE: {u16_le(26)}  (planes)")
        print(f"  @ 0x1C  u16 LE: {u16_le(28)}  (bits per pixel)")
    print()


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("IV_01279.BMT")
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        sys.exit(1)

    data = path.read_bytes()
    size = len(data)
    print(f"File: {path}")
    print(f"Size: {size} bytes ({size:,})")
    print()

    dump_header(data)

    candidates = find_dimension_candidates(data)
    # Sort by file offset
    candidates.sort(key=lambda x: x[0])

    print("--- Dimension candidates (offset, encoding, width x height, context) ---")
    print("Known resolutions: 160x120, 320x240, 640x480")
    print()

    for offset, enc, w, h, ctx in candidates:
        hex_ctx = " ".join(f"{b:02x}" for b in ctx)
        print(f"  offset 0x{offset:06x} ({offset:6d})  {enc:10s}  {w} x {h}")
        print(f"    context: {hex_ctx}")
        print()

    print(f"Total candidates: {len(candidates)}")

    # High-confidence: same header pattern (36, 40, then width, height)
    high_conf = [
        c for c in candidates
        if c[1] == "32-bit LE"
        and len(c[4]) >= 12
        and c[4][:4] == b"\x24\x00\x00\x00"  # 36 LE
        and c[4][4:8] == b"\x28\x00\x00\x00"  # 40 LE
    ]
    if high_conf:
        print()
        print("--- High-confidence dimension headers (pattern: 36, 40, width, height) ---")
        for offset, enc, w, h, _ in high_conf:
            print(f"  offset 0x{offset:06x}:  {w} x {h}")

    # Sanity: expected pixel size for 320x240 @ 16 bpp
    header_len = 36
    ir_pixels = 320 * 240 * 2
    first_block_end = header_len + ir_pixels
    if first_block_end <= size:
        print()
        print("--- Consistency check (first image 320x240 @ 16 bpp, header 36) ---")
        print(f"  Header + pixel block ends at offset: {first_block_end} (0x{first_block_end:x})")
        next_bytes = data[first_block_end : first_block_end + 32]
        print(f"  Next 32 bytes (hex): {next_bytes.hex()}")
        # Check for UTF-16 ASCII
        try:
            text = next_bytes.decode("utf-16-le", errors="replace")
            print(f"  As UTF-16-LE: {repr(text)}")
        except Exception:
            pass


if __name__ == "__main__":
    main()
