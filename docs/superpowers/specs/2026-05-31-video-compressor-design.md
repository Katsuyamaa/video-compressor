# Video Compressor — Design Spec
**Date:** 2026-05-31

## Overview

A personal-use web application that runs locally (`localhost:5000`) and compresses existing video files to a user-specified target file size. The user uploads a video via the browser, configures compression settings, and downloads the compressed result.

## Requirements

- Single video at a time
- User controls: target size (MB) + minimum quality threshold (CRF)
- User selects output format (MP4, MKV, WebM)
- Compressed video delivered as browser download
- No permanent storage — temp files cleaned up after download

## Architecture

```
Browser (HTML/JS)
  └── Upload video + settings (POST /compress)
        └── Flask route
              └── FFmpeg 2-pass encoding
                    └── Compressed file → send_file() → Browser download
```

Single-file Flask app + one HTML template. No database, no auth, no queue.

## Components

### 1. Flask Backend (`app.py`)

- `GET /` — Serve the upload form
- `POST /compress` — Accept video upload + settings, run FFmpeg, return file

**Settings accepted via form:**
- `target_mb` (float) — desired output size in megabytes
- `min_crf` (int, 0–51) — minimum quality floor (lower = better quality); default 23
- `output_format` (str) — `mp4`, `mkv`, or `webm`

**Bitrate calculation:**
```
target_bits = target_mb * 8 * 1024 * 1024
video_bitrate = (target_bits / duration_seconds) - audio_bitrate
```

**Encoding:** FFmpeg 2-pass encoding for accurate size targeting. CRF is used as a quality floor — if the calculated bitrate would produce worse quality than the CRF floor, encoding falls back to CRF mode with a warning.

**Temp files:** Written to `tempfile.mkdtemp()`, deleted after `send_file()` using `after_this_request`.

### 2. Frontend (`templates/index.html`)

Single-page form:
- File input (video files only)
- Target MB input (number, min 1)
- Min quality slider (CRF 0–51, labeled Low→High quality)
- Output format dropdown (MP4, MKV, WebM)
- Compress button with progress indication (spinner while processing)
- Error display area for FFmpeg failures

No JavaScript framework — vanilla JS for form submission + fetch API.

### 3. FFmpeg Integration

Called via Python `subprocess`. FFmpeg must be installed and on PATH.

**2-pass example:**
```bash
# Pass 1
ffmpeg -y -i input.mp4 -b:v {bitrate}k -pass 1 -an -f null /dev/null

# Pass 2
ffmpeg -y -i input.mp4 -b:v {bitrate}k -pass 2 output.mp4
```

For WebM: use `libvpx-vp9` codec. For MP4/MKV: use `libx264`.

## Error Handling

- File too large to fit at acceptable quality → return HTTP 400 with message
- FFmpeg not found → return HTTP 500 with install instructions
- Invalid file type → reject at upload with HTTP 400
- FFmpeg process failure → capture stderr, return HTTP 500 with details

## Dependencies

```
flask
```

FFmpeg installed separately (system dependency).

## Project Structure

Everything in a single flat folder — no subdirectories. HTML is embedded in `app.py` via `render_template_string`.

```
C:\Projects\
  app.py          ← Flask app + HTML template embedded as string
  requirements.txt
```

## Running

```bash
pip install -r requirements.txt
python app.py
# Open http://localhost:5000
```
