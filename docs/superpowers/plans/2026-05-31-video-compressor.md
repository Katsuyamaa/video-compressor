# Video Compressor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a localhost web app where the user uploads a video, sets a target MB and minimum quality (CRF), picks an output format, and downloads the compressed result.

**Architecture:** Single Flask app (`app.py`) runs on `localhost:5000`. HTML is embedded as a string in `app.py` via `render_template_string`. FFmpeg handles video encoding via 2-pass bitrate mode or CRF mode depending on which constraint is more conservative. All temp files are cleaned up after download.

**Tech Stack:** Python 3.9+, Flask, FFmpeg (system install), ffprobe (bundled with FFmpeg)

---

## File Map

| File | Purpose |
|------|---------|
| `app.py` | All logic: Flask routes, video info, bitrate calc, encoding, HTML template |
| `requirements.txt` | Python dependencies |
| `test_app.py` | Unit tests for pure functions and Flask routes |

---

### Task 1: Project Setup

**Files:**
- Create: `C:\Projects\requirements.txt`
- Create: `C:\Projects\test_app.py` (empty placeholder)

- [ ] **Step 1: Create requirements.txt**

```
flask==3.0.3
pytest==8.2.0
```

- [ ] **Step 2: Install dependencies**

Run: `pip install -r requirements.txt`
Expected: Flask and pytest installed successfully.

- [ ] **Step 3: Verify FFmpeg is available**

Run: `ffmpeg -version`
Expected: FFmpeg version info printed. If not found, install from https://ffmpeg.org/download.html and add to PATH.

- [ ] **Step 4: Create empty test file**

Create `test_app.py`:
```python
# tests for app.py pure functions
```

- [ ] **Step 5: Commit**

```bash
git init
git add requirements.txt test_app.py
git commit -m "feat: project scaffold"
```

---

### Task 2: Video Info Extraction

**Files:**
- Modify: `C:\Projects\app.py` (create if not exists)
- Modify: `C:\Projects\test_app.py`

- [ ] **Step 1: Write failing tests**

In `test_app.py`:
```python
import json
import subprocess
from unittest.mock import patch, MagicMock
from app import get_video_info


def test_get_video_info_returns_duration_and_size():
    fake_output = json.dumps({
        "format": {
            "duration": "120.5",
            "size": "52428800"
        }
    })
    mock_result = MagicMock()
    mock_result.stdout = fake_output

    with patch("subprocess.run", return_value=mock_result):
        info = get_video_info("fake.mp4")

    assert info["duration"] == 120.5
    assert info["size_bytes"] == 52428800


def test_get_video_info_raises_on_ffprobe_failure():
    with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "ffprobe")):
        try:
            get_video_info("fake.mp4")
            assert False, "expected RuntimeError"
        except RuntimeError as e:
            assert "ffprobe" in str(e).lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest test_app.py::test_get_video_info_returns_duration_and_size -v`
