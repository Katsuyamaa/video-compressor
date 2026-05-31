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
