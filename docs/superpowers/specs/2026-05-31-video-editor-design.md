# Video Editor Features — Design Spec
**Date:** 2026-05-31

## Overview

Extend the existing video compressor app with trim, resolution, and audio editing features. All operations are applied in a single FFmpeg command alongside existing compression. The `/compress` route is replaced by `/process` which handles all parameters together.

## Requirements

- **Trim:** optional start time and end time (HH:MM:SS format); empty = use video start/end
- **Resolution:** dropdown — Original, 1080p, 720p, 480p, 360p
- **Audio:** mute checkbox OR volume slider (0–200%); mute takes priority if checked
- **Compression:** existing target MB, CRF, and output format controls retained
- All operations applied in one FFmpeg command (no intermediate files)
- Output delivered as browser download

## Architecture

```
Browser form (trim + resolution + audio + compression settings)
  → POST /process
    → validate_process_params() — validates all inputs
    → build_ffmpeg_args() — constructs single FFmpeg command
    → FFmpeg encodes → BytesIO → send_file() → browser download
```

Single `app.py` file. HTML template updated in-place. No new files.

## Components

### 1. Input Validation — `validate_process_params(form)`

Returns `(params_dict, error_string)`. Validates:
- `start_time`, `end_time`: optional, must match `HH:MM:SS` or `MM:SS` pattern; end > start if both given
- `resolution`: one of `original`, `1080p`, `720p`, `480p`, `360p`
- `mute`: boolean (checkbox)
- `volume`: int 0–200 (default 100)
- `target_mb`: float > 0
- `min_crf`: int 0–51
- `output_format`: one of `mp4`, `mkv`, `webm`

### 2. FFmpeg Command Builder — `build_ffmpeg_args(input_path, output_path, params, video_info)`

Returns a list of FFmpeg arguments. Applies all filters in one pass:

**Trim:** `-ss {start_time} -to {end_time}` (input-side seeking for speed)

**Resolution:** `-vf scale=-2:{height}` where height = 1080/720/480/360; omitted if "original"

**Audio:**
- Mute: `-an`
- Volume: `-af volume={volume/100}` (only if volume ≠ 100 and not muted)

**Encoding:** same 2-pass bitrate or CRF logic as existing `select_encoding_params()`. For 2-pass with trim, duration is recalculated from trimmed length.

**Note:** `-vf` and `-af` filters are combined if both resolution and volume are active:
- `-vf scale=-2:{height}` (video filter)
- `-af volume={vol}` (audio filter, separate flag)

### 3. `/process` Route

Replaces `/compress`. Accepts all form fields. Flow:
1. Validate file (same as before: required, not empty filename)
2. `validate_process_params(form)` → return 400 on error
3. Save upload to temp dir (`secure_filename`)
4. `get_video_info()` → duration, size
5. Calculate effective duration (after trim) for bitrate calculation
6. `build_ffmpeg_args()` → run FFmpeg
7. Read output into `BytesIO`, clean up temp dir
8. `send_file()` with `download_name = stem + "_processed.{format}"`

### 4. HTML Template Updates

Form additions below existing fields:

```
── Trim ──────────────────────────────────────
  Başlangıç: [00:00:00]    Bitiş: [00:00:00]
── Çözünürlük ────────────────────────────────
  [Orijinal ▾]
── Ses ───────────────────────────────────────
  [x] Sesi kapat (mute)
  Ses seviyesi: ──●────── 100%
```

Mute checkbox disables the volume slider when checked (JS).

## Error Handling

- Invalid time format → 400 with message
- End time ≤ start time → 400
- Volume out of range → 400
- FFmpeg failure → 500 with stderr excerpt
- Temp cleanup always in `finally`

## Removed

- `/compress` route — replaced by `/process`
- `encode_video()` function — replaced by `build_ffmpeg_args()` which is more flexible

## Tests

- `validate_process_params`: valid input, invalid time format, end ≤ start, invalid resolution, volume out of range
- `build_ffmpeg_args`: trim args present when times set, resolution scale arg correct, mute flag, volume filter, no extras when defaults used
- Flask routes: GET / returns 200, POST /process missing file → 400, invalid format → 400

**Note:** Existing tests for `encode_video`, `calculate_video_bitrate`, `select_encoding_params`, and `get_video_info` must be updated. `encode_video` is removed; `calculate_video_bitrate` and `select_encoding_params` are absorbed into `build_ffmpeg_args` logic. `get_video_info` stays unchanged.

## Project Structure

```
C:\Projects\video-compressor\
  app.py          ← all logic + embedded HTML
  requirements.txt
  test_app.py
```
