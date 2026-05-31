# Video Editor Features Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the existing video compressor with trim, resolution change, and audio controls, all applied in a single FFmpeg command via a new `/process` route.

**Architecture:** `encode_video()` is removed and replaced by `build_ffmpeg_args()` which builds a flexible FFmpeg command list. A new `validate_process_params()` handles all form validation. The `/compress` route is replaced by `/process`. The HTML template is updated in-place with new form fields.

**Tech Stack:** Python 3.9+, Flask, FFmpeg, re (stdlib), io (stdlib)

---

## File Map

| File | Changes |
|------|---------|
| `app.py` | Add `io`, `re` imports; add `_time_to_seconds`, `validate_process_params`, `build_ffmpeg_args`, `RESOLUTION_MAP`; remove `encode_video`; replace `/compress` with `/process`; update `HTML_TEMPLATE` |
| `test_app.py` | Remove 3 `encode_video` tests; update 2 `/compress` route tests to `/process`; add tests for `validate_process_params` and `build_ffmpeg_args` |

---

### Task 1: Refactor — Remove encode_video, Add Imports and Time Helper

**Files:**
- Modify: `C:\Projects\video-compressor\app.py`
- Modify: `C:\Projects\video-compressor\test_app.py`

- [ ] **Step 1: Remove encode_video tests from test_app.py**

Open `test_app.py` and delete these three test functions entirely (leave everything else):
- `test_encode_video_calls_ffmpeg_two_pass_for_bitrate_mode`
- `test_encode_video_calls_ffmpeg_single_pass_for_crf_mode`
- `test_encode_video_raises_on_ffmpeg_failure`

Also remove the line `from app import encode_video` at the top of the appended block.

The import block that remains should be:
```python
from app import get_video_info
# ... (first 3 tests for get_video_info) ...
from app import calculate_video_bitrate, select_encoding_params
# ... (5 tests for bitrate/encoding) ...
from app import app as flask_app
import io
# ... (3 route tests) ...
```

- [ ] **Step 2: Run tests to confirm only 8 pass now (3 removed)**

Run: `pytest test_app.py -v` from `C:\Projects\video-compressor`
Expected: 11 tests collected → 8 pass, 3 errors (encode_video import broken — expected).

Actually the import `from app import encode_video` will cause an error. Make sure that line is removed. After removing it and the 3 tests, run again:

Run: `pytest test_app.py -v`
Expected: **8 passed**

- [ ] **Step 3: Add io and re imports to app.py**

In `app.py`, change the top imports block from:
```python
import json
import os
import shutil
import subprocess
import tempfile
```
to:
```python
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
```

- [ ] **Step 4: Add _time_to_seconds and RESOLUTION_MAP to app.py**

After the `AUDIO_CODEC_MAP` dict and before `encode_video`, add:
```python

RESOLUTION_MAP = {
    "1080p": 1080,
    "720p": 720,
    "480p": 480,
    "360p": 360,
}

TIME_PATTERN = re.compile(r'^\d{1,2}:\d{2}:\d{2}$|^\d{2}:\d{2}$')


def _time_to_seconds(t: str) -> float:
    parts = t.split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
```

- [ ] **Step 5: Remove encode_video from app.py**

Delete the entire `encode_video` function (lines 84–141 in the original file).

- [ ] **Step 6: Fix the inline __import__("io") in the compress route**

In the `/compress` route, change:
```python
        response = send_file(
            __import__("io").BytesIO(file_bytes),
```
to:
```python
        response = send_file(
            io.BytesIO(file_bytes),
```

- [ ] **Step 7: Run tests to confirm still 8 passing**

Run: `pytest test_app.py -v`
Expected: **8 passed**

- [ ] **Step 8: Commit**

```bash
git add app.py test_app.py
git commit -m "refactor: remove encode_video, add io/re imports and time helper"
```

---

### Task 2: validate_process_params with TDD

**Files:**
- Modify: `C:\Projects\video-compressor\app.py`
- Modify: `C:\Projects\video-compressor\test_app.py`

- [ ] **Step 1: Write failing tests**

APPEND to the end of `test_app.py`:

