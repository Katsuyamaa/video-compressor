import json
import os
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

    if target_mb <= 0:
        return jsonify({"error": "Hedef boyut 0'dan büyük olmalı"}), 400
    if not 0 <= min_crf <= 51:
        return jsonify({"error": "CRF değeri 0-51 arasında olmalı"}), 400

    video_file = request.files["video"]
    safe_name = secure_filename(video_file.filename) or "input.mp4"
    tmp_dir = tempfile.mkdtemp()

    try:
        input_path = os.path.join(tmp_dir, "input_" + safe_name)
        video_file.save(input_path)

        info = get_video_info(input_path)
        duration = info["duration"]

        video_bitrate = calculate_video_bitrate(target_mb, duration)
        params = select_encoding_params(video_bitrate, min_crf, output_format)

        stem = os.path.splitext(safe_name)[0]
        output_filename = f"{stem}_compressed.{output_format}"
        output_path = os.path.join(tmp_dir, output_filename)

        encode_video(input_path, output_path, params, output_format)

        with open(output_path, "rb") as f:
            file_bytes = f.read()

        warning = params.get("warning", "")
        response = send_file(
            __import__("io").BytesIO(file_bytes),
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
