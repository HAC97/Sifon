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
