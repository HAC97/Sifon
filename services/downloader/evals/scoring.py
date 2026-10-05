"""Pure scoring for the real-site eval: no network, no pytest, tested from the gate lane.

A case ends as one of four kinds:
  pass        the downloaded file checks out
  fail        a product failure (bad file, non-NETWORK DownloadFailure, any other exception)
  network     a DownloadFailure(NETWORK or LOGIN_REQUIRED) or a timeout, after one retry; says nothing
              about the product (LOGIN_REQUIRED on a public URL is the site blocking this machine)
  known_dead  a case listed in KNOWN_DEAD_CASES; still run and printed, never counted

rate    = pass / (pass + fail) over active cases (network and known_dead excluded)
verdict = INCONCLUSIVE when network results exceed 25% of the active cases (or there is nothing
          to judge), otherwise PASS iff rate >= 0.8.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from typing import Callable

from app.errors import DownloadFailure, ErrorCode

PASS = "pass"
FAIL = "fail"
NETWORK = "network"
KNOWN_DEAD = "known_dead"
KINDS = (PASS, FAIL, NETWORK, KNOWN_DEAD)

VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"
VERDICT_INCONCLUSIVE = "INCONCLUSIVE"

THRESHOLD = 0.8
NETWORK_SHARE_LIMIT = 0.25

# https://vimeo.com/56015672 is a 404 today and every other Vimeo URL tried needed login
# (see URL_VERIFICATION.md). (url, mode) pairs.
DEAD_VIMEO_URL = "https://vimeo.com/56015672"
KNOWN_DEAD_CASES = frozenset({(DEAD_VIMEO_URL, "video"), (DEAD_VIMEO_URL, "audio")})


def classify_exception(exc: BaseException) -> str:
    """NETWORK for a NETWORK or LOGIN_REQUIRED DownloadFailure or a timeout, FAIL for everything else.

    The eval URLs are public, so LOGIN_REQUIRED on them is the site refusing this machine (YouTube's
    "confirm you're not a bot" on GitHub's datacenter IPs), not a product failure.
    """
    if isinstance(exc, DownloadFailure):
        return NETWORK if exc.code in (ErrorCode.NETWORK, ErrorCode.LOGIN_REQUIRED) else FAIL
    if isinstance(exc, (TimeoutError, subprocess.TimeoutExpired)):
        return NETWORK
    return FAIL


def should_retry(kind: str) -> bool:
    return kind == NETWORK


def run_with_retry(run_once: Callable[[], dict]) -> dict:
    """Run a case; a `network` outcome is retried once with the same inputs."""
    result = run_once()
    if should_retry(result["kind"]):
        result = run_once()
    return result


def finalize_kind(kind: str, known_dead: bool) -> tuple[str, bool]:
    """Returns (final kind, promote). A known-dead case never counts; if it passes, promote."""
    if known_dead:
        return KNOWN_DEAD, kind == PASS
    return kind, False


@dataclass
class Summary:
    counts: dict[str, int]
    rate: float | None
    network_share: float
    verdict: str
    promote: list[dict] = field(default_factory=list)


def summarize(results: list[dict]) -> Summary:
    counts = {kind: 0 for kind in KINDS}
    for r in results:
        counts[r["kind"]] += 1
    judged = counts[PASS] + counts[FAIL]
    active = judged + counts[NETWORK]
    rate = counts[PASS] / judged if judged else None
    network_share = counts[NETWORK] / active if active else 0.0
    if active == 0 or network_share > NETWORK_SHARE_LIMIT or rate is None:
        verdict = VERDICT_INCONCLUSIVE
    else:
        verdict = VERDICT_PASS if rate >= THRESHOLD else VERDICT_FAIL
    return Summary(
        counts=counts,
        rate=rate,
        network_share=network_share,
        verdict=verdict,
        promote=[r for r in results if r.get("promote")],
    )
