import pytest
from yt_dlp.utils import DownloadError

from app.errors import DownloadFailure, ErrorCode
from app.extractor import fetch_info, summarize_info

RAW = {
    "title": "Me at the zoo",
    "thumbnail": "https://img.example/t.jpg",
    "duration": 19,
    "uploader": "jawed",
    "formats": [
        {"format_id": "140", "height": None, "vcodec": "none"},
        {"format_id": "18", "height": 360, "vcodec": "avc1"},
        {"format_id": "22", "height": 720, "vcodec": "avc1"},
        {"format_id": "137", "height": 720, "vcodec": "avc1"},
        {"format_id": "x", "height": 1080, "vcodec": None},
    ],
}


def test_summarize_lists_unique_video_heights_descending():
    info = summarize_info(RAW)
    assert info == {
        "title": "Me at the zoo",
        "thumbnail": "https://img.example/t.jpg",
        "duration": 19,
        "uploader": "jawed",
        "heights": [1080, 720, 360],
    }


def test_summarize_fills_defaults_for_sparse_info():
    info = summarize_info({"formats": []})
    assert info["title"] == "video"
    assert info["heights"] == []
    assert info["thumbnail"] is None
    assert info["uploader"] is None


def test_summarize_uses_channel_when_uploader_missing():
    assert summarize_info({"title": "t", "channel": "chan"})["uploader"] == "chan"


def test_summarize_takes_first_entry_of_a_playlist():
    raw = {"_type": "playlist", "entries": [None, RAW, {"title": "second"}]}
    assert summarize_info(raw)["title"] == "Me at the zoo"


def test_summarize_empty_playlist_is_unknown_failure():
    with pytest.raises(DownloadFailure) as exc:
        summarize_info({"_type": "playlist", "entries": []})
    assert exc.value.code == ErrorCode.UNKNOWN


def fake_ydl(raw=None, error=None):
    class FakeYDL:
        opts = None

        def __init__(self, opts):
            FakeYDL.opts = opts

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def extract_info(self, url, download=False):
            if error is not None:
                raise error
            return raw

        def sanitize_info(self, info):
            return info

    return FakeYDL


def test_fetch_info_returns_summary_and_disables_playlists():
    cls = fake_ydl(raw=RAW)
    assert fetch_info("https://example.com/v", ytdlp_cls=cls)["title"] == "Me at the zoo"
    assert cls.opts["noplaylist"] is True
    assert cls.opts["playlist_items"] == "1"
    assert cls.opts["skip_download"] is True


def test_fetch_info_maps_download_errors():
    cls = fake_ydl(error=DownloadError("ERROR: Unsupported URL: x"))
    with pytest.raises(DownloadFailure) as exc:
        fetch_info("https://example.com/v", ytdlp_cls=cls)
    assert exc.value.code == ErrorCode.UNSUPPORTED_SITE


def test_fetch_info_none_result_is_unknown_failure():
    with pytest.raises(DownloadFailure) as exc:
        fetch_info("https://example.com/v", ytdlp_cls=fake_ydl(raw=None))
    assert exc.value.code == ErrorCode.UNKNOWN
