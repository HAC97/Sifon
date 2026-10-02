import pytest

from app.errors import USER_MESSAGES, DownloadFailure, ErrorCode, map_error


@pytest.mark.parametrize(
    "message, expected",
    [
        ("ERROR: Unsupported URL: https://example.com/x", ErrorCode.UNSUPPORTED_SITE),
        ("ERROR: [youtube] abc: Sign in to confirm you're not a bot", ErrorCode.LOGIN_REQUIRED),
        ("ERROR: Private video. Sign in if you've been granted access", ErrorCode.LOGIN_REQUIRED),
        ("ERROR: This video is not available in your country", ErrorCode.GEO_BLOCKED),
        ("ERROR: The uploader has blocked it in your country on copyright grounds", ErrorCode.GEO_BLOCKED),
        ("ERROR: Postprocessing: ffprobe and ffmpeg not found. Please install", ErrorCode.FFMPEG_MISSING),
        ("ERROR: You have requested merging of multiple formats but ffmpeg is not installed", ErrorCode.FFMPEG_MISSING),
        ("ERROR: Unable to download webpage: <urlopen error timed out>", ErrorCode.NETWORK),
        ("ERROR: [Errno 11001] getaddrinfo failed", ErrorCode.NETWORK),
        ("ERROR: [vimeo] 56015672: Unable to download webpage: HTTP Error 404: Not Found", ErrorCode.UNSUPPORTED_SITE),
        ("ERROR: Unable to download webpage: HTTP Error 410: Gone", ErrorCode.UNSUPPORTED_SITE),
        ("ERROR: Video unavailable", ErrorCode.UNSUPPORTED_SITE),
        ("ERROR: [youtube] abc: This video is unavailable", ErrorCode.UNSUPPORTED_SITE),
        ("ERROR: Unable to download webpage: HTTP Error 503: Service Unavailable", ErrorCode.NETWORK),
        ("ERROR: Unable to download webpage: HTTP Error 500: Internal Server Error", ErrorCode.NETWORK),
        ("ERROR: Unable to download webpage: <urlopen error timed out>", ErrorCode.NETWORK),
        ("ERROR: Unable to download webpage: something odd", ErrorCode.NETWORK),
        ("ERROR: <urlopen error [Errno -2] Name or service not known>", ErrorCode.NETWORK),
        ("ERROR: Temporary failure in name resolution", ErrorCode.NETWORK),
        # Login and geo messages keep their code even when they also look like a 404 or "unavailable".
        ("ERROR: Unable to download webpage: HTTP Error 404: Not Found. Sign in to continue", ErrorCode.LOGIN_REQUIRED),
        ("ERROR: Video unavailable. This video is not available in your country", ErrorCode.GEO_BLOCKED),
        ("ERROR: Unable to download webpage: HTTP Error 404: Not Found (geo restriction)", ErrorCode.GEO_BLOCKED),
        ("ERROR: Video unavailable. Private video. Sign in if you've been granted access", ErrorCode.LOGIN_REQUIRED),
        ("ERROR: something nobody has seen before", ErrorCode.UNKNOWN),
        ("", ErrorCode.UNKNOWN),
    ],
)
def test_map_error(message, expected):
    assert map_error(message) == expected


def test_ffmpeg_wins_over_generic_download_words():
    # "Unable to download" alone is NETWORK, but a missing ffmpeg must be reported as such.
    assert map_error("Unable to download: ffprobe and ffmpeg not found") == ErrorCode.FFMPEG_MISSING


def test_every_code_has_a_spanish_user_message():
    assert set(USER_MESSAGES) == set(ErrorCode)
    assert all(msg.strip() for msg in USER_MESSAGES.values())


def test_download_failure_defaults_to_user_message():
    failure = DownloadFailure(ErrorCode.GEO_BLOCKED)
    assert failure.code == ErrorCode.GEO_BLOCKED
    assert failure.message == USER_MESSAGES[ErrorCode.GEO_BLOCKED]


def test_download_failure_accepts_custom_message():
    assert DownloadFailure(ErrorCode.INVALID_URL, "custom").message == "custom"
