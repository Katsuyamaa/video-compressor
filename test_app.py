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


def test_get_video_info_raises_when_ffprobe_not_found():
    with patch("subprocess.run", side_effect=FileNotFoundError()):
        try:
            get_video_info("fake.mp4")
            assert False, "expected RuntimeError"
        except RuntimeError as e:
            assert "ffprobe" in str(e).lower()


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
