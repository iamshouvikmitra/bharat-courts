#!/usr/bin/env python3
"""Find a working public Indian HTTP proxy for the live E2E monitor.

The eCourts portals time out from GitHub's runner IPs (all three hosts, since
2026-10-22) while answering fine from Indian addresses. When no paid proxy or
Tailscale exit node is configured, the monitor falls back to a free public
proxy so it can still tell us whether the SDK works.

Free proxies are unreliable — on 2026-10-25 only 2 of 68 listed Indian proxies
completed an HTTPS CONNECT to hcservices.ecourts.gov.in — so this script
probes every candidate against the real portal, in parallel, and prints the
fastest one that answered 200. Nothing is printed when none works; the caller
then runs direct and the failure is reported as "no Indian egress", not as an
SDK bug.

Only the Python standard library is used so this can run before the project
is installed.

Usage::

    proxy=$(python .github/scripts/find_india_proxy.py)
    [ -n "$proxy" ] && export HTTPS_PROXY="$proxy" HTTP_PROXY="$proxy"
"""

from __future__ import annotations

import concurrent.futures as cf
import json
import ssl
import sys
import time
import urllib.error
import urllib.request

SOURCES = [
    # ProxyScrape: plain "ip:port" lines, India, HTTP(S) proxies checked <5s.
    (
        "https://api.proxyscrape.com/v4/free-proxy-list/get"
        "?request=display_proxies&country=in&protocol=http"
        "&proxy_format=ipport&format=text&timeout=5000",
        "text",
    ),
    # Geonode: JSON list sorted by last check.
    (
        "https://proxylist.geonode.com/api/proxy-list"
        "?country=IN&protocols=http%2Chttps&limit=200&sort_by=lastChecked&sort_type=desc",
        "geonode",
    ),
]

# Probe against the portal the SDK actually needs, through an HTTPS CONNECT
# tunnel — a proxy that only forwards plain HTTP is useless to us.
PROBE_URL = "https://hcservices.ecourts.gov.in/hcservices/main.php"
PROBE_TIMEOUT = 15  # seconds per proxy
LIST_TIMEOUT = 20
MAX_WORKERS = 24
RECHECK_TOP = 8  # fastest responders re-verified sequentially before one is chosen
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def fetch_candidates() -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for url, kind in SOURCES:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=LIST_TIMEOUT) as resp:
                body = resp.read().decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001 — a dead list is not fatal
            log(f"list {url.split('/')[2]}: {type(e).__name__}: {e}")
            continue
        entries: list[str] = []
        if kind == "text":
            entries = [line.strip() for line in body.splitlines() if ":" in line]
        else:
            try:
                data = json.loads(body).get("data", [])
            except json.JSONDecodeError:
                data = []
            entries = [f"{p.get('ip')}:{p.get('port')}" for p in data if p.get("ip")]
        fresh = [e for e in entries if e not in seen]
        seen.update(fresh)
        out.extend(fresh)
        log(f"list {url.split('/')[2]}: {len(entries)} entries ({len(fresh)} new)")
    return out


def probe(hostport: str) -> tuple[str, float] | None:
    """Return (proxy_url, seconds) if the portal answered 200 through it."""
    proxy_url = f"http://{hostport}"
    ctx = ssl.create_default_context()
    ctx.check_hostname = False  # mirror the SDK, which disables verification
    ctx.verify_mode = ssl.CERT_NONE
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url}),
        urllib.request.HTTPSHandler(context=ctx),
    )
    req = urllib.request.Request(PROBE_URL, headers={"User-Agent": USER_AGENT})
    t0 = time.time()
    try:
        with opener.open(req, timeout=PROBE_TIMEOUT) as resp:
            if resp.status == 200 and len(resp.read(4096)) > 0:
                return proxy_url, time.time() - t0
    except Exception:  # noqa: BLE001 — dead proxy
        return None
    return None


def main() -> int:
    candidates = fetch_candidates()
    if not candidates:
        log("no proxy candidates from any list")
        return 0
    log(f"probing {len(candidates)} Indian proxies against {PROBE_URL} ...")
    working: list[tuple[str, float]] = []
    with cf.ThreadPoolExecutor(MAX_WORKERS) as ex:
        for result in ex.map(probe, candidates):
            if result:
                working.append(result)
                log(f"  OK {result[0]} ({result[1]:.1f}s)")
    if not working:
        log("no working Indian proxy found")
        return 0
    working.sort(key=lambda r: r[1])
    log(f"{len(working)}/{len(candidates)} answered once; re-verifying the fastest")
    # Free proxies die within minutes. Require a second, sequential success a
    # moment later before trusting one with a 10-minute run.
    for proxy_url, first_t in working[:RECHECK_TOP]:
        time.sleep(1)
        again = probe(proxy_url.removeprefix("http://"))
        if again:
            log(f"picked {proxy_url} ({first_t:.1f}s, {again[1]:.1f}s)")
            print(proxy_url)
            return 0
        log(f"  dropped {proxy_url}: failed re-check")
    log("every candidate failed its re-check")
    return 0


if __name__ == "__main__":
    sys.exit(main())
