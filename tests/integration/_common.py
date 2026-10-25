"""Shared harness for the live integration scripts.

Every script under ``tests/integration/`` is a standalone checklist against a
real backend. This module holds the pieces they share so each script stays a
flat list of checks:

* :class:`Check` — one PASS/FAIL line with free-form details.
* :class:`Suite` — runs the checks, prints the report, writes a JSON summary
  (``E2E_SUMMARY_JSON`` or ``<results_dir>/test_summary.json``) that the CI
  monitor renders into the job summary and the tracking issue.
* :func:`rotate` — deterministic daily rotation over a pool (courts, states,
  phrases) so the monitor exercises a different slice of the portal each day
  and a single court going dark (Delhi stopped publishing cause lists on HC
  Services in Oct 2026) cannot fail the whole backend.
* :func:`first_working` — try candidates in rotation order until one yields
  data, recording what each returned. A check passes if *any* candidate
  works; the per-candidate detail shows which ones didn't.

Rotation is seeded from ``E2E_SEED`` when set, else from today's date, so a
failing run is reproducible with ``E2E_SEED=<n> python tests/integration/x.py``.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import traceback
from collections.abc import Awaitable, Callable, Iterable, Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import urlsplit, urlunsplit

T = TypeVar("T")
C = TypeVar("C")


# ---------------------------------------------------------------------------
# rotation
# ---------------------------------------------------------------------------


def seed() -> int:
    """Rotation seed: ``E2E_SEED`` if set, else today's ordinal day."""
    raw = os.environ.get("E2E_SEED")
    if raw:
        try:
            return int(raw)
        except ValueError:
            pass
    return date.today().toordinal()


def rotate(pool: Sequence[T], n: int | None = None) -> list[T]:
    """Return ``pool`` rotated by today's seed, optionally truncated to ``n``.

    Day 1 starts at pool[0], day 2 at pool[1], … so over ``len(pool)`` days
    every entry has been first once. The full pool is still available after
    the starting point, so a check can fall through to the next court.
    """
    items = list(pool)
    if not items:
        return []
    start = seed() % len(items)
    rotated = items[start:] + items[:start]
    return rotated[:n] if n else rotated


def working_day_candidates(*, back: int = 1, forward: int = 1) -> list[date]:
    """Dates worth asking for a cause list on.

    No list is published for a Sunday (or most Saturdays / holidays), so a
    bare "today" query legitimately returns 0 rows — exactly how a broken
    parser also looks. Ask for today, the next ``forward`` working days
    (boards are published a day or two ahead) and the previous ``back``
    working days (past lists stay available).
    """
    today = date.today()
    out = [today]
    step = today
    found = 0
    while found < forward:
        step += timedelta(days=1)
        if step.weekday() < 5:
            out.append(step)
            found += 1
    step = today
    found = 0
    while found < back:
        step -= timedelta(days=1)
        if step.weekday() < 5:
            out.append(step)
            found += 1
    return out


def ddmmyyyy(d: date) -> str:
    return d.strftime("%d-%m-%Y")


# ---------------------------------------------------------------------------
# check + suite
# ---------------------------------------------------------------------------


