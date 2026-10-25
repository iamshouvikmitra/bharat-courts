#!/usr/bin/env python3
"""Render a live-E2E summary JSON (written by tests/integration/_common.py) as Markdown.

Used twice by the monitor workflow: once for the job's step summary and once
for the body of the per-backend tracking issue, so both show the same
per-check table rather than a raw log tail.

Usage::

    python .github/scripts/render_e2e_summary.py e2e-logs/hcservices.json [--title] > out.md
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ICON = {"PASS": "✅", "FAIL": "❌", "SKIP": "⏭️"}


def render(summary: dict, *, title: bool) -> str:
    out: list[str] = []
    if title:
        out.append(f"### {summary.get('title', summary.get('backend', 'live E2E'))}")
        out.append("")
    verdict = (
        f"**{summary['passed']}/{summary['total']} passed**"
        + (f", {summary['skipped']} skipped (portal-side)" if summary.get("skipped") else "")
        + (f", **{summary['failed']} failed**" if summary.get("failed") else "")
    )
    out.append(
        f"{verdict} · v{summary.get('version', '?')} · seed `{summary.get('seed', '?')}` · "
        f"egress: `{summary.get('proxy') or 'direct'}` · {summary.get('elapsed', 0)}s"
    )
    out.append("")
    out.append("| | Check | Covers | Time | Notes |")
    out.append("|---|---|---|---|---|")
    for c in summary.get("checks", []):
        status = c.get("status") or ("PASS" if c.get("passed") else "FAIL")
        covers = ", ".join(f"`{x}`" for x in c.get("covers", [])[:3])
        note = c.get("error") or ""
        if not note:
            # Surface the most informative detail for a passing check.
            details = c.get("details") or {}
            for key in ("court", "chosen", "phrase", "first", "found", "hits", "items", "note"):
                if key in details:
                    note = f"{key}: {details[key]}"
                    break
        note = str(note).replace("|", "\\|").replace("\n", " ")
        if len(note) > 140:
            note = note[:137] + "…"
        icon = ICON.get(status, "?")
        out.append(f"| {icon} | {c['name']} | {covers} | {c.get('elapsed', 0)}s | {note} |")
    failed = [c for c in summary.get("checks", []) if (c.get("status") or "FAIL") == "FAIL"]
    if failed:
        out.append("")
        out.append("<details><summary>Failure details</summary>")
        out.append("")
        for c in failed:
            out.append(f"**{c['name']}** — {c.get('error', '')}")
            for k, v in (c.get("details") or {}).items():
                out.append(f"- `{k}`: {str(v)[:300]}")
            out.append("")
        out.append("</details>")
    return "\n".join(out) + "\n"


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__, file=sys.stderr)
        return 2
    path = Path(args[0])
    if not path.exists():
        print(
            f"_No summary JSON at `{path}` — the script did not get far enough to write one "
            f"(install failure, hung portal hit the timeout, or crashed before the first check)._"
        )
        return 0
    summary = json.loads(path.read_text())
    sys.stdout.write(render(summary, title="--title" in sys.argv))
    return 0


if __name__ == "__main__":
    sys.exit(main())