```python
from app import validate_process_params

VALID_FORM = {
    "start_time": "",
    "end_time": "",
    "resolution": "original",
    "volume": "100",
    "target_mb": "50",
    "min_crf": "23",
    "output_format": "mp4",
}


def test_validate_valid_params_returns_no_error():
    params, err = validate_process_params(VALID_FORM)
    assert err == ""
    assert params["target_mb"] == 50.0
    assert params["min_crf"] == 23
    assert params["output_format"] == "mp4"
    assert params["mute"] is False
    assert params["volume"] == 100
    assert params["resolution"] == "original"


def test_validate_invalid_start_time_format():
    form = {**VALID_FORM, "start_time": "1234"}
    _, err = validate_process_params(form)
    assert err != ""
    assert "başlangıç" in err.lower() or "zaman" in err.lower()


def test_validate_end_before_start():
    form = {**VALID_FORM, "start_time": "00:01:00", "end_time": "00:00:30"}
    _, err = validate_process_params(form)
    assert err != ""
    assert "bitiş" in err.lower() or "başlangıç" in err.lower()


def test_validate_invalid_resolution():
    form = {**VALID_FORM, "resolution": "8k"}
    _, err = validate_process_params(form)
    assert err != ""


def test_validate_volume_out_of_range():
    form = {**VALID_FORM, "volume": "300"}
    _, err = validate_process_params(form)
    assert err != ""


def test_validate_invalid_crf():
    form = {**VALID_FORM, "min_crf": "99"}
    _, err = validate_process_params(form)
    assert err != ""


def test_validate_mute_checkbox_on():
    form = {**VALID_FORM, "mute": "on"}
    params, err = validate_process_params(form)
    assert err == ""
    assert params["mute"] is True
```

- [ ] **Step 2: Run tests to verify new ones fail**

Run: `pytest test_app.py -v`
Expected: 8 pass, 7 fail with ImportError for `validate_process_params`.

- [ ] **Step 3: Implement validate_process_params in app.py**

Add this function AFTER `_time_to_seconds` and BEFORE the HTML template:

```python

def validate_process_params(form) -> tuple[dict, str]:
    params = {}

    start_time = (form.get("start_time") or "").strip()
    end_time = (form.get("end_time") or "").strip()
    if start_time and not TIME_PATTERN.match(start_time):
        return {}, "Geçersiz başlangıç zamanı formatı (ÖR: 00:01:30)"
    if end_time and not TIME_PATTERN.match(end_time):
        return {}, "Geçersiz bitiş zamanı formatı (ÖR: 00:02:00)"
    if start_time and end_time and _time_to_seconds(end_time) <= _time_to_seconds(start_time):
        return {}, "Bitiş zamanı başlangıç zamanından büyük olmalı"
    params["start_time"] = start_time
    params["end_time"] = end_time

    resolution = form.get("resolution", "original")
    if resolution not in ("original", "1080p", "720p", "480p", "360p"):
        return {}, f"Geçersiz çözünürlük: {resolution}"
    params["resolution"] = resolution

    params["mute"] = form.get("mute") == "on"

    try:
        volume = int(form.get("volume", 100))
    except (ValueError, TypeError):
        return {}, "Geçersiz ses seviyesi"
    if not 0 <= volume <= 200:
        return {}, "Ses seviyesi 0-200 arasında olmalı"
    params["volume"] = volume

    try:
        target_mb = float(form.get("target_mb", 50))
        min_crf = int(form.get("min_crf", 23))
    except (ValueError, TypeError):
        return {}, "Geçersiz boyut veya kalite değeri"
    if target_mb <= 0:
        return {}, "Hedef boyut 0'dan büyük olmalı"
    if not 0 <= min_crf <= 51:
        return {}, "CRF değeri 0-51 arasında olmalı"
    params["target_mb"] = target_mb
    params["min_crf"] = min_crf

    output_format = (form.get("output_format") or "mp4").lower()
    if output_format not in ALLOWED_FORMATS:
        return {}, f"Geçersiz format: {output_format}"
    params["output_format"] = output_format

    return params, ""
```

- [ ] **Step 4: Run all tests**

Run: `pytest test_app.py -v`
Expected: **15 passed**

- [ ] **Step 5: Commit**

```bash
git add app.py test_app.py
git commit -m "feat: add validate_process_params"
```

---

### Task 3: build_ffmpeg_args with TDD

**Files:**
- Modify: `C:\Projects\video-compressor\app.py`
- Modify: `C:\Projects\video-compressor\test_app.py`

- [ ] **Step 1: Write failing tests**

APPEND to the end of `test_app.py`:

