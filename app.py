import io
import json
import os
import re
import shutil
import subprocess
import tempfile

from flask import Flask, render_template_string, request, send_file, jsonify
from werkzeug.utils import secure_filename

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


ALLOWED_FORMATS = {"mp4", "mkv", "webm"}


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


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="tr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Video İşleyici</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    background: #f1f5f9;
    min-height: 100vh;
    padding: 40px 16px 60px;
    color: #0f172a;
  }
  .card {
    background: #fff;
    border-radius: 16px;
    box-shadow: 0 1px 3px rgba(0,0,0,.08), 0 8px 24px rgba(0,0,0,.06);
    max-width: 600px;
    margin: 0 auto;
    overflow: hidden;
  }
  .card-header {
    padding: 28px 32px 24px;
    border-bottom: 1px solid #f1f5f9;
  }
  h1 {
    font-size: 1.35rem;
    font-weight: 700;
    letter-spacing: -0.02em;
    color: #0f172a;
  }
  h1 span { color: #3b82f6; }
  .card-body { padding: 24px 32px 32px; }

  .section {
    background: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 18px 20px;
    margin-bottom: 12px;
  }
  .section-label {
    font-size: 0.7rem;
    font-weight: 700;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: #94a3b8;
    margin-bottom: 14px;
  }
  .group { margin-bottom: 14px; }
  .group:last-child { margin-bottom: 0; }
  .row { display: flex; gap: 12px; }
  .row .group { flex: 1; }

  label {
    display: block;
    font-size: 0.8rem;
    font-weight: 600;
    color: #475569;
    margin-bottom: 6px;
  }
  label .val {
    font-weight: 700;
    color: #3b82f6;
  }

  input[type=file] {
    width: 100%;
    padding: 10px 14px;
    border: 1.5px dashed #cbd5e1;
    border-radius: 10px;
    font-size: 0.875rem;
    background: #fff;
    color: #475569;
    cursor: pointer;
    transition: border-color 0.15s;
  }
  input[type=file]:hover { border-color: #3b82f6; }

  input[type=number], select {
    width: 100%;
    padding: 9px 12px;
    border: 1.5px solid #e2e8f0;
    border-radius: 8px;
    font-size: 0.875rem;
    background: #fff;
    color: #0f172a;
    transition: border-color 0.15s, box-shadow 0.15s;
    appearance: none;
  }
  select {
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 12 12'%3E%3Cpath fill='%2394a3b8' d='M6 8L1 3h10z'/%3E%3C/svg%3E");
    background-repeat: no-repeat;
    background-position: right 12px center;
    padding-right: 32px;
  }
  input[type=number]:focus, select:focus {
    outline: none;
    border-color: #3b82f6;
    box-shadow: 0 0 0 3px rgba(59,130,246,.12);
  }

  input[type=range] { width: 100%; accent-color: #3b82f6; cursor: pointer; }
  .scale-labels {
    display: flex;
    justify-content: space-between;
    font-size: 0.68rem;
    color: #94a3b8;
    margin-top: 4px;
  }

  .check-row {
    display: flex;
    align-items: center;
    gap: 10px;
    padding: 10px 14px;
    background: #fff;
    border: 1.5px solid #e2e8f0;
    border-radius: 8px;
    cursor: pointer;
    transition: border-color 0.15s;
  }
  .check-row:hover { border-color: #3b82f6; }
  input[type=checkbox] {
    width: 16px; height: 16px;
    accent-color: #3b82f6;
    cursor: pointer;
    flex-shrink: 0;
  }
  .check-row span { font-size: 0.875rem; font-weight: 500; color: #374151; }

  #preview {
    display: none;
    width: 100%;
    border-radius: 10px;
    margin-top: 12px;
    max-height: 280px;
    background: #0f172a;
  }
  #trimCanvas {
    display: none;
    width: 100%;
    height: 64px;
    border-radius: 8px;
    margin-top: 12px;
    cursor: col-resize;
    user-select: none;
    box-shadow: 0 1px 4px rgba(0,0,0,.12);
  }
  #trimInfo {
    display: none;
    font-size: 0.75rem;
    color: #64748b;
    margin-top: 8px;
    text-align: center;
    font-variant-numeric: tabular-nums;
    letter-spacing: 0.01em;
  }

  .dimmed { opacity: 0.35; pointer-events: none; transition: opacity 0.2s; }

  .submit-wrap { margin-top: 20px; }
  button[type=submit] {
    width: 100%;
    padding: 14px;
    background: #3b82f6;
    color: #fff;
    border: none;
    border-radius: 10px;
    font-size: 0.95rem;
    font-weight: 700;
    cursor: pointer;
    letter-spacing: -0.01em;
    transition: background 0.15s, transform 0.1s, box-shadow 0.15s;
    box-shadow: 0 2px 8px rgba(59,130,246,.35);
  }
  button[type=submit]:hover:not(:disabled) {
    background: #2563eb;
    box-shadow: 0 4px 16px rgba(59,130,246,.4);
    transform: translateY(-1px);
  }
  button[type=submit]:active:not(:disabled) { transform: translateY(0); }
  button[type=submit]:disabled { background: #bfdbfe; box-shadow: none; cursor: not-allowed; }

  .status {
    text-align: center;
    margin-top: 14px;
    font-size: 0.875rem;
    color: #64748b;
    display: none;
    animation: pulse 1.5s ease-in-out infinite;
  }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:.5} }

  .warning {
    background: #fffbeb;
    border: 1px solid #fcd34d;
    border-radius: 10px;
    padding: 14px 16px;
    margin-top: 14px;
    font-size: 0.85rem;
    color: #92400e;
  }
  .error-box {
    background: #fef2f2;
    border: 1px solid #fca5a5;
    border-radius: 10px;
    padding: 14px 16px;
    margin-top: 14px;
    font-size: 0.85rem;
    color: #991b1b;
  }
</style>
</head>
<body>
<div class="card">
  <div class="card-header">
    <h1>Video <span>İşleyici</span></h1>
  </div>
  <div class="card-body">
  <form id="form">

    <div class="section">
      <div class="section-label">Dosya</div>
      <div class="group">
        <input type="file" id="videoFile" accept="video/*" required>
      </div>
      <video id="preview" controls></video>
    </div>

    <div class="section">
      <div class="section-label">Kırpma</div>
      <canvas id="trimCanvas"></canvas>
      <div id="trimInfo">Başlangıç: 0:00 | Bitiş: 0:00 | Seçili: 0:00</div>
      <input type="hidden" id="start_time" name="start_time" value="">
      <input type="hidden" id="end_time" name="end_time" value="">
    </div>

    <div class="section">
      <div class="section-label">Görüntü</div>
      <div class="group">
        <label>Çözünürlük</label>
        <select id="resolution" name="resolution">
          <option value="original">Orijinal</option>
          <option value="1080p">1080p</option>
          <option value="720p">720p</option>
          <option value="480p">480p</option>
          <option value="360p">360p</option>
        </select>
      </div>
    </div>

    <div class="section">
      <div class="section-label">Ses</div>
      <div class="group">
        <label class="check-row" for="mute">
          <input type="checkbox" id="mute" onchange="toggleVol(this.checked)">
          <span>Sesi kapat (mute)</span>
        </label>
      </div>
      <div class="group" id="volGroup">
        <label>Ses Seviyesi — <span class="val"><span id="volVal">100</span>%</span></label>
        <input type="range" id="volume" min="0" max="200" value="100"
               oninput="document.getElementById('volVal').textContent=this.value">
        <div class="scale-labels"><span>0%</span><span>Orijinal</span><span>200%</span></div>
      </div>
    </div>

    <div class="section">
      <div class="section-label">Sıkıştırma</div>
      <div class="row">
        <div class="group">
          <label>Hedef Boyut (MB)</label>
          <input type="number" id="target_mb" name="target_mb" min="1" step="0.1" value="50" required>
        </div>
        <div class="group">
          <label>Çıktı Formatı</label>
          <select id="output_format" name="output_format">
            <option value="mp4">MP4</option>
            <option value="mkv">MKV</option>
            <option value="webm">WebM</option>
          </select>
        </div>
      </div>
      <div class="group">
        <label>Minimum Kalite — CRF: <span class="val"><span id="crfVal">23</span></span></label>
        <input type="range" id="min_crf" name="min_crf" min="0" max="51" value="23"
               oninput="document.getElementById('crfVal').textContent=this.value">
        <div class="scale-labels"><span>En iyi kalite (0)</span><span>En küçük dosya (51)</span></div>
      </div>
    </div>

    <div class="submit-wrap">
      <button type="submit" id="btn">İşle ve İndir</button>
    </div>

  </form>
  <p class="status" id="status">İşleniyor, lütfen bekleyin…</p>
  <div id="msg"></div>
  </div>
</div>

<script>
// ── State ──────────────────────────────────────────────────────────────────
let startPct = 0;
let endPct = 1;
let dragging = null;
let thumbImgData = null;
let prevObjectURL = null;
let prevMetaListener = null;

const THUMB_COUNT = 20;
const HANDLE_R = 10;
const MIN_GAP = 0.02;

// ── Elements ───────────────────────────────────────────────────────────────
const videoEl = document.getElementById('preview');
const canvas = document.getElementById('trimCanvas');
const ctx = canvas.getContext('2d');
const trimInfo = document.getElementById('trimInfo');

// ── Time helpers ───────────────────────────────────────────────────────────
function fmtTime(s) {
  const m = Math.floor(s / 60);
  const sec = Math.floor(s % 60);
  return m + ':' + String(sec).padStart(2, '0');
}

function secsToHHMMSS(s) {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  return String(h).padStart(2,'0') + ':' + String(m).padStart(2,'0') + ':' + String(sec).padStart(2,'0');
}

// ── UI updates ─────────────────────────────────────────────────────────────
function updateInfoBar() {
  const dur = videoEl.duration || 0;
  const s = startPct * dur;
  const e = endPct * dur;
  trimInfo.textContent = 'Başlangıç: ' + fmtTime(s) + ' | Bitiş: ' + fmtTime(e) + ' | Seçili: ' + fmtTime(e - s);
}

function updateHiddenInputs() {
  const dur = videoEl.duration || 0;
  document.getElementById('start_time').value = startPct <= 0.001 ? '' : secsToHHMMSS(startPct * dur);
  document.getElementById('end_time').value   = endPct   >= 0.999 ? '' : secsToHHMMSS(endPct * dur);
}

// ── Canvas drawing ─────────────────────────────────────────────────────────
function drawHandles() {
  const cw = canvas.width;
  const ch = canvas.height;
  const sx = Math.round(startPct * cw);
  const ex = Math.round(endPct * cw);

  if (thumbImgData) ctx.putImageData(thumbImgData, 0, 0);

  ctx.fillStyle = 'rgba(0,0,0,0.55)';
  ctx.fillRect(0, 0, sx, ch);
  ctx.fillRect(ex, 0, cw - ex, ch);

  ctx.strokeStyle = '#2563eb';
  ctx.lineWidth = 2;
  ctx.strokeRect(sx + 1, 1, ex - sx - 2, ch - 2);

  ctx.fillStyle = '#2563eb';
  ctx.fillRect(sx - 3, 0, 6, ch);
  ctx.beginPath(); ctx.arc(sx, ch / 2, HANDLE_R, 0, Math.PI * 2); ctx.fill();
  ctx.fillRect(ex - 3, 0, 6, ch);
  ctx.beginPath(); ctx.arc(ex, ch / 2, HANDLE_R, 0, Math.PI * 2); ctx.fill();
}

// ── Thumbnail generation ───────────────────────────────────────────────────
function generateThumbnails() {
  const cw = canvas.width;
  const ch = canvas.height;
  const dur = videoEl.duration;
  if (!isFinite(dur) || dur <= 0) {
    drawHandles();
    updateInfoBar();
    updateHiddenInputs();
    return;
  }
  const fw = cw / THUMB_COUNT;
  let i = 0;
  thumbImgData = null;
  ctx.clearRect(0, 0, cw, ch);

  function next() {
    if (i >= THUMB_COUNT) {
      thumbImgData = ctx.getImageData(0, 0, cw, ch);
      drawHandles();
      updateInfoBar();
      updateHiddenInputs();
      return;
    }
    function onSeeked() {
      videoEl.removeEventListener('seeked', onSeeked);
      ctx.drawImage(videoEl, Math.round(i * fw), 0, Math.ceil(fw), ch);
      i++;
      next();
    }
    videoEl.addEventListener('seeked', onSeeked);
    videoEl.currentTime = (i + 0.5) * dur / THUMB_COUNT;
  }
  next();
}

// ── File input ─────────────────────────────────────────────────────────────
document.getElementById('videoFile').addEventListener('change', function() {
  const file = this.files[0];
  if (!file) return;
  if (prevObjectURL) URL.revokeObjectURL(prevObjectURL);
  prevObjectURL = URL.createObjectURL(file);

  startPct = 0; endPct = 1; dragging = null; thumbImgData = null;

  videoEl.src = prevObjectURL;
  videoEl.style.display = 'block';

  if (prevMetaListener) videoEl.removeEventListener('loadedmetadata', prevMetaListener);
  prevMetaListener = function() {
    prevMetaListener = null;
    canvas.style.display = 'block';
    trimInfo.style.display = 'block';
    canvas.width = Math.round(canvas.getBoundingClientRect().width);
    canvas.height = Math.round(canvas.getBoundingClientRect().height);
    generateThumbnails();
  };
  videoEl.addEventListener('loadedmetadata', prevMetaListener, { once: true });
});

// ── Drag ───────────────────────────────────────────────────────────────────
function canvasX(e) {
  const r = canvas.getBoundingClientRect();
  return (e.clientX - r.left) * (canvas.width / r.width);
}

canvas.addEventListener('mousedown', function(e) {
  const x = canvasX(e);
  const sx = startPct * canvas.width;
  const ex = endPct * canvas.width;
  if (Math.abs(x - sx) <= HANDLE_R * 2) dragging = 'left';
  else if (Math.abs(x - ex) <= HANDLE_R * 2) dragging = 'right';
});

canvas.addEventListener('mousemove', function(e) {
  if (!dragging) return;
  const pct = Math.max(0, Math.min(1, canvasX(e) / canvas.width));
  if (dragging === 'left') startPct = Math.min(pct, endPct - MIN_GAP);
  else endPct = Math.max(pct, startPct + MIN_GAP);
  videoEl.currentTime = (dragging === 'left' ? startPct : endPct) * videoEl.duration;
  drawHandles();
  updateInfoBar();
  updateHiddenInputs();
});

document.addEventListener('mouseup', function() { dragging = null; });

// ── Volume toggle ──────────────────────────────────────────────────────────
function toggleVol(muted) {
  document.getElementById('volGroup').classList.toggle('dimmed', muted);
}

// ── Form submit ────────────────────────────────────────────────────────────
document.getElementById('form').onsubmit = async function(e) {
  e.preventDefault();
  const btn = document.getElementById('btn');
  const status = document.getElementById('status');
  const msg = document.getElementById('msg');
  msg.innerHTML = '';
  btn.disabled = true;
  status.style.display = 'block';

  const fd = new FormData();
  fd.append('video',         document.getElementById('videoFile').files[0]);
  fd.append('start_time',    document.getElementById('start_time').value);
  fd.append('end_time',      document.getElementById('end_time').value);
  fd.append('resolution',    document.getElementById('resolution').value);
  if (document.getElementById('mute').checked) fd.append('mute', 'on');
  fd.append('volume',        document.getElementById('volume').value);
  fd.append('target_mb',     document.getElementById('target_mb').value);
  fd.append('min_crf',       document.getElementById('min_crf').value);
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


@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)


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


if __name__ == "__main__":
    app.run(debug=True, port=5000)
