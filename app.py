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
