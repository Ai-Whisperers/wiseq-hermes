"""Review researched OSS connectors for licence, maintenance and risk.

Why this exists
---------------
``data/oss/*.json`` holds 428 researched projects across 31 capability
lanes.  The integration agent ranks them, but a ranking is not a
decision.  Before any connector is installed it has to clear three
questions that the local data cannot answer:

  1. **Licence.**  A connector that ships copyleft, or no licence at
     all, cannot simply be dropped into a commercial system.  The
     repository files record neither licence nor maintenance.
  2. **Maintenance.**  A connector last touched years ago will not
     still speak a current API.
  3. **Risk.**  A connector that wants write access to orders or
     invoices needs an explicit, revocable approval -- and the risk
     rating must be visible to a human, not buried in a ranking score.

This script answers those questions from the public GitHub API and
writes a review table a human can act on.  It makes NO install
decision and changes nothing in the system: it produces evidence.

Read-only, public, no credentials needed for the public API.  A
``GITHUB_TOKEN`` is used when present, purely to raise the rate limit.

Run it::

    python scripts/review_mcp_candidates.py --out data/public
    python scripts/review_mcp_candidates.py --lanes inventory-sync,barcodes-labels
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from wiseq.agents.integration_catalogue import IntegrationCatalogueAgent  # noqa: E402
from wiseq.db.db import Database  # noqa: E402

GITHUB_API = "https://api.github.com/repos"
BROWSER_UA = "wiseq-hermes-review/1.0"

# Licences that are safe for a commercial system when used as a
# dependency.  Anything not listed here needs a human to read it.
PERMISSIVE = {"MIT", "Apache-2.0", "BSD-2-Clause", "BSD-3-Clause",
              "ISC", "Unlicense", "CC0-1.0", "Zlib", "MPL-2.0"}
# Copyleft: usable, but the obligation travels with the code.
COPYLEFT = {"GPL-2.0", "GPL-3.0", "AGPL-3.0", "LGPL-2.1", "LGPL-3.0"}

# A lane that can move money, stock or customer data needs a human to
# approve the credential before it is handed over.
HIGH_RISK_LANES = {
    "accounting", "order-to-cash", "invoice-parse", "warehouse",
    "inventory-sync", "marketplace-api", "marketplace-sync",
    "bol-com", "helpdesk", "email-automation", "price-intelligence",
    "repricer",
}

# How stale a project may be before its API assumptions are doubtful.
STALE_DAYS = 540


def api_get(path: str, token: str | None) -> dict:
    """GET a GitHub API path, returning {} on any failure."""
    headers = {"User-Agent": BROWSER_UA, "Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(f"{GITHUB_API}/{path}", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return {"__error__": f"HTTP {exc.code}"}
    except Exception as exc:
        return {"__error__": str(exc)}


def days_since(stamp: str) -> int | None:
    """Days since an ISO timestamp, or None when it cannot be read."""
    if not stamp:
        return None
    try:
        from datetime import datetime, timezone

        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - when).days
    except Exception:
        return None


def review(repo: str, lane: str, token: str | None) -> dict:
    """Review one repository."""
    meta = api_get(repo, token)
    if "__error__" in meta:
        return {
            "repo": repo,
            "lane": lane,
            "error": meta["__error__"],
            "verdict": "UNKNOWN",
            "reasons": [f"could not be fetched: {meta['__error__']}"],
        }

    licence = (meta.get("license") or {}).get("spdx_id") or "NOASSERTION"
    archived = bool(meta.get("archived"))
    pushed = meta.get("pushed_at") or ""
    age = days_since(pushed)
    open_issues = meta.get("open_issues_count")
    stars = meta.get("stargazers_count", 0)
    has_issues = bool(meta.get("has_issues"))

    reasons: list[str] = []
    risks: list[str] = []

    if licence in PERMISSIVE:
        reasons.append(f"licence {licence}: permissive, safe to depend on")
    elif licence in COPYLEFT:
        reasons.append(f"licence {licence}: copyleft, obligations travel with it")
        risks.append(f"copyleft licence {licence} -- read before embedding")
    elif licence in ("NOASSERTION", None, ""):
        reasons.append("no licence declared: all rights reserved by default")
        risks.append("NO LICENCE -- cannot be used in a commercial system "
                     "without the author's permission")
    else:
        reasons.append(f"licence {licence}: needs a human read")
        risks.append(f"licence {licence} is not on the known-safe list")

    if archived:
        risks.append("repository is archived -- unmaintained")
    if age is None:
        risks.append("last push date unknown")
    elif age > STALE_DAYS:
        risks.append(f"last push {age} days ago -- API assumptions may be stale")
    else:
        reasons.append(f"pushed {age} days ago")

    if open_issues and open_issues > 20:
        risks.append(f"{open_issues} open issues")
    if not has_issues:
        risks.append("issues are disabled -- problems may be untracked")

    if lane in HIGH_RISK_LANES:
        risks.append(f"lane '{lane}' can touch money, stock or customer data -- "
                     "needs an explicit, revocable credential")

    # A verdict a human can act on.
    blocking = [r for r in risks if r.startswith("NO LICENCE")
                or r.startswith("repository is archived")
                or r.startswith("copyleft")]
    if blocking:
        verdict = "REVIEW_REQUIRED"
    elif risks:
        verdict = "USABLE_WITH_CAUTION"
    else:
        verdict = "USABLE"

    return {
        "repo": repo,
        "lane": lane,
        "url": meta.get("html_url"),
        "license": licence,
        "stars": stars,
        "pushed_at": pushed,
        "days_since_push": age,
        "archived": archived,
        "open_issues": open_issues,
        "description": (meta.get("description") or "")[:200],
        "verdict": verdict,
        "reasons": reasons,
        "risks": risks,
        "high_risk_lane": lane in HIGH_RISK_LANES,
    }


def render(result: dict) -> str:
    """A Markdown review table a human can act on."""
    lines: list[str] = []
    lines.append("# MCP connector review — licence, maintenance, risk")
    lines.append("")
    lines.append(f"Observed: **{result['observed']}**")
    lines.append("")
    lines.append("Every row was checked against the public GitHub API. This is "
                 "evidence for a decision, not a decision: nothing was installed "
                 "and nothing in the system changed.")
    lines.append("")

    counts = result["verdict_counts"]
    lines.append("| Verdict | Connectors |")
    lines.append("| --- | --- |")
    for verdict, count in sorted(counts.items()):
        lines.append(f"| {verdict} | {count} |")
    lines.append("")

    lines.append("## Review")
    lines.append("")
    lines.append("| Connector | Lane | Licence | Last push | Verdict | Blocking risk |")
    lines.append("| --- | --- | --- | --- | --- | --- |")
    for row in result["reviews"]:
        days = row.get("days_since_push")
        age = f"{days}d ago" if days is not None else "unknown"
        blocking = "; ".join(row.get("risks", [])) or "-"
        if len(blocking) > 80:
            blocking = blocking[:77] + "..."
        lines.append(
            f"| `{row['repo']}` | {row['lane']} | {row.get('license', '-')} | "
            f"{age} | **{row['verdict']}** | {blocking} |"
        )
    lines.append("")

    lines.append("## What each verdict means")
    lines.append("")
    lines.append("- **USABLE** — permissive licence, recently maintained, no blocking risk.")
    lines.append("- **USABLE_WITH_CAUTION** — usable, but something needs a human eye: a "
                 "stale push, a lot of open issues, or a lane that can touch money.")
    lines.append("- **REVIEW_REQUIRED** — blocked until read: no licence, an archived "
                 "repository, or a copyleft licence with obligations.")
    lines.append("- **UNKNOWN** — the repository could not be fetched; check it by hand.")
    lines.append("")
    lines.append("## Before anything is installed")
    lines.append("")
    lines.append("1. Read the licence. `NOASSERTION` means all rights are reserved.")
    lines.append("2. For a high-risk lane, give the connector its own scoped, "
                 "revocable credential — never the owner's account token.")
    lines.append("3. Install it in a container that can reach only the one API it needs.")
    lines.append("4. Re-check this table before every release; a licence can change.")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="data/public", help="Output directory")
    parser.add_argument("--repo", default=None, help="Client repository directory")
    parser.add_argument("--lanes", default=None,
                        help="Comma-separated lanes to review (default: all)")
    parser.add_argument("--top", type=int, default=3, help="Candidates per lane")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    repo = Path(args.repo) if args.repo else (root / "data" / "wiseq-repo")
    db = Database("sqlite:///:memory:")
    # The catalogue agent records what it did, so the schema has to exist.
    db.init_schema()
    agent = IntegrationCatalogueAgent(db, repo=repo)
    backlog = agent.build_backlog(limit_per_lane=args.top)

    wanted = {x.strip() for x in (args.lanes or "").split(",") if x.strip()}
    token = os.environ.get("GITHUB_TOKEN") or None

    reviews: list[dict] = []
    for lane in backlog["backlog"]:
        if wanted and lane["lane"] not in wanted:
            continue
        for candidate in lane.get("top") or []:
            repo_name = candidate.get("repo")
            if not repo_name:
                continue
            reviews.append(review(repo_name, lane["lane"], token))
            time.sleep(0.3)

    verdict_counts: dict[str, int] = {}
    for row in reviews:
        verdict_counts[row["verdict"]] = verdict_counts.get(row["verdict"], 0) + 1

    result = {
        "observed": date.today().isoformat(),
        "lanes_reviewed": len(wanted) or backlog["lanes"],
        "connectors_reviewed": len(reviews),
        "verdict_counts": verdict_counts,
        "reviews": reviews,
    }

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = result["observed"]
    (out_dir / f"mcp-review-{stamp}.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / f"mcp-review-{stamp}.md").write_text(render(result), encoding="utf-8")
    (out_dir / "mcp-review-latest.md").write_text(render(result), encoding="utf-8")
    (out_dir / "mcp-review-latest.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"reviewed {len(reviews)} connectors")
    for verdict, count in sorted(verdict_counts.items()):
        print(f"  {verdict}: {count}")
    print(f"wrote {out_dir}/mcp-review-{stamp}.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
