import subprocess

import pytest

from app.errors import DownloadFailure, ErrorCode
from evals.scoring import (
    FAIL,
    KNOWN_DEAD,
    KNOWN_DEAD_CASES,
    NETWORK,
    PASS,
    VERDICT_FAIL,
    VERDICT_INCONCLUSIVE,
    VERDICT_PASS,
    classify_exception,
    finalize_kind,
    run_with_retry,
    should_retry,
    summarize,
)


def results_of(**counts):
    """results_of(pass_=8, fail=2) -> list of {"kind": ...} dicts."""
    out = []
    for kind, n in counts.items():
        out += [{"kind": kind.rstrip("_"), "promote": False} for _ in range(n)]
    return out


# classification


ENVIRONMENT_CODES = (ErrorCode.NETWORK, ErrorCode.LOGIN_REQUIRED)


@pytest.mark.parametrize("code", ENVIRONMENT_CODES)
def test_environment_download_failures_are_network(code):
    # LOGIN_REQUIRED is YouTube's bot check on CI IPs (weekly run 2026-10-05: 4 of 9 active cases
    # were scored FAIL and the rate dropped to 56%).
    assert classify_exception(DownloadFailure(code)) == NETWORK


@pytest.mark.parametrize("code", [c for c in ErrorCode if c not in ENVIRONMENT_CODES])
def test_other_download_failures_are_product_failures(code):
    assert classify_exception(DownloadFailure(code)) == FAIL


def test_ci_run_of_2026_10_05_is_inconclusive_not_a_product_failure():
    # 4 YouTube cases blocked by the bot check, 5 passing: used to be FAIL at 56%.
    blocked = [classify_exception(DownloadFailure(ErrorCode.LOGIN_REQUIRED)) for _ in range(4)]
    s = summarize([{"kind": k, "promote": False} for k in blocked + [PASS] * 5])
    assert s.counts[FAIL] == 0
    assert s.verdict == VERDICT_INCONCLUSIVE


@pytest.mark.parametrize(
    "exc",
    [TimeoutError("slow"), subprocess.TimeoutExpired(cmd="ffprobe", timeout=1)],
)
def test_timeouts_are_network(exc):
    assert classify_exception(exc) == NETWORK


@pytest.mark.parametrize("exc", [RuntimeError("boom"), KeyError("x"), ValueError("bad"), subprocess.CalledProcessError(1, "ffprobe")])
def test_any_other_exception_is_a_product_failure(exc):
    assert classify_exception(exc) == FAIL


def test_known_dead_cases_are_the_two_vimeo_cases():
    assert {(url, mode) for url, mode in KNOWN_DEAD_CASES} == {
        ("https://vimeo.com/56015672", "video"),
        ("https://vimeo.com/56015672", "audio"),
    }


def test_known_dead_failure_is_known_dead_and_not_promoted():
    assert finalize_kind(FAIL, known_dead=True) == (KNOWN_DEAD, False)
    assert finalize_kind(NETWORK, known_dead=True) == (KNOWN_DEAD, False)


def test_known_dead_pass_raises_promote():
    assert finalize_kind(PASS, known_dead=True) == (KNOWN_DEAD, True)


@pytest.mark.parametrize("kind", [PASS, FAIL, NETWORK])
def test_active_case_keeps_its_kind(kind):
    assert finalize_kind(kind, known_dead=False) == (kind, False)


# retry


def test_should_retry_only_on_network():
    assert should_retry(NETWORK) is True
    assert should_retry(FAIL) is False
    assert should_retry(PASS) is False


def test_network_outcome_is_retried_exactly_once():
    calls = []

    def run():
        calls.append(1)
        return {"kind": NETWORK}

    assert run_with_retry(run)["kind"] == NETWORK
    assert len(calls) == 2


def test_network_then_pass_records_the_retry_result():
    outcomes = iter([{"kind": NETWORK}, {"kind": PASS}])
    assert run_with_retry(lambda: next(outcomes))["kind"] == PASS


def test_fail_is_not_retried():
    calls = []

    def run():
        calls.append(1)
        return {"kind": FAIL}

    assert run_with_retry(run)["kind"] == FAIL
    assert len(calls) == 1


def test_pass_is_not_retried():
    calls = []

    def run():
        calls.append(1)
        return {"kind": PASS}

    run_with_retry(run)
    assert len(calls) == 1


# rate and verdict


def test_rate_excludes_network_and_known_dead():
    s = summarize(results_of(pass_=8, fail=1, network=1, known_dead=2))
    assert s.counts == {PASS: 8, FAIL: 1, NETWORK: 1, KNOWN_DEAD: 2}
    assert s.rate == pytest.approx(8 / 9)
    assert s.network_share == pytest.approx(1 / 10)
    assert s.verdict == VERDICT_PASS


def test_rate_exactly_point_eight_passes():
    s = summarize(results_of(pass_=8, fail=2))
    assert s.rate == 0.8
    assert s.verdict == VERDICT_PASS


def test_rate_below_threshold_fails():
    s = summarize(results_of(pass_=79, fail=21))
    assert s.rate == pytest.approx(0.79)
    assert s.verdict == VERDICT_FAIL


def test_network_share_above_25_percent_is_inconclusive():
    # 3 of 11 active = 27%, even though the rest is perfect.
    s = summarize(results_of(pass_=8, network=3))
    assert s.network_share > 0.25
    assert s.verdict == VERDICT_INCONCLUSIVE


def test_exactly_25_percent_network_is_not_inconclusive():
    s = summarize(results_of(pass_=9, network=3))
    assert s.network_share == 0.25
    assert s.verdict == VERDICT_PASS


def test_exactly_25_percent_network_still_judged_on_rate():
    s = summarize(results_of(pass_=3, fail=6, network=3))
    assert s.verdict == VERDICT_FAIL


def test_all_network_is_inconclusive_without_dividing_by_zero():
    s = summarize(results_of(network=9, known_dead=2))
    assert s.rate is None
    assert s.network_share == 1.0
    assert s.verdict == VERDICT_INCONCLUSIVE


def test_empty_list_is_inconclusive():
    s = summarize([])
    assert s.rate is None
    assert s.network_share == 0.0
    assert s.verdict == VERDICT_INCONCLUSIVE
    assert s.counts == {PASS: 0, FAIL: 0, NETWORK: 0, KNOWN_DEAD: 0}


def test_only_known_dead_is_inconclusive():
    assert summarize(results_of(known_dead=2)).verdict == VERDICT_INCONCLUSIVE


def test_promote_is_reported():
    results = results_of(pass_=9, fail=0) + [{"kind": KNOWN_DEAD, "promote": True, "site": "vimeo"}]
    s = summarize(results)
    assert len(s.promote) == 1
    assert s.verdict == VERDICT_PASS  # the rate is unaffected, the eval test fails on promote separately


def test_no_promote_by_default():
    assert summarize(results_of(pass_=1)).promote == []
