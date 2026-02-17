# BMT extractor

Tools to **read and extract images from Testo BMT files** (thermal camera format). The format was reverse‑engineered from sample files; there is no official specification. Tested with files from the **Testo 875-1i** (resolutions: 160×120 IR, 320×240 SuperResolution, 640×480 visual).

Use this if you have `.BMT` files but no Windows/Proprietary software to open them (e.g. on Linux/macOS).

## What it does

- **Extracts** thermal (320×240, colormapped) and visual (640×480, grayscale) images as BMP.
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

## File layout (reverse‑engineered)

- **First block:** BMA header (54 bytes) then 320×240 16‑bit thermal pixels.
- **Second block:** 36‑byte header at offset 153740, then 640×480 16‑bit visual pixels.
- Thermal images are normalized and saved with a temperature colormap (dark blue → blue → yellow → red → white). Visual uses the high byte of each 16‑bit value (no normalisation). All images are rotated 180° to correct orientation.

## License

This project is licensed under the **Apache License, Version 2.0**. See [LICENSE](LICENSE) for the full text. The BMT file layout described here is reverse‑engineered and unofficial.