Expected: `ImportError` or `ModuleNotFoundError` (app.py doesn't exist yet).

- [ ] **Step 3: Implement get_video_info in app.py**

Create `app.py`:
```python
import json
import os
import subprocess
import tempfile

from flask import Flask, render_template_string, request, send_file, jsonify

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 4 * 1024 * 1024 * 1024  # 4 GB upload limit


def get_video_info(filepath: str) -> dict:
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                filepath,
            ],
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffprobe failed: {e.stderr}") from e
    except FileNotFoundError:
        raise RuntimeError("ffprobe not found — install FFmpeg and add it to PATH")

    data = json.loads(result.stdout)
    fmt = data["format"]
    return {
        "duration": float(fmt["duration"]),
        "size_bytes": int(fmt["size"]),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest test_app.py -v`
Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app.py test_app.py
git commit -m "feat: add get_video_info with ffprobe"
```

---

### Task 3: Bitrate Calculation and Encoding Mode Selection

**Files:**
- Modify: `C:\Projects\app.py`
- Modify: `C:\Projects\test_app.py`

- [ ] **Step 1: Write failing tests**

Append to `test_app.py`:
```python
from app import calculate_video_bitrate, select_encoding_params


def test_calculate_video_bitrate_basic():
    # target 10 MB, 60s video, 128kbps audio
    # target_bits = 10 * 8 * 1024 * 1024 = 83886080
    # audio_bits = 128000 * 60 = 7680000
    # video_bits = 83886080 - 7680000 = 76206080
    # video_kbps = 76206080 / 60 / 1000 = 1270
    result = calculate_video_bitrate(target_mb=10.0, duration_seconds=60.0)
    assert result == 1270


def test_calculate_video_bitrate_minimum_floor():
    # Very small target should return minimum 50 kbps, not negative
    result = calculate_video_bitrate(target_mb=0.01, duration_seconds=3600.0)
    assert result == 50


def test_select_encoding_params_uses_bitrate_when_high_enough():
    # 1000 kbps target, CRF 35 floor (very low quality floor)
    params = select_encoding_params(video_bitrate_kbps=1000, min_crf=35, output_format="mp4")
    assert params["mode"] == "bitrate"
    assert params["bitrate"] == 1000


def test_select_encoding_params_uses_crf_when_bitrate_too_low():
    # 50 kbps target, CRF 18 floor (high quality floor) — CRF wins
    params = select_encoding_params(video_bitrate_kbps=50, min_crf=18, output_format="mp4")
    assert params["mode"] == "crf"
    assert params["crf"] == 18


def test_select_encoding_params_crf_mode_returns_warning():
    params = select_encoding_params(video_bitrate_kbps=50, min_crf=18, output_format="mp4")
    assert "warning" in params
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest test_app.py -v`
Expected: ImportError for `calculate_video_bitrate` and `select_encoding_params`.

- [ ] **Step 3: Implement both functions in app.py**

Append to `app.py` (after `get_video_info`):
```python
def calculate_video_bitrate(
    target_mb: float,
    duration_seconds: float,
    audio_bitrate_kbps: int = 128,
) -> int:
    target_bits = target_mb * 8 * 1024 * 1024
    audio_bits = audio_bitrate_kbps * 1000 * duration_seconds
    video_bits = target_bits - audio_bits
    video_bitrate_kbps = int(video_bits / duration_seconds / 1000)
    return max(video_bitrate_kbps, 50)


def select_encoding_params(
    video_bitrate_kbps: int,
    min_crf: int,
    output_format: str,
) -> dict:
    # Heuristic: estimate bitrate that CRF min_crf would produce
    # Formula: kbps ≈ 150 * 2^((51 - crf) / 8)
    import math
    crf_floor_kbps = int(150 * (2 ** ((51 - min_crf) / 8)))

    if video_bitrate_kbps >= crf_floor_kbps:
        return {"mode": "bitrate", "bitrate": video_bitrate_kbps}
    else:
        return {
            "mode": "crf",
            "crf": min_crf,
            "warning": (
                f"Hedef boyut çok küçük — kalite sınırı (CRF {min_crf}) devreye girdi. "
                f"Çıktı dosyası hedeften büyük olabilir."
            ),
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest test_app.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app.py test_app.py
git commit -m "feat: add bitrate calculation and encoding mode selection"
```

---

### Task 4: FFmpeg Encoding Function

**Files:**
- Modify: `C:\Projects\app.py`
- Modify: `C:\Projects\test_app.py`

- [ ] **Step 1: Write failing tests**

Append to `test_app.py`:
```python
from app import encode_video


def test_encode_video_calls_ffmpeg_two_pass_for_bitrate_mode(tmp_path):
    output = str(tmp_path / "out.mp4")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        m = MagicMock()
        m.returncode = 0
        return m

    with patch("subprocess.run", side_effect=fake_run):
        encode_video(
            input_path="input.mp4",
            output_path=output,
            params={"mode": "bitrate", "bitrate": 500},
            output_format="mp4",
        )

    assert len(calls) == 2
    assert "-pass" in calls[0] and "1" in calls[0]
    assert "-pass" in calls[1] and "2" in calls[1]


def test_encode_video_calls_ffmpeg_single_pass_for_crf_mode(tmp_path):
    output = str(tmp_path / "out.mp4")
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        m = MagicMock()
        m.returncode = 0
        return m

    with patch("subprocess.run", side_effect=fake_run):
        encode_video(
            input_path="input.mp4",
            output_path=output,
            params={"mode": "crf", "crf": 23, "warning": "..."},
            output_format="mp4",
        )

    assert len(calls) == 1
    assert "-crf" in calls[0]


def test_encode_video_raises_on_ffmpeg_failure(tmp_path):
    output = str(tmp_path / "out.mp4")

    with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "ffmpeg", stderr="error")):
        try:
            encode_video(
                input_path="input.mp4",
                output_path=output,
                params={"mode": "crf", "crf": 23},
                output_format="mp4",
            )
            assert False, "expected RuntimeError"
        except RuntimeError as e:
            assert "ffmpeg" in str(e).lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest test_app.py -v`
Expected: ImportError for `encode_video`.

- [ ] **Step 3: Implement encode_video in app.py**

Append to `app.py` (after `select_encoding_params`):
```python
CODEC_MAP = {
    "mp4": "libx264",
    "mkv": "libx264",
    "webm": "libvpx-vp9",
}
AUDIO_CODEC_MAP = {
    "mp4": "aac",
    "mkv": "aac",
    "webm": "libopus",
}