```python
from app import build_ffmpeg_args

BASE_PARAMS = {
    "start_time": "",
    "end_time": "",
    "resolution": "original",
    "mute": False,
    "volume": 100,
    "target_mb": 50.0,
    "min_crf": 23,
    "output_format": "mp4",
}


def test_build_ffmpeg_args_crf_mode_returns_one_command():
    # 50MB target, 60s video at CRF 23 — CRF floor heuristic will pick CRF for very short videos
    # Force CRF by making bitrate floor kick in: use min_crf=0 (high quality floor)
    params = {**BASE_PARAMS, "min_crf": 0}
    commands, _ = build_ffmpeg_args("in.mp4", "out.mp4", params, 60.0)
    assert len(commands) == 1
    assert "-crf" in commands[0]


def test_build_ffmpeg_args_bitrate_mode_returns_two_commands():
    # Low quality floor (high CRF = 51) means bitrate mode wins
    params = {**BASE_PARAMS, "min_crf": 51}
    commands, _ = build_ffmpeg_args("in.mp4", "out.mp4", params, 60.0)
    assert len(commands) == 2
    assert "-pass" in commands[0] and "1" in commands[0]
    assert "-pass" in commands[1] and "2" in commands[1]


def test_build_ffmpeg_args_trim_adds_ss_and_t():
    params = {**BASE_PARAMS, "start_time": "00:00:30", "end_time": "00:01:00"}
    commands, _ = build_ffmpeg_args("in.mp4", "out.mp4", params, 120.0)
    first_cmd = commands[0]
    assert "-ss" in first_cmd
    assert "00:00:30" in first_cmd
    assert "-t" in first_cmd
    assert "30.0" in first_cmd or "30" in first_cmd


def test_build_ffmpeg_args_resolution_adds_vf_scale():
    params = {**BASE_PARAMS, "resolution": "720p", "min_crf": 51}
    commands, _ = build_ffmpeg_args("in.mp4", "out.mp4", params, 60.0)
    all_args = " ".join(commands[-1])
    assert "scale=-2:720" in all_args


def test_build_ffmpeg_args_mute_adds_an():
    params = {**BASE_PARAMS, "mute": True, "min_crf": 51}
    commands, _ = build_ffmpeg_args("in.mp4", "out.mp4", params, 60.0)
    last_cmd = commands[-1]
    assert "-an" in last_cmd
    assert "-c:a" not in last_cmd


def test_build_ffmpeg_args_volume_adds_af():
    params = {**BASE_PARAMS, "volume": 150, "min_crf": 51}
    commands, _ = build_ffmpeg_args("in.mp4", "out.mp4", params, 60.0)
    all_args = " ".join(commands[-1])
    assert "volume=1.50" in all_args


def test_build_ffmpeg_args_default_volume_no_af():
    params = {**BASE_PARAMS, "volume": 100, "min_crf": 51}
    commands, _ = build_ffmpeg_args("in.mp4", "out.mp4", params, 60.0)
    all_args = " ".join(commands[-1])
    assert "volume=" not in all_args
```

- [ ] **Step 2: Run tests to verify new ones fail**

Run: `pytest test_app.py -v`
Expected: 15 pass, 7 fail with ImportError for `build_ffmpeg_args`.

- [ ] **Step 3: Implement build_ffmpeg_args in app.py**

Add this function AFTER `validate_process_params` and BEFORE `HTML_TEMPLATE`:

```python

def build_ffmpeg_args(
    input_path: str,
    output_path: str,
    params: dict,
    video_duration: float,
) -> tuple[list[list[str]], str]:
    output_format = params["output_format"]
    video_codec = CODEC_MAP[output_format]
    audio_codec = AUDIO_CODEC_MAP[output_format]

    start_secs = _time_to_seconds(params["start_time"]) if params["start_time"] else 0.0
    end_secs = _time_to_seconds(params["end_time"]) if params["end_time"] else video_duration
    effective_duration = max(end_secs - start_secs, 1.0)

    video_bitrate = calculate_video_bitrate(params["target_mb"], effective_duration)
    enc = select_encoding_params(video_bitrate, params["min_crf"], output_format)
    warning = enc.get("warning", "")

    seek_args = []
    if params["start_time"]:
        seek_args += ["-ss", params["start_time"]]

    trim_args = []
    if params["start_time"] or params["end_time"]:
        trim_args = ["-t", str(effective_duration)]

    vf_args = []
    if params["resolution"] in RESOLUTION_MAP:
        height = RESOLUTION_MAP[params["resolution"]]
        vf_args = ["-vf", f"scale=-2:{height}"]

    if params["mute"]:
        audio_args = ["-an"]
    else:
        audio_args = ["-c:a", audio_codec, "-b:a", "128k"]
        if params["volume"] != 100:
            audio_args += ["-af", f"volume={params['volume'] / 100:.2f}"]

    passlogfile = os.path.join(tempfile.gettempdir(), "ffmpeg2pass")
    pass1_fmt = "webm" if output_format == "webm" else "null"

    def base_cmd():
        return ["ffmpeg", "-y"] + seek_args + ["-i", input_path] + trim_args + ["-c:v", video_codec]

    if enc["mode"] == "bitrate":
        pass1 = base_cmd() + ["-b:v", f"{enc['bitrate']}k"] + vf_args + [
            "-pass", "1", "-passlogfile", passlogfile,
            "-an", "-f", pass1_fmt, os.devnull,
        ]
        pass2 = base_cmd() + ["-b:v", f"{enc['bitrate']}k"] + vf_args + [
            "-pass", "2", "-passlogfile", passlogfile,
        ] + audio_args + [output_path]
        return [pass1, pass2], warning
    else:
        cmd = base_cmd() + ["-crf", str(enc["crf"])] + vf_args + audio_args + [output_path]
        return [cmd], warning
```

