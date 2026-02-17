# BMT extractor

Tools to **read and extract images from Testo BMT files** (thermal camera format). The format was reverse‑engineered from sample files; there is no official specification. Tested with files from the **Testo 875-1i** (resolutions: 160×120 IR, 320×240 SuperResolution, 640×480 visual).

Use this if you have `.BMT` files but no Windows/Proprietary software to open them (e.g. on Linux/macOS).

## What it does

- **Extracts** thermal (320×240) and visual (640×480) images as BMP; both are embedded BMPs in the file and are written verbatim (with a corrected size in the thermal BMP header when needed).
- **Optional:** Scans a BMT file for potential image-dimension headers (for reverse‑engineering).
- **HTML report:** View thermal and visual side‑by‑side or with thermal overlaid on the photo (opacity slider). Supports a single file or a directory of BMTs (all listed, sorted by filename).

## Limitations:

This project was tried without the SuperResolution option turned on. This option will probably change the file format. 

## Requirements

- **Python 3** (no extra packages; uses only the standard library).

## How to run

### Extract images (and generate report)

**Single BMT file:**

```bash
python3 bmt_extract_images.py path/to/image.BMT
```

Output goes to `path/to/extracted/` by default (e.g. `image_thermal_320x240.bmp`, `image_visual_640x480.bmp`, and `image_report.html`).

**Directory of BMT files:**

```bash
python3 bmt_extract_images.py path/to/folder/
```

- Finds all `.BMT` / `.bmt` in that folder (sorted by name).
- Extracts each into `path/to/folder/extracted/`.
- Writes `extracted/stems.json` (list of filenames without extension) and `extracted/report.html` to view all pictures in one page.

**Custom output directory (optional second argument):**

```bash
python3 bmt_extract_images.py path/to/image.BMT path/to/output/
python3 bmt_extract_images.py path/to/folder/ path/to/output/
```

### View the report

Open the generated HTML in a browser:

- Single file: `extracted/<name>_report.html`
- Directory: `extracted/report.html`

Use “Side by side” or “Thermal over visual (alpha)” and, in overlay mode, the “Thermal opacity” slider. The report must be opened from the same folder that contains the extracted BMPs (or use a local HTTP server if your browser blocks `file://`).

### Scan for image dimensions (optional)

To inspect where the format stores width/height (e.g. for other camera models or format variants):

```bash
python3 bmt_scan_dimensions.py path/to/image.BMT
```

Prints a hex dump of the header and all candidate offsets where known resolutions (160×120, 320×240, 640×480) appear.

### Scan for thermal scale (optional)

To find where min/max temperature (thermal scale) might be stored for each picture:

```bash
python3 bmt_scan_thermal_scale.py path/to/image.BMT
```

Scans header and metadata regions for plausible temperature values (float, double, int16 °C or ×0.1, uint16 −273) and reports (min, max) pairs. A short summary lists the best candidates (e.g. for later use in the extractor).

### Analyse header stability (optional)

To see which bytes in non-picture areas are identical across files (stable) vs image-specific (changing):

```bash
python3 bmt_analyze_headers.py image1.BMT image2.BMT ...
```

Reports four ranges (file/thermal header, block between thermal and visual, visual header, tail after visual image), with stable bytes printed escaped and changing bytes marked. Use this to see where per-image data (e.g. thermal scale) can live.

## BMT file format (reverse‑engineered)

There is no official specification. The following is what we have inferred from Testo 875-1i `.BMT` files. Layout may differ for other models or settings (e.g. SuperResolution).

### Overview

A BMT file is a container that holds two images and metadata:

1. **Thermal image** — embedded as a BMP at the start of the file.
2. **Visual (photo) image** — embedded as a second BMP at a fixed offset.
3. **Metadata** — in the gap between the two BMPs and after the second BMP. Some bytes are stable across files; others change per image (e.g. candidate regions for thermal scale).

All offsets below are in decimal unless prefixed with `0x`.

### Block 1: Thermal image (BMP at offset 0)

- **Offset:** 0.
- **Format:** Standard BMP: magic `BM` (2 bytes), then at offset +2 a 4-byte little-endian “file size”, then file header and DIB (e.g. 40-byte BITMAPINFOHEADER), then pixel data.
- **Dimensions:** 320×240, 16 bits per pixel. Pixel data starts at offset 54; row stride padded to 4 bytes. So the **actual** thermal BMP size is 153 654 bytes (54 + 320×240×2 with row padding).
- **Quirk:** The 4-byte size at offset +2 is often set to the **whole BMT file size** (e.g. 845 121), not the thermal BMP size. An extractor must derive the real size from the DIB: pixel data offset at +10, width/height at +18/+22, bit count at +28; then `size = pixel_offset + (padded row × |height|)`. The written BMP should have the correct size in its header so that viewers accept it.

### Gap between thermal and visual

- From the end of the thermal BMP (153 654) to the start of the visual BMP (0x2587a = 153 722) there are **68 bytes** of non-picture data. Part of this (and other regions) varies per file; `bmt_analyze_headers.py` reports which bytes are stable vs changing. `bmt_scan_thermal_scale.py` scans selected changing regions for plausible min/max temperature values (thermal scale).

### Block 2: Visual image (BMP at 0x2587a)

- **Offset:** 0x2587a (153 722).
- **Format:** Full embedded BMP: magic `BM`, file size at +2 (correct in our samples, e.g. 614 454), then standard header and pixel data.
- **Dimensions:** 640×480, 16 bits per pixel in our samples. Extracted verbatim (no conversion).

### After the visual BMP

- The remainder of the file follows the visual image. Length and content are variable; some of it is stable, some changes per image.

### Extraction behaviour

- **Thermal:** Read BMP from offset 0. If the size at +2 is ≥ file length, compute size from the DIB and write a BMP with the corrected size in the header. No colormap or rotation is applied; the output is the embedded 16‑bit BMP.
- **Visual:** Copy the bytes from 0x2587a for the length given in the BMP header. No conversion.

## License

This project is licensed under the **Apache License, Version 2.0**. See [LICENSE](LICENSE) for the full text. The BMT file layout described here is reverse‑engineered and unofficial.
