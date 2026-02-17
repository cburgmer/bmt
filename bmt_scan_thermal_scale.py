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
Scan BMT file for plausible thermal scale (temperature range) values.

The camera auto-adjusts so the coldest pixel maps to dark blue and the warmest to
white/red. We expect min and max temperature (e.g. -6°C to 50°C) stored in
image-specific (changing) regions identified by bmt_analyze_headers.py.

Outputs candidates in plausible Celsius range so you can identify the right offsets
and encoding (e.g. to copy into the extractor for proper temperature scaling).
"""

import struct
import sys
from pathlib import Path

# Intervals to scan: (name, start, end) — based on changing regions from header analysis
SCAN_REGIONS = [
    ("0x2586a_0x2586f", 0x2586A, 0x2586F),
    ("0xbb8cf_0xbb8d7", 0xBB8CF, 0xBB8D7),
    ("0xbb8e7_0xbb8f7", 0xBB8E7, 0xBB8F7),
    ("0xbb912_0xbb918", 0xBB912, 0xBB918),
    ("0xbb929_0xbb938", 0xBB929, 0xBB938),
]

# Plausible temperature range for reporting (Celsius)
TEMP_MIN = -50.0
TEMP_MAX = 120.0

# Single values to exclude (likely not temperatures: dimensions, counts, etc.)
EXCLUDE_INTEGERS = {0, 1, 8, 10, 12, 16, 28, 36, 40, 54, 120, 160, 240, 320, 480, 640}


def unpack_candidates(data: bytes, offset: int) -> list[tuple[str, float]]:
    """Try to interpret 4 or 8 bytes at offset as temperature. Returns list of (encoding, value)."""
    out = []
    if offset + 8 > len(data):
        return out

    # 32-bit float LE/BE (most likely for temperatures)
    for endian, name in [("<f", "float LE"), (">f", "float BE")]:
        try:
            v = struct.unpack_from(endian, data, offset)[0]
            if isinstance(v, float) and v == v and TEMP_MIN <= v <= TEMP_MAX:
                out.append((name, v))
        except Exception:
            pass

    # 64-bit double LE/BE
    if offset + 8 <= len(data):
        for endian, name in [("<d", "double LE"), (">d", "double BE")]:
            try:
                v = struct.unpack_from(endian, data, offset)[0]
                if isinstance(v, float) and v == v and TEMP_MIN <= v <= TEMP_MAX:
                    out.append((name, v))
            except Exception:
                pass

    # int16 as Celsius (e.g. -6, 50) — exclude known dimension/count values
    for endian, name in [("<h", "int16 LE °C"), (">h", "int16 BE °C")]:
        try:
            v = struct.unpack_from(endian, data, offset)[0]
            if v not in EXCLUDE_INTEGERS and TEMP_MIN <= v <= TEMP_MAX:
                out.append((name, float(v)))
        except Exception:
            pass

    # int16 as fixed-point ×0.1 (e.g. -60 -> -6.0, 500 -> 50.0)
    for endian, name in [("<h", "int16 LE ×0.1"), (">h", "int16 BE ×0.1")]:
        try:
            raw = struct.unpack_from(endian, data, offset)[0]
            v = raw * 0.1
            if TEMP_MIN <= v <= TEMP_MAX and int(v) not in EXCLUDE_INTEGERS:
                out.append((name, v))
        except Exception:
            pass

    # uint16 ×0.1 (e.g. 500 → 50.0)
    for endian, name in [("<H", "uint16 LE ×0.1"), (">H", "uint16 BE ×0.1")]:
        try:
            raw = struct.unpack_from(endian, data, offset)[0]
            v = raw * 0.1
            if TEMP_MIN <= v <= TEMP_MAX:
                out.append((name, v))
        except Exception:
            pass
    # uint16 − 273 (Kelvin to Celsius)
    for endian, name in [("<H", "uint16 LE −273"), (">H", "uint16 BE −273")]:
        try:
            raw = struct.unpack_from(endian, data, offset)[0]
            v = raw - 273.0
            if TEMP_MIN <= v <= TEMP_MAX:
                out.append((name, v))
        except Exception:
            pass

    return out


def scan_region(data: bytes, name: str, start: int, end: int) -> list[tuple[int, str, float]]:
    """Scan a byte range for plausible temperature values. Returns (offset, encoding, value)."""
    results = []
    seen = set()
    for offset in range(start, min(end, len(data) - 4)):
        for enc, val in unpack_candidates(data, offset):
            key = (offset, enc, round(val, 4))
            if key not in seen:
                seen.add(key)
                results.append((offset, enc, val))
    return results


def _pair_ok(lo: float, hi: float) -> bool:
    """Exclude trivial (0,0) and require meaningful spread (e.g. ≥ 1°C) or at least min != max."""
    if lo >= hi:
        return False
    if lo == 0.0 and hi == 0.0:
        return False
    if hi - lo < 0.5:  # at least 0.5 °C spread
        return False
    return True


def find_min_max_pairs(data: bytes, start: int, end: int) -> list[tuple[int, str, float, float]]:
    """Find consecutive 4- or 8-byte pairs that could be (min_T, max_T) with min < max."""
    pairs = []
    for offset in range(start, min(end, len(data) - 8)):
        # Two floats LE
        try:
            a, b = struct.unpack_from("<ff", data, offset)
            if a == a and b == b and TEMP_MIN <= a <= TEMP_MAX and TEMP_MIN <= b <= TEMP_MAX and _pair_ok(a, b):
                pairs.append((offset, "float LE, float LE", a, b))
        except Exception:
            pass
        try:
            a, b = struct.unpack_from(">ff", data, offset)
            if a == a and b == b and TEMP_MIN <= a <= TEMP_MAX and TEMP_MIN <= b <= TEMP_MAX and _pair_ok(a, b):
                pairs.append((offset, "float BE, float BE", a, b))
        except Exception:
            pass
        # Two doubles LE
        if offset + 16 <= len(data):
            try:
                a, b = struct.unpack_from("<dd", data, offset)
                if a == a and b == b and TEMP_MIN <= a <= TEMP_MAX and TEMP_MIN <= b <= TEMP_MAX and _pair_ok(a, b):
                    pairs.append((offset, "double LE, double LE", a, b))
            except Exception:
                pass
        # int16 LE pair (as °C or ×0.1)
        try:
            a, b = struct.unpack_from("<hh", data, offset)
            af, bf = a * 0.1, b * 0.1
            if TEMP_MIN <= af <= TEMP_MAX and TEMP_MIN <= bf <= TEMP_MAX and _pair_ok(af, bf):
                pairs.append((offset, "int16 LE ×0.1, int16 LE ×0.1", af, bf))
            af, bf = float(a), float(b)
            if TEMP_MIN <= af <= TEMP_MAX and TEMP_MIN <= bf <= TEMP_MAX and _pair_ok(af, bf):
                pairs.append((offset, "int16 LE °C, int16 LE °C", af, bf))
        except Exception:
            pass
    return pairs


# For summary: strict range expected for real thermal scale (e.g. -6 to 50 °C)
SUMMARY_TEMP_MIN = -10.0
SUMMARY_TEMP_MAX = 60.0
SUMMARY_MIN_SPREAD = 10.0  # min–max spread to count as scale (avoid text/accidental pairs)
TARGET_MIN_C = -6.0
TARGET_MAX_C = 50.0


def _distance_to_target(lo: float, hi: float) -> float:
    """Distance of (lo, hi) from target range (-6, 50). Lower is better."""
    return abs(lo - TARGET_MIN_C) + abs(hi - TARGET_MAX_C)


def main() -> None:
    paths = [Path(p) for p in sys.argv[1:]] if len(sys.argv) > 1 else [Path("IV_01279.BMT")]
    paths = [p for p in paths if p.exists()]
    if not paths:
        print("No files found.", file=sys.stderr)
        return

    # Across all files: (region, offset, enc) -> list of (lo, hi)
    aggregated: dict[tuple[str, int, str], list[tuple[float, float]]] = {}

    for bmt_path in paths:
        data = bmt_path.read_bytes()
        print(f"\n{'='*60}")
        print(f"File: {bmt_path}  ({len(data)} bytes)")
        print("=" * 60)

        all_pairs = []

        for name, start, end in SCAN_REGIONS:
            print(f"\n--- Region: {name}  (0x{start:x} – 0x{end:x}, {end - start} bytes) ---")
            candidates = scan_region(data, name, start, end)
            pairs = find_min_max_pairs(data, start, end)
            for off, enc, lo, hi in pairs:
                all_pairs.append((name, off, enc, lo, hi))
                key = (name, off, enc)
                aggregated.setdefault(key, []).append((lo, hi))
            if pairs:
                print("  Possible thermal scale (min °C, max °C) pairs:")
                for off, enc, lo, hi in pairs:
                    hex_snip = data[off : off + 16].hex() if off + 16 <= len(data) else data[off:].hex()
                    print(f"    0x{off:05x}  {enc}  →  min={lo:.2f}, max={hi:.2f} °C   ({hex_snip})")

            single_seen = set()
            for off, enc, val in sorted(candidates, key=lambda x: (x[0], x[2])):
                if val == 0.0:
                    continue
                key = (off, enc, round(val, 4))
                if key in single_seen:
                    continue
                single_seen.add(key)
                hex_snip = data[off : off + 8].hex() if off + 8 <= len(data) else data[off:].hex()
                print(f"  0x{off:05x}  {enc:28s}  →  {val:8.2f} °C   ({hex_snip})")

            if not pairs and not single_seen:
                print("  No plausible thermal scale (min/max pairs or non-zero single values) in range [{}, {}] °C.".format(TEMP_MIN, TEMP_MAX))

        # Per-file summary (when a single file)
        if len(paths) == 1:
            summary = [
                (region, off, enc, lo, hi)
                for region, off, enc, lo, hi in all_pairs
                if SUMMARY_TEMP_MIN <= lo <= SUMMARY_TEMP_MAX
                and SUMMARY_TEMP_MIN <= hi <= SUMMARY_TEMP_MAX
                and (hi - lo) >= SUMMARY_MIN_SPREAD
            ]
            if summary:
                print("\n--- Best thermal scale candidates (min/max in [{}, {}] °C, spread ≥ {} °C) ---".format(
                    SUMMARY_TEMP_MIN, SUMMARY_TEMP_MAX, SUMMARY_MIN_SPREAD))
                for region, off, enc, lo, hi in summary:
                    print(f"  {region}  0x{off:05x}  {enc}  →  min={lo:.2f}, max={hi:.2f} °C")

    # Multi-file: aggregate min/max per candidate and sort by distance to (-6, 50)
    if len(paths) > 1 and aggregated:
        # For each candidate: global_lo = min of all lo, global_hi = max of all hi
        summary_agg = []
        for (region, off, enc), pairs in aggregated.items():
            los, his = [p[0] for p in pairs], [p[1] for p in pairs]
            global_lo, global_hi = min(los), max(his)
            if not (SUMMARY_TEMP_MIN <= global_lo <= SUMMARY_TEMP_MAX and SUMMARY_TEMP_MIN <= global_hi <= SUMMARY_TEMP_MAX):
                continue
            if global_hi - global_lo < SUMMARY_MIN_SPREAD:
                continue
            dist = _distance_to_target(global_lo, global_hi)
            summary_agg.append((dist, region, off, enc, global_lo, global_hi, len(pairs)))
        summary_agg.sort(key=lambda x: (x[0], x[1], x[2]))
        print("\n" + "=" * 60)
        print("Aggregated across {} file(s): min/max per candidate, ordered by distance to target ({} to {} °C)".format(
            len(paths), TARGET_MIN_C, TARGET_MAX_C))
        print("=" * 60)
        for dist, region, off, enc, global_lo, global_hi, n in summary_agg:
            print(f"  {region}  0x{off:05x}  {enc}")
            print(f"    →  min={global_lo:.2f}, max={global_hi:.2f} °C  (over {n} file(s))  distance to ({TARGET_MIN_C}, {TARGET_MAX_C})= {dist:.1f}")

    print()


if __name__ == "__main__":
    main()