- [ ] **Step 4: Run all tests**

Run: `pytest test_app.py -v`
Expected: **22 passed**

- [ ] **Step 5: Commit**

```bash
git add app.py test_app.py
git commit -m "feat: add build_ffmpeg_args"
```

---

### Task 4: /process Route, HTML Update, and Test Fixes

**Files:**
- Modify: `C:\Projects\video-compressor\app.py`
- Modify: `C:\Projects\video-compressor\test_app.py`

- [ ] **Step 1: Update route tests in test_app.py**

Find and replace the existing 3 route tests at the bottom of `test_app.py`. Replace these functions:

```python
def test_index_returns_200():
    with flask_app.test_client() as client:
        response = client.get("/")
    assert response.status_code == 200
    assert b"Video" in response.data


def test_compress_missing_file_returns_400():
    with flask_app.test_client() as client:
        response = client.post("/compress", data={
            "target_mb": "10",
            "min_crf": "23",
            "output_format": "mp4",
        })
    assert response.status_code == 400


def test_compress_invalid_format_returns_400():
    video_bytes = io.BytesIO(b"fake video content")
    with flask_app.test_client() as client:
        response = client.post("/compress", data={
            "video": (video_bytes, "test.mp4"),
            "target_mb": "10",
            "min_crf": "23",
            "output_format": "avi",
        })
    assert response.status_code == 400
```

with these:

```python
def test_index_returns_200():
    with flask_app.test_client() as client:
        response = client.get("/")
    assert response.status_code == 200
    assert b"Video" in response.data


def test_process_missing_file_returns_400():
    with flask_app.test_client() as client:
        response = client.post("/process", data={
            "target_mb": "10",
            "min_crf": "23",
            "output_format": "mp4",
            "resolution": "original",
            "volume": "100",
            "start_time": "",
            "end_time": "",
        })
    assert response.status_code == 400


def test_process_invalid_format_returns_400():
    video_bytes = io.BytesIO(b"fake video content")
    with flask_app.test_client() as client:
        response = client.post("/process", data={
            "video": (video_bytes, "test.mp4"),
            "target_mb": "10",
            "min_crf": "23",
            "output_format": "avi",
            "resolution": "original",
            "volume": "100",
            "start_time": "",
            "end_time": "",
        })
    assert response.status_code == 400


def test_process_invalid_crf_returns_400():
    video_bytes = io.BytesIO(b"fake video content")
    with flask_app.test_client() as client:
        response = client.post("/process", data={
            "video": (video_bytes, "test.mp4"),
            "target_mb": "10",
            "min_crf": "99",
            "output_format": "mp4",
            "resolution": "original",
            "volume": "100",
            "start_time": "",
            "end_time": "",
        })
    assert response.status_code == 400
```

- [ ] **Step 2: Run tests — expect 3 route tests to fail**

