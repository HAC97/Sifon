import pytest

from app.formats import HEIGHTS, OUTTMPL, video_selector, ytdlp_options


def noop(_):
    pass


def test_best_selector_has_no_height_filter():
    assert video_selector("best") == "bv*+ba/b"


@pytest.mark.parametrize("height", HEIGHTS)
def test_height_selector_caps_resolution(height):
    assert video_selector(height) == f"bv*[height<={height}]+ba/b[height<={height}]"


@pytest.mark.parametrize("bad", ["999", "", "1080p", "-1", "best; rm"])
def test_invalid_height_rejected(bad):
    with pytest.raises(ValueError):
        video_selector(bad)


def test_video_options_merge_to_mp4_and_prefer_compatible_codecs():
    opts = ytdlp_options("video", "720", "mp3", "C:/t/%(title)s.%(ext)s", noop)
    assert opts["format"] == "bv*[height<=720]+ba/b[height<=720]"
    assert opts["merge_output_format"] == "mp4"
    assert opts["format_sort"] == ["res", "ext:mp4:m4a"]
    assert "postprocessors" not in opts


def test_mp3_audio_options_use_192k():
    opts = ytdlp_options("audio", "best", "mp3", "x", noop)
    assert opts["format"] == "bestaudio/best"
    assert opts["postprocessors"] == [
        {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
    ]


@pytest.mark.parametrize("fmt", ["m4a", "opus"])
def test_other_audio_formats_have_no_forced_bitrate(fmt):
    opts = ytdlp_options("audio", "best", fmt, "x", noop)
    assert opts["postprocessors"] == [{"key": "FFmpegExtractAudio", "preferredcodec": fmt}]


def test_playlists_are_limited_to_first_item():
    for mode in ("video", "audio"):
        opts = ytdlp_options(mode, "best", "mp3", "x", noop)
        assert opts["noplaylist"] is True
        assert opts["playlist_items"] == "1"


def test_hooks_and_outtmpl_are_wired():
    pp = lambda d: None  # noqa: E731
    opts = ytdlp_options("video", "best", "mp3", "OUT", noop, pp)
    assert opts["outtmpl"] == "OUT"
    assert opts["progress_hooks"] == [noop]
    assert opts["postprocessor_hooks"] == [pp]


def test_invalid_mode_and_audio_format_rejected():
    with pytest.raises(ValueError):
        ytdlp_options("gif", "best", "mp3", "x", noop)
    with pytest.raises(ValueError):
        ytdlp_options("audio", "best", "wav", "x", noop)


def test_outtmpl_truncates_title_and_includes_id():
    assert "%(title).120s" in OUTTMPL
    assert "[%(id)s]" in OUTTMPL