class Check:
    """One line of the report.

    A check ends in one of three states: PASS, FAIL, or SKIP. SKIP means the
    *portal* could not answer (its own "connection to server failed" page,
    an outage banner) so the SDK could not be judged either way — the request
    was well-formed and the SDK classified the response correctly, which is
    all we can verify. Skips never fail the backend but are listed in the
    report so a portal that is down for a week is still visible.
    """

    def __init__(self, name: str, *, covers: Iterable[str] = ()):
        self.name = name
        self.covers = list(covers)  # SDK symbols this check exercises
        self.passed = False
        self.skipped = False
        self.error = ""
        self.details: dict[str, Any] = {}
        self.errors: list[BaseException] = []  # exceptions seen by first_working
        self.elapsed = 0.0

    def fail(self, msg: str) -> None:
        self.passed = False
        self.error = msg

    def skip(self, reason: str) -> None:
        """Portal-side failure: not a pass, not an SDK failure."""
        self.passed = True
        self.skipped = True
        self.error = reason

    def skip_if_portal_outage(self, what: str) -> bool:
        """Skip when every recorded attempt failed with a portal outage page."""
        if self.errors and all(is_portal_outage(e) for e in self.errors):
            self.skip(f"portal-side outage on {what}: {str(self.errors[-1])[:100]}")
            return True
        return False

    @property
    def status(self) -> str:
        if self.skipped:
            return "SKIP"
        return "PASS" if self.passed else "FAIL"

    def __str__(self) -> str:
        s = f"[{self.status}] {self.name}  ({self.elapsed:.1f}s)"
        if self.error:
            s += f"\n       {'REASON' if self.skipped else 'ERROR'}: {self.error}"
        for k, v in self.details.items():
            s += f"\n       {k}: {v}"
        return s

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "covers": self.covers,
            "status": self.status,
            "passed": self.passed,
            "skipped": self.skipped,
            "error": self.error,
            "elapsed": round(self.elapsed, 2),
            "details": {k: _jsonable(v) for k, v in self.details.items()},
        }


# Phrases the eCourts portals emit when *their* backend is down. The SDK maps
# them to its own error types, so matching the text is the only portable test.
PORTAL_OUTAGE_PHRASES = (
    "connection to server failed",
    "try after some time",
    "unable to connect to server",
    "service unavailable",
    "temporarily unavailable",
)


def is_portal_outage(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(phrase in text for phrase in PORTAL_OUTAGE_PHRASES)


def _jsonable(v: Any) -> Any:
    if isinstance(v, (str, int, float, bool)) or v is None:
        return v
    if isinstance(v, dict):
        return {str(k): _jsonable(x) for k, x in list(v.items())[:20]}
    if isinstance(v, (list, tuple, set)):
        return [_jsonable(x) for x in list(v)[:20]]
    return str(v)


CheckFn = Callable[[Check], Awaitable[None] | None]


class Suite:
    """Runs a list of ``(name, covers, fn)`` checks and reports."""

    def __init__(self, title: str, *, results_dir: Path | str, backend: str):
        self.title = title
        self.backend = backend
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.checks: list[Check] = []
        self._fns: list[tuple[Check, CheckFn]] = []

    # -- registration ------------------------------------------------------

    def check(self, name: str, *covers: str) -> Callable[[CheckFn], CheckFn]:
        """Decorator: register ``fn(check)`` as a check."""

        def deco(fn: CheckFn) -> CheckFn:
            self._fns.append((Check(name, covers=covers), fn))
            return fn

        return deco

    # -- helpers -----------------------------------------------------------

    def save_json(self, name: str, data: Any) -> Path:
        path = self.results_dir / f"{name}.json"
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str))
        return path

    # -- run ---------------------------------------------------------------

    async def run(self) -> bool:
        version = _sdk_version()
        print("=" * 70)
        print(f"  bharat-courts — {self.title}")
        print(f"  Version: {version}   Date: {date.today().isoformat()}   Seed: {seed()}")
        print(f"  Proxy:   {proxy_in_use() or 'none (direct)'}")
        print(f"  Results: {self.results_dir}")
        print("=" * 70)
        print()

        total = len(self._fns)
        for i, (check, fn) in enumerate(self._fns, 1):
            print(f"[{i}/{total}] {check.name}...")
            t0 = time.time()
            try:
                result = fn(check)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as e:  # noqa: BLE001 — any error is a failed check
                check.passed = False
                check.error = f"{type(e).__name__}: {e}"
                traceback.print_exc()
            check.elapsed = time.time() - t0
            self.checks.append(check)
            print(f"  {check}")
            print()
            # Persist after every check: a script killed by CI's hard cap
            # still leaves a (partial) report behind.
            self._write_summary(version, total)

        summary = self._write_summary(version, total)
        print("=" * 70)
        line = f"  Results: {summary['passed']}/{total} passed"
        if summary["skipped"]:
            line += f", {summary['skipped']} skipped (portal-side)"
        if summary["failed"]:
            line += f", {summary['failed']} FAILED"
        print(f"{line}  ({summary['elapsed']:.1f}s total)")
        print("=" * 70)
        return summary["failed"] == 0

    def _write_summary(self, version: str, total: int) -> dict[str, Any]:
        passed = sum(1 for c in self.checks if c.passed and not c.skipped)
        skipped = sum(1 for c in self.checks if c.skipped)
        failed = len(self.checks) - passed - skipped
        elapsed = sum(c.elapsed for c in self.checks)
        summary = {
            "backend": self.backend,
            "title": self.title,
            "version": version,
            "date": date.today().isoformat(),
            "seed": seed(),
            "proxy": proxy_in_use(),
            "passed": passed,
            "skipped": skipped,
            "failed": failed,
            "total": total,
            "complete": len(self.checks) == total,
            "elapsed": round(elapsed, 1),
            "checks": [c.to_dict() for c in self.checks],
        }
        self.save_json("test_summary", summary)
        target = os.environ.get("E2E_SUMMARY_JSON")
        if target:
            Path(target).parent.mkdir(parents=True, exist_ok=True)
            Path(target).write_text(json.dumps(summary, indent=2, ensure_ascii=False))
        return summary

    def main(self) -> None:
        ok = asyncio.run(self.run())
        sys.exit(0 if ok else 1)


