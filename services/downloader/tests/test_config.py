import pytest

from app.config import Settings, SettingsError, load_settings


def test_defaults_are_conservative_for_a_personal_machine():
    s = load_settings({})
    assert s == Settings()
    assert (s.max_concurrent, s.max_queue) == (2, 10)
    assert s.max_filesize_bytes == 2048 * 1024 * 1024
    assert s.min_free_disk_bytes == 1024 * 1024 * 1024


def test_environment_overrides_each_limit():
    s = load_settings(
        {
            "SIFON_MAX_CONCURRENT": "1",
            "SIFON_MAX_QUEUE": "3",
            "SIFON_MAX_FILESIZE_MB": "500",
            "SIFON_MAX_DURATION_MIN": "20",
            "SIFON_MIN_FREE_DISK_MB": "100",
            "SIFON_TTL_MINUTES": "5",
        }
    )
    assert (s.max_concurrent, s.max_queue, s.max_filesize_mb) == (1, 3, 500)
    assert (s.max_duration_min, s.min_free_disk_mb, s.ttl_minutes) == (20, 100, 5)


def test_blank_values_use_the_default():
    assert load_settings({"SIFON_MAX_QUEUE": "  "}) == Settings()


@pytest.mark.parametrize("value", ["abc", "1.5", "0", "-2"])
def test_bad_values_fail_loudly_naming_the_variable(value):
    with pytest.raises(SettingsError, match="SIFON_MAX_FILESIZE_MB"):
        load_settings({"SIFON_MAX_FILESIZE_MB": value})


def test_queue_smaller_than_concurrency_is_rejected():
    with pytest.raises(SettingsError, match="SIFON_MAX_QUEUE"):
        load_settings({"SIFON_MAX_CONCURRENT": "4", "SIFON_MAX_QUEUE": "2"})
