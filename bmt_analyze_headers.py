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
Analyse non-picture byte ranges across multiple BMT files.

Compares:
- File/thermal header (start of file)
- Block between end of thermal image and start of visual header
- Visual image header
- Final part of file after the visual image

Reports which bytes are stable (identical in all files) vs changing (vary per file).
Stable regions are printed with control characters escaped for readability.
Helps identify where image-specific data (e.g. thermal scale) can be stored.
"""

import sys
from pathlib import Path
from typing import Optional

# Layout (must match bmt_extract_images)
THERMAL_HEADER_SIZE = 54
THERMAL_PIXEL_BYTES = 320 * 240 * 2
FIRST_BLOCK_END = THERMAL_HEADER_SIZE + THERMAL_PIXEL_BYTES  # 153654
VISUAL_HEADER_OFFSET = 153722
VISUAL_HEADER_SIZE = 54
VISUAL_PIXEL_BYTES = 640 * 480 * 2
VISUAL_BLOCK_END = VISUAL_HEADER_OFFSET + VISUAL_HEADER_SIZE + VISUAL_PIXEL_BYTES  # 768176

RANGES = [
    ("file/thermal_header", 0, THERMAL_HEADER_SIZE),
    ("between_thermal_and_visual", FIRST_BLOCK_END, VISUAL_HEADER_OFFSET),
    ("visual_header", VISUAL_HEADER_OFFSET, VISUAL_HEADER_OFFSET + VISUAL_HEADER_SIZE),
    ("after_visual_image", VISUAL_BLOCK_END, None),  # None = to end of file
]


MAX_DISPLAY_BYTES = 256  # Cap per run for display; longer runs show head + tail


def escape_for_display(data: bytes, max_bytes: Optional[int] = None) -> str:
    """Return bytes as string with control chars escaped (e.g. \\x00, \\n)."""
    if max_bytes is not None and len(data) > max_bytes:
        head = data[: max_bytes // 2]
        tail = data[-(max_bytes - len(head)) :]
        return escape_for_display(head) + " ... (" + str(len(data)) + " bytes total) ... " + escape_for_display(tail)
    return "".join(
        "\\x{:02x}".format(b) if b < 32 or b >= 127 else chr(b)
        for b in data
    )


def analyze_range(name: str, start: int, end: Optional[int], file_datas: list[bytes]) -> tuple[bytes, bytes, int]:
    """
    Compare a byte range across all files. end=None means to end of shortest file.
    Returns (stable_bytes, mask_stable, length_used).
    stable_bytes: at each offset, byte if all files agree, else 0x00 (we'll use a separate mask).
    Actually: return (common_bytes, varying_mask, len).
    common_bytes = bytes that are same everywhere (use 0 for differing positions so we can show "varying")
    Better: return (bytes_or_none_per_offset, ...). Simpler: return two bytearrays, one "canonical" (from first file)
    and one "all_same" (1 where same, 0 where different). Or just return:
    - stable_slice: bytes that are identical (only at offsets where all match)
    - For "changing" we need to report which offsets differ. So: for each offset, True if stable.
    Returns (reference_bytes, is_stable_per_byte) where reference_bytes is from first file (or first file's length).
    """
    if not file_datas:
        return b"", b"", 0
    ref = file_datas[0]
    if end is None:
        end = min(len(d) for d in file_datas)
    else:
        end = min(end, min(len(d) for d in file_datas))
    length = end - start
    if length <= 0:
        return b"", b"", 0
    ref_slice = ref[start:end]
    stable = bytearray(length)
    for i in range(length):
        b = ref_slice[i]
        if all(d[start + i] == b for d in file_datas):
            stable[i] = 1
        else:
            stable[i] = 0
    return bytes(ref_slice), bytes(stable), length


def run_length_split(stable: bytes) -> list[tuple[bool, int, int]]:
    """Split stability mask into runs (True/False, start_offset, length)."""
    if not stable:
        return []
    runs = []
    cur = bool(stable[0])
    start = 0
    for i in range(1, len(stable)):
        if bool(stable[i]) != cur:
            runs.append((cur, start, i - start))
            cur = bool(stable[i])
            start = i
    runs.append((cur, start, len(stable) - start))
    return runs


def main() -> None:
    paths = [Path(p) for p in sys.argv[1:]] if len(sys.argv) > 1 else [Path("IV_01279.BMT")]
    paths = [p for p in paths if p.exists()]
    if not paths:
        print("No files found.", file=sys.stderr)
        return

    file_datas = [p.read_bytes() for p in paths]
    min_len = min(len(d) for d in file_datas)
    n = len(file_datas)

    print("BMT non-picture range analysis")
    print("{} file(s): {}".format(n, ", ".join(str(p) for p in paths)))
    print("(Ranges use first file length; shorter files may truncate.)")
    print()

    for name, start, end in RANGES:
        if end is None:
            end = min_len
        actual_end = min(end, min_len)
        length = actual_end - start
        if length <= 0:
            print("--- {} (0x{:x} – 0x{:x}) ---".format(name, start, actual_end))
            print("  (empty or beyond file length)")
            print()
            continue

        ref_slice, stable_mask, _ = analyze_range(name, start, end, file_datas)
        runs = run_length_split(stable_mask)
        n_stable = sum(1 for b in stable_mask if b)
        n_vary = len(stable_mask) - n_stable

        print("--- {} (0x{:x} – 0x{:x}, {} bytes) ---".format(name, start, actual_end, length))
        print("  Stable: {} bytes  |  Changing: {} bytes".format(n_stable, n_vary))
        print()

        for is_stable, run_start, run_len in runs:
            offset = start + run_start
            chunk = ref_slice[run_start : run_start + run_len]
            label = "STABLE" if is_stable else "CHANGING"
            print("  [{}] 0x{:x} – 0x{:x}  ({} bytes)".format(
                label, offset, offset + run_len, run_len))
            if is_stable and chunk:
                escaped = escape_for_display(chunk, max_bytes=MAX_DISPLAY_BYTES)
                if len(escaped) > 80:
                    for i in range(0, len(escaped), 80):
                        print("    {}".format(escaped[i : i + 80]))
                else:
                    print("    {}".format(escaped))
            elif not is_stable and run_len <= 32:
                # Show first file's bytes for varying (hex)
                print("    (hex) {}".format(chunk.hex()))
            elif not is_stable:
                print("    (hex, first 64) {}...".format(chunk[:64].hex()))
            print()

    print("Done.")


if __name__ == "__main__":
    main()