async def first_working(
    check: Check,
    candidates: Sequence[C],
    fn: Callable[[C], Awaitable[T]],
    *,
    label: str,
    key: Callable[[C], str] = str,
    accept: Callable[[T], bool] = bool,
    max_tries: int | None = None,
) -> tuple[C | None, T | None]:
    """Try ``fn`` on each candidate until one returns an accepted value.

    Each attempt is recorded in ``check.details`` under ``label[candidate]``
    as either a size / repr or the exception. Returns ``(candidate, value)``
    for the first accepted result, else ``(None, None)``.
    """
    tried = 0
    for cand in candidates:
        if max_tries is not None and tried >= max_tries:
            break
        tried += 1
        name = key(cand)
        try:
            value = await fn(cand)
        except Exception as e:  # noqa: BLE001 — recorded, next candidate
            check.errors.append(e)
            check.details[f"{label}[{name}]"] = f"ERROR {type(e).__name__}: {str(e)[:120]}"
            continue
        check.details[f"{label}[{name}]"] = _describe(value)
        if accept(value):
            return cand, value
    return None, None


def _describe(value: Any) -> str:
    if isinstance(value, (list, tuple, set, dict)):
        return f"{len(value)} item(s)"
    if isinstance(value, (bytes, bytearray)):
        return f"{len(value):,} bytes"
    if value is None:
        return "None"
    items = getattr(value, "items", None)
    if isinstance(items, list):  # SearchResult and friends
        total = getattr(value, "total_count", None)
        return f"{len(items)} item(s)" + (f" of {total:,}" if isinstance(total, int) else "")
    return str(value)[:100]


# ---------------------------------------------------------------------------
# environment
# ---------------------------------------------------------------------------


def proxy_in_use() -> str | None:
    """The proxy the SDK will use, with credentials masked, or ``None``."""
    raw = (
        os.environ.get("BHARAT_COURTS_PROXY")
        or os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("http_proxy")
    )
    return mask_proxy(raw) if raw else None


def mask_proxy(url: str) -> str:
    parts = urlsplit(url)
    if parts.username or parts.password:
        host = parts.hostname or ""
        if parts.port:
            host = f"{host}:{parts.port}"
        parts = parts._replace(netloc=f"***:***@{host}")
    return urlunsplit(parts)


def _sdk_version() -> str:
    try:
        from bharat_courts import __version__

        return __version__
    except Exception:  # noqa: BLE001
        return "unknown"


def require(module: str, extra: str) -> None:
    """Exit early with an install hint if an optional dependency is missing."""
    try:
        __import__(module)
    except ImportError:
        print(f"ERROR: {module} not installed. Run: pip install -e '.[{extra}]'", file=sys.stderr)
        sys.exit(1)