def encode_video(
    input_path: str,
    output_path: str,
    params: dict,
    output_format: str,
) -> None:
    video_codec = CODEC_MAP[output_format]
    audio_codec = AUDIO_CODEC_MAP[output_format]

    try:
        if params["mode"] == "bitrate":
            passlogfile = os.path.join(tempfile.gettempdir(), "ffmpeg2pass")
            pass1_format = "webm" if output_format == "webm" else "null"

            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", input_path,
                    "-c:v", video_codec,
                    "-b:v", f"{params['bitrate']}k",
                    "-pass", "1", "-passlogfile", passlogfile,
                    "-an", "-f", pass1_format, os.devnull,
                ],
                capture_output=True,
                text=True,
                check=True,
            )
            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", input_path,
                    "-c:v", video_codec,
                    "-b:v", f"{params['bitrate']}k",
                    "-pass", "2", "-passlogfile", passlogfile,
                    "-c:a", audio_codec, "-b:a", "128k",
                    output_path,
                ],
                capture_output=True,
                text=True,
                check=True,
            )

        else:  # CRF mode
            subprocess.run(
                [
                    "ffmpeg", "-y", "-i", input_path,
                    "-c:v", video_codec,
                    "-crf", str(params["crf"]),
                    "-c:a", audio_codec, "-b:a", "128k",
                    output_path,
                ],
                capture_output=True,
                text=True,
                check=True,
            )

    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"ffmpeg encoding failed: {e.stderr}") from e
    except FileNotFoundError:
        raise RuntimeError("ffmpeg not found — install FFmpeg and add it to PATH")
