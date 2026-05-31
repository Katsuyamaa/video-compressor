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
