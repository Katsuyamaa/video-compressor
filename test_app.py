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


from app import app as flask_app
import io


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
    params = {**BASE_PARAMS, "min_crf": 0}
    commands, _ = build_ffmpeg_args("in.mp4", "out.mp4", params, 60.0)
    assert len(commands) == 1
    assert "-crf" in commands[0]


def test_build_ffmpeg_args_bitrate_mode_returns_two_commands():
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