Run: `pytest test_app.py -v`
Expected: 19 pass (the renamed/new route tests fail because `/process` doesn't exist yet).

- [ ] **Step 3: Replace /compress route with /process in app.py**

Find the entire `/compress` route function and replace it with `/process`:

```python
@app.route("/process", methods=["POST"])
def process():
    if "video" not in request.files or request.files["video"].filename == "":
        return jsonify({"error": "Video dosyası seçilmedi"}), 400

    params, err = validate_process_params(request.form)
    if err:
        return jsonify({"error": err}), 400

    video_file = request.files["video"]
    safe_name = secure_filename(video_file.filename) or "input.mp4"
    tmp_dir = tempfile.mkdtemp()

    try:
        input_path = os.path.join(tmp_dir, "input_" + safe_name)
        video_file.save(input_path)

        video_info = get_video_info(input_path)

        stem = os.path.splitext(safe_name)[0]
        output_filename = f"{stem}_processed.{params['output_format']}"
        output_path = os.path.join(tmp_dir, output_filename)

        commands, warning = build_ffmpeg_args(input_path, output_path, params, video_info["duration"])

        for cmd in commands:
            try:
                subprocess.run(cmd, capture_output=True, text=True, check=True)
            except subprocess.CalledProcessError as e:
                raise RuntimeError(f"ffmpeg başarısız oldu: {e.stderr}") from e
            except FileNotFoundError:
                raise RuntimeError("ffmpeg bulunamadı — FFmpeg'i kurun ve PATH'e ekleyin")

        with open(output_path, "rb") as f:
            file_bytes = f.read()

        response = send_file(
            io.BytesIO(file_bytes),
            as_attachment=True,
            download_name=output_filename,
            mimetype="application/octet-stream",
        )
        if warning:
            response.headers["X-Warning"] = warning
        return response

    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
```

Also delete the old `/compress` route entirely.

- [ ] **Step 4: Update HTML_TEMPLATE in app.py**

Replace the entire `HTML_TEMPLATE` string with this updated version:

```python
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Video İşleyici</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: system-ui, sans-serif; max-width: 580px; margin: 48px auto; padding: 0 20px; color: #1a1a1a; }
  h1 { font-size: 1.5rem; margin-bottom: 24px; }
  .section-title { font-size: 0.7rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: #6b7280; margin: 20px 0 10px; border-top: 1px solid #e5e7eb; padding-top: 16px; }
  .group { margin-bottom: 14px; }
  .row { display: flex; gap: 12px; }
  .row .group { flex: 1; }
  label { display: block; font-size: 0.875rem; font-weight: 600; margin-bottom: 6px; }
  input[type=file], input[type=number], input[type=text], select {
    width: 100%; padding: 9px 12px; border: 1px solid #d1d5db; border-radius: 6px;
    font-size: 0.9rem; background: #fff;
  }
  input[type=range] { width: 100%; accent-color: #2563eb; }
  input[type=checkbox] { width: 16px; height: 16px; margin-right: 6px; cursor: pointer; accent-color: #2563eb; }
  .check-label { display: flex; align-items: center; font-size: 0.875rem; font-weight: 600; cursor: pointer; }
  .scale-labels { display: flex; justify-content: space-between; font-size: 0.72rem; color: #6b7280; margin-top: 2px; }
  button {
    width: 100%; padding: 12px; background: #2563eb; color: #fff;
    border: none; border-radius: 6px; font-size: 1rem; font-weight: 600;
    cursor: pointer; transition: background 0.2s; margin-top: 8px;
  }
  button:hover:not(:disabled) { background: #1d4ed8; }
  button:disabled { background: #93c5fd; cursor: not-allowed; }
  .status { text-align: center; margin-top: 14px; font-size: 0.9rem; color: #4b5563; display: none; }
  .warning { background: #fef9c3; border: 1px solid #fbbf24; border-radius: 6px; padding: 12px; margin-top: 16px; font-size: 0.875rem; }
  .error-box { background: #fee2e2; border: 1px solid #f87171; border-radius: 6px; padding: 12px; margin-top: 16px; font-size: 0.875rem; }
  .dimmed { opacity: 0.4; pointer-events: none; }
</style>
</head>
<body>
<h1>Video İşleyici</h1>
<form id="form">

  <div class="group">
    <label>Video Dosyası</label>
    <input type="file" id="video" accept="video/*" required>
  </div>

  <div class="section-title">Kırpma</div>
  <div class="row">
    <div class="group">
      <label>Başlangıç</label>
      <input type="text" id="start_time" placeholder="00:00:00">
    </div>
    <div class="group">
      <label>Bitiş</label>
      <input type="text" id="end_time" placeholder="00:00:00">
    </div>
  </div>

  <div class="section-title">Görüntü</div>
  <div class="group">
    <label>Çözünürlük</label>
    <select id="resolution">
      <option value="original">Orijinal</option>
      <option value="1080p">1080p</option>
      <option value="720p">720p</option>
      <option value="480p">480p</option>
      <option value="360p">360p</option>
    </select>
  </div>

  <div class="section-title">Ses</div>
  <div class="group">
    <label class="check-label">
      <input type="checkbox" id="mute" onchange="toggleVol(this.checked)">
      Sesi kapat (mute)
    </label>
  </div>
  <div class="group" id="volGroup">
    <label>Ses Seviyesi: <span id="volVal">100</span>%</label>
    <input type="range" id="volume" min="0" max="200" value="100"
           oninput="document.getElementById('volVal').textContent=this.value">
    <div class="scale-labels"><span>0%</span><span>Orijinal (100%)</span><span>200%</span></div>
  </div>

  <div class="section-title">Sıkıştırma</div>
  <div class="group">
    <label>Hedef Boyut (MB)</label>
    <input type="number" id="target_mb" min="1" step="0.1" value="50" required>
  </div>
  <div class="group">
    <label>Minimum Kalite — CRF: <span id="crfVal">23</span></label>
    <input type="range" id="min_crf" min="0" max="51" value="23"
           oninput="document.getElementById('crfVal').textContent=this.value">
    <div class="scale-labels"><span>En iyi kalite (0)</span><span>En küçük dosya (51)</span></div>
  </div>
  <div class="group">
    <label>Çıktı Formatı</label>
    <select id="output_format">
      <option value="mp4">MP4</option>
      <option value="mkv">MKV</option>
      <option value="webm">WebM</option>
    </select>
  </div>

  <button type="submit" id="btn">İşle ve İndir</button>
</form>
<p class="status" id="status">İşleniyor, lütfen bekleyin...</p>
<div id="msg"></div>

<script>
function toggleVol(muted) {
  document.getElementById('volGroup').classList.toggle('dimmed', muted);
}

document.getElementById('form').onsubmit = async function(e) {
  e.preventDefault();
  const btn = document.getElementById('btn');
  const status = document.getElementById('status');
  const msg = document.getElementById('msg');
  msg.innerHTML = '';
  btn.disabled = true;
  status.style.display = 'block';

  const fd = new FormData();
  fd.append('video', document.getElementById('video').files[0]);
  fd.append('start_time', document.getElementById('start_time').value);
  fd.append('end_time', document.getElementById('end_time').value);
  fd.append('resolution', document.getElementById('resolution').value);
  if (document.getElementById('mute').checked) fd.append('mute', 'on');
  fd.append('volume', document.getElementById('volume').value);
  fd.append('target_mb', document.getElementById('target_mb').value);
  fd.append('min_crf', document.getElementById('min_crf').value);
  fd.append('output_format', document.getElementById('output_format').value);

  try {
    const res = await fetch('/process', {method: 'POST', body: fd});
    if (res.ok && !res.headers.get('Content-Type').includes('application/json')) {
      const warning = res.headers.get('X-Warning');
      if (warning) msg.innerHTML = '<div class="warning">' + warning + '</div>';
      const blob = await res.blob();
      const disp = res.headers.get('Content-Disposition') || '';
      const match = disp.match(/filename="?([^"]+)"?/);
      const filename = match ? match[1] : 'output.mp4';
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = filename; a.click();
      URL.revokeObjectURL(url);
    } else {
      const data = await res.json();
      msg.innerHTML = '<div class="error-box">' + (data.error || 'Hata oluştu') + '</div>';
    }
  } catch(err) {
    msg.innerHTML = '<div class="error-box">Bağlantı hatası: ' + err.message + '</div>';
  } finally {
    btn.disabled = false;
    status.style.display = 'none';
  }
};
</script>
</body>
</html>"""
```

- [ ] **Step 5: Run all tests**

Run: `pytest test_app.py -v`
Expected: **23 passed**

- [ ] **Step 6: Commit**

```bash
git add app.py test_app.py
git commit -m "feat: add /process route, update HTML with trim/resolution/audio controls"
```

- [ ] **Step 7: Manual smoke test**

Run: `python app.py` from `C:\Projects\video-compressor`
Open `http://localhost:5000` in browser.

Verify:
- Page title is "Video İşleyici"
- Form shows Kırpma, Görüntü, Ses, Sıkıştırma sections
- Mute checkbox grays out the volume slider
- Select a small video, set trim times, pick 720p, submit
- File downloads as `filename_processed.mp4`

- [ ] **Step 8: Push to GitHub**

```bash
git push origin master
```