```

- [ ] **Step 4: Run all tests**

Run: `pytest test_app.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app.py test_app.py
git commit -m "feat: add encode_video with 2-pass bitrate and CRF modes"
```

---

### Task 5: Flask Routes and Embedded HTML

**Files:**
- Modify: `C:\Projects\app.py`
- Modify: `C:\Projects\test_app.py`

- [ ] **Step 1: Write failing route tests**

Append to `test_app.py`:
```python
from app import app as flask_app
import io


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
    video_bytes.name = "test.mp4"
    with flask_app.test_client() as client:
        response = client.post("/compress", data={
            "video": (video_bytes, "test.mp4"),
            "target_mb": "10",
            "min_crf": "23",
            "output_format": "avi",  # not allowed
        })
    assert response.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest test_app.py::test_index_returns_200 -v`
Expected: FAIL (no routes defined yet).

- [ ] **Step 3: Add HTML template string and routes to app.py**

Append to `app.py` (after `encode_video`):
```python
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Video Sıkıştırıcı</title>
<style>
  * { box-sizing: border-box; }
  body { font-family: system-ui, sans-serif; max-width: 560px; margin: 48px auto; padding: 0 20px; color: #1a1a1a; }
  h1 { font-size: 1.5rem; margin-bottom: 24px; }
  .group { margin-bottom: 18px; }
  label { display: block; font-size: 0.875rem; font-weight: 600; margin-bottom: 6px; }
  input[type=file], input[type=number], select {
    width: 100%; padding: 9px 12px; border: 1px solid #d1d5db; border-radius: 6px;
    font-size: 0.9rem; background: #fff;
  }
  input[type=range] { width: 100%; accent-color: #2563eb; }
  .crf-labels { display: flex; justify-content: space-between; font-size: 0.75rem; color: #6b7280; margin-top: 2px; }
  button {
    width: 100%; padding: 12px; background: #2563eb; color: #fff;
    border: none; border-radius: 6px; font-size: 1rem; font-weight: 600;
    cursor: pointer; transition: background 0.2s;
  }
  button:hover:not(:disabled) { background: #1d4ed8; }
  button:disabled { background: #93c5fd; cursor: not-allowed; }
  .status { text-align: center; margin-top: 14px; font-size: 0.9rem; color: #4b5563; display: none; }
  .warning { background: #fef9c3; border: 1px solid #fbbf24; border-radius: 6px; padding: 12px; margin-top: 16px; font-size: 0.875rem; }
  .error-box { background: #fee2e2; border: 1px solid #f87171; border-radius: 6px; padding: 12px; margin-top: 16px; font-size: 0.875rem; }
</style>
</head>
<body>
<h1>Video Sıkıştırıcı</h1>
<form id="form">
  <div class="group">
    <label>Video Dosyası</label>
    <input type="file" id="video" accept="video/*" required>
  </div>
  <div class="group">
    <label>Hedef Boyut (MB)</label>
    <input type="number" id="target_mb" min="1" step="0.1" value="50" required>
  </div>
  <div class="group">
    <label>Minimum Kalite Eşiği — CRF: <span id="crfVal">23</span></label>
    <input type="range" id="min_crf" min="0" max="51" value="23"
           oninput="document.getElementById('crfVal').textContent=this.value">
    <div class="crf-labels"><span>En iyi kalite (0)</span><span>En küçük dosya (51)</span></div>
  </div>
  <div class="group">
    <label>Çıktı Formatı</label>
    <select id="output_format">
      <option value="mp4">MP4</option>
      <option value="mkv">MKV</option>
      <option value="webm">WebM</option>
    </select>
  </div>
  <button type="submit" id="btn">Sıkıştır ve İndir</button>
</form>
<p class="status" id="status">Sıkıştırılıyor, lütfen bekleyin...</p>
<div id="msg"></div>

<script>
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
  fd.append('target_mb', document.getElementById('target_mb').value);
  fd.append('min_crf', document.getElementById('min_crf').value);
  fd.append('output_format', document.getElementById('output_format').value);

  try {
    const res = await fetch('/compress', {method: 'POST', body: fd});
    if (res.ok && res.headers.get('Content-Type') !== 'application/json') {
      const warning = res.headers.get('X-Warning');
      if (warning) {
        msg.innerHTML = '<div class="warning">' + warning + '</div>';
      }
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

ALLOWED_FORMATS = {"mp4", "mkv", "webm"}


@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route("/compress", methods=["POST"])
def compress():
    if "video" not in request.files or request.files["video"].filename == "":
        return jsonify({"error": "Video dosyası seçilmedi"}), 400

    output_format = request.form.get("output_format", "mp4").lower()
    if output_format not in ALLOWED_FORMATS:
        return jsonify({"error": f"Geçersiz format: {output_format}"}), 400

    try:
        target_mb = float(request.form.get("target_mb", 50))
        min_crf = int(request.form.get("min_crf", 23))
    except ValueError:
        return jsonify({"error": "Geçersiz boyut veya kalite değeri"}), 400

    video_file = request.files["video"]
    tmp_dir = tempfile.mkdtemp()

    try:
        input_path = os.path.join(tmp_dir, "input_" + video_file.filename)
        video_file.save(input_path)

        info = get_video_info(input_path)
        duration = info["duration"]

        video_bitrate = calculate_video_bitrate(target_mb, duration)
        params = select_encoding_params(video_bitrate, min_crf, output_format)

        output_filename = os.path.splitext(video_file.filename)[0] + f"_compressed.{output_format}"
        output_path = os.path.join(tmp_dir, output_filename)

        encode_video(input_path, output_path, params, output_format)

        warning = params.get("warning", "")
        headers = {}
        if warning:
            headers["X-Warning"] = warning

        response = send_file(
            output_path,
            as_attachment=True,
            download_name=output_filename,
        )
        for k, v in headers.items():
            response.headers[k] = v
        return response

    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500
    finally:
        # cleanup runs after response is sent for temp files
        import shutil
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass


if __name__ == "__main__":
    app.run(debug=True, port=5000)
```

- [ ] **Step 4: Run all tests**

Run: `pytest test_app.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app.py
git commit -m "feat: add Flask routes and embedded HTML template"
```

---

### Task 6: Manual Verification

**Files:** None (verification only)

- [ ] **Step 1: Start the server**

Run: `python app.py`
Expected: `Running on http://127.0.0.1:5000`

- [ ] **Step 2: Open browser and test the happy path**

Navigate to `http://localhost:5000`.
- Select any video file from your disk
- Set target MB (e.g., half the original size)
- Leave CRF at 23
- Select MP4
- Click "Sıkıştır ve İndir"
Expected: File download starts after processing.

- [ ] **Step 3: Test the quality floor**

- Set target MB to a very small value (e.g., 1 MB for a long video)
- Set CRF to 18 (high quality floor)
- Submit
Expected: Warning message shows "kalite sınırı devreye girdi", file downloads at CRF quality (larger than 1 MB).

- [ ] **Step 4: Test error case — missing file**

Submit the form without selecting a video (via DevTools to bypass HTML validation).
Expected: Error message in the page.

- [ ] **Step 5: Final commit**

```bash
git add .
git commit -m "feat: video compressor complete"
```
