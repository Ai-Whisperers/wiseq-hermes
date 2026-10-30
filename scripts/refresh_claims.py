"""Refresh the client's claims ledger against live public evidence.

Why this exists
---------------
``data/CLAIMS-LEDGER.md`` is the control that stops a stale snapshot from
being quoted to the client as current fact.  Its own re-check policy says
rows marked STALE must be re-verified before they are quoted.

But the ledger is a markdown table edited by hand, so nothing enforced
that policy: a STALE row could sit there for months and still look like
a claim.  Worse, a *re-verification* could change the number and leave
the ledger still asserting the old one.

This tool closes that loop.  For each claim with a machine-checkable
public source it:

  1. fetches the live source,
  2. extracts named fields (review count, trust score, verdict, ...),
  3. compares each field the ledger asserts against the live value,
  4. reports AGREE / CHANGED / UNREACHABLE / NO_CHECKER per claim.

The comparison is field-by-field on purpose.  A Trustpilot profile
carries two different numbers -- the displayed rating (4.4) and the
TrustScore (4.5) -- and a fuzzy "does any number match" test would
wrongly call that a change.  Naming the fields keeps the two apart.

It never edits the client repository.  The ledger is a human artefact in
the client's own repo; this produces the evidence needed to update it,
and a per-claim diff a human can act on.

Run::

    .venv/bin/python scripts/refresh_claims.py --out data/public
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LEDGER = ROOT.parent / "wiseq-repo" / "data" / "CLAIMS-LEDGER.md"

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 WiseQ-Audit/1.0"
)


# --------------------------------------------------------------------------
# fetch
# --------------------------------------------------------------------------
def fetch(url: str, timeout: int = 30) -> tuple[bool, str]:
    """Return (ok, text).  A blocked page is a normal outcome, not a crash."""
    try:
        req = Request(url, headers={
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/json",
            "Accept-Language": "nl,en;q=0.8",
        })
        with urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            charset = resp.headers.get_content_charset() or "utf-8"
            return True, raw.decode(charset, errors="replace")
    except HTTPError as exc:
        return False, f"HTTP {exc.code}"
    except URLError as exc:
        return False, f"URLError {exc.reason}"
    except Exception as exc:  # noqa: BLE001 - a page failure is data here
        return False, f"{type(exc).__name__}: {exc}"


# --------------------------------------------------------------------------
# html -> visible text
# --------------------------------------------------------------------------
_TAG = re.compile(r"<[^>]+>")
_SCRIPT = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.S | re.I)


def visible_text(html: str) -> str:
    """Reduce a page to the text a reader would see.

    Pages interleave the value with markup -- ``Trust Score</span>
    <span>0</span>`` -- so a regex over raw HTML misses it.  Dropping
    scripts and tags first is what makes the field extraction reliable.
    """
    text = _SCRIPT.sub(" ", html)
    text = _TAG.sub(" ", text)
    text = (text.replace("&nbsp;", " ").replace("&amp;", "&")
                .replace("&quot;", '"').replace("&#39;", "'"))
    return re.sub(r"\s+", " ", text)


# --------------------------------------------------------------------------
# checkers -- each returns named fields
# --------------------------------------------------------------------------
@dataclass
class Observation:
    """What a checker saw on the live page."""

    checker: str
    source: str
    fields: dict[str, str] = field(default_factory=dict)
    ok: bool = False
    error: str = ""


DUTCH_MONTHS = {
    "jan": 1, "feb": 2, "mrt": 3, "maart": 3, "apr": 4, "mei": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "okt": 10, "nov": 11, "dec": 12,
}


def _latest_date(dates: list[str]) -> str:
    """Return the most recent of 'D month YYYY' strings."""
    best = ""
    best_key = (-1, -1, -1)
    for raw in dates:
        m = re.match(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", raw)
        if not m:
            continue
        day, month_name, year = int(m.group(1)), m.group(2).lower(), int(m.group(3))
        month = DUTCH_MONTHS.get(month_name[:4]) or DUTCH_MONTHS.get(month_name[:3])
        if not month:
            continue
        key = (year, month, day)
        if key > best_key:
            best_key, best = key, raw
    return best


def _trustpilot(html: str) -> Observation:
    """Read the review count and both scores off the Trustpilot profile.

    The profile carries two different ratings: the TrustScore (4.5) and
    the displayed rating (4.4).  They are read into separate fields so
    a comparison never confuses one for the other.
    """
    obs = Observation("trustpilot", "https://nl.trustpilot.com/review/wiseq.nl")
    text = visible_text(html)

    m = re.search(r"TrustScore\s*([0-9]+(?:[.,][0-9])?)\s*uit\s*5", text)
    if m:
        obs.fields["trust_score"] = m.group(1).replace(",", ".")

    # The displayed rating is the standalone number that follows the
    # "TrustScore X uit 5" phrase.
    m = re.search(r"TrustScore[^0-9]{0,40}[0-9.,]+\s*uit\s*5\s*([0-5](?:[.,][0-9])?)\b", text)
    if m:
        obs.fields["displayed_rating"] = m.group(1).replace(",", ".")

    counts = re.findall(r"\b([0-9]{1,5})\s+(?:reviews|beoordelingen|recensies)\b", text, re.I)
    if counts:
        obs.fields["reviews"] = counts[0]

    # Not every review carries the "Geüpdatet op" prefix -- some show a
    # bare date -- so every Dutch-format date on the profile is collected
    # and the most recent one is the latest review.
    month = r"(?:jan|feb|mrt|maart|apr|mei|jun|jul|aug|sep|okt|nov|dec)[a-z]*"
    dates = re.findall(rf"(\d{{1,2}}\s+{month}\s+\d{{4}})", text, re.I)
    latest = _latest_date(dates)
    if latest:
        obs.fields["latest_review"] = latest

    obs.ok = bool(obs.fields)
    return obs


def _scamadviser(html: str) -> Observation:
    """Read the ScamAdviser verdict off the domain check page."""
    obs = Observation("scamadviser", "https://www.scamadviser.com/check-website/wiseq.nl")
    text = visible_text(html)

    if "Very Likely Unsafe" in text:
        obs.fields["verdict"] = "Very Likely Unsafe"
    elif "Likely Safe" in text:
        obs.fields["verdict"] = "Likely Safe"

    m = re.search(r"Trust Score\s*([0-9]+)", text)
    if m:
        obs.fields["trust_score"] = m.group(1)

    m = re.search(r"reported to us as possible scam by\s*([^,\.]+)", text)
    if m:
        obs.fields["reporter"] = m.group(1).strip()

    m = re.search(r"hasn't been scanned in more than ([0-9]+) days", text)
    if m:
        obs.fields["scan_age_days"] = m.group(1)

    obs.ok = bool(obs.fields)
    return obs


def _bol_count(html: str) -> Observation:
    """Read the seller's listing count off a bol.com search page."""
    obs = Observation("bol_count", "https://www.bol.com/nl/nl/s/?seller=1428598")
    m = re.search(r"([0-9][0-9.]*)\s+resultaten", visible_text(html), re.I)
    if m:
        obs.fields["count"] = m.group(1)
    obs.ok = bool(obs.fields)
    return obs


def _thuiswinkel(html: str) -> Observation:
    """Look for the Thuiswinkel membership fee on the tariff page."""
    obs = Observation("thuiswinkel", "https://www.thuiswinkel.org/over-thuiswinkel/lidmaatschap")
    amounts = re.findall(r"(?:EUR|€)\s*([0-9][0-9.,]{2,})", visible_text(html))
    if amounts:
        obs.fields["amounts"] = ", ".join(amounts[:5])
    obs.ok = bool(amounts)
    return obs


CHECKERS = {
    "trustpilot": _trustpilot,
    "scamadviser": _scamadviser,
    "bol_count": _bol_count,
    "thuiswinkel": _thuiswinkel,
}


# --------------------------------------------------------------------------
# claims
# --------------------------------------------------------------------------
@dataclass
class Claim:
    """A ledger row that can be re-verified from the public web."""

    number: int
    text: str
    status: str
    checker: str
    expected: dict[str, str] = field(default_factory=dict)


@dataclass
class CheckResult:
    claim: Claim
    observation: Observation
    verdict: str = ""
    detail: str = ""


def _normalise(value: str) -> str:
    """Compare numbers and words without formatting noise."""
    return value.strip().replace(",", ".").replace(" ", "").lower()


def compare(claim: Claim, obs: Observation) -> tuple[str, str]:
    """Compare the fields the ledger asserts against the live values.

    Only the fields the ledger actually names are compared.  A claim
    that says nothing checkable is reported as AGREE-with-no-comparison
    rather than given an invented verdict.
    """
    if not claim.expected:
        return "AGREE", "no machine-comparable value in the ledger text"

    changed: list[str] = []
    agree: list[str] = []
    missing: list[str] = []

    for key, expected in claim.expected.items():
        live = obs.fields.get(key)
        if live is None:
            missing.append(f"{key} not found on the live page (ledger asserts {expected!r})")
            continue
        if _normalise(live) == _normalise(expected):
            agree.append(f"{key}={live}")
        else:
            changed.append(f"{key}: ledger says {expected!r}, live shows {live!r}")

    if changed:
        return "CHANGED", "; ".join(changed)
    if missing:
        return "UNREACHABLE", "; ".join(missing)
    return "AGREE", ", ".join(agree)


def check(claim: Claim) -> CheckResult:
    """Fetch the claim's source and compare it with what the ledger says."""
    checker = CHECKERS.get(claim.checker)
    if checker is None:
        obs = Observation(claim.checker, "", {}, False, f"no checker for {claim.checker!r}")
        return CheckResult(claim, obs, "NO_CHECKER", obs.error)

    ok, payload = fetch(CHECKER_SOURCE[claim.checker])
    if not ok:
        obs = Observation(claim.checker, CHECKER_SOURCE[claim.checker], {}, False, payload)
        return CheckResult(claim, obs, "UNREACHABLE", payload)

    obs = checker(payload)
    if not obs.ok:
        return CheckResult(claim, obs, "UNREACHABLE", obs.error or "value not found on page")

    verdict, detail = compare(claim, obs)
    return CheckResult(claim, obs, verdict, detail)


# The source URL for each checker -- kept next to the checkers themselves.
CHECKER_SOURCE = {
    "trustpilot": "https://nl.trustpilot.com/review/wiseq.nl",
    "scamadviser": "https://www.scamadviser.com/check-website/wiseq.nl",
    "bol_count": "https://www.bol.com/nl/nl/s/?seller=1428598",
    "thuiswinkel": "https://www.thuiswinkel.org/over-thuiswinkel/lidmaatschap",
}


# --------------------------------------------------------------------------
# ledger parsing
# --------------------------------------------------------------------------
LEDGER_ROW = re.compile(r"^\|\s*(\d+)\s*\|\s*(.*?)\s*\|\s*(\*\*[^*]+\*\*[^*]*)\s*\|")


def _pick_checker(claim_text: str) -> str | None:
    lowered = claim_text.lower()
    if "trustpilot" in lowered:
        return "trustpilot"
    if "scamadviser" in lowered:
        return "scamadviser"
    if "bol" in lowered and ("listing" in lowered or "resultaten" in lowered):
        return "bol_count"
    if "thuiswinkel" in lowered:
        return "thuiswinkel"
    return None


def _expected_for(checker: str, claim_text: str) -> dict[str, str]:
    """Read the values the ledger row asserts, per checker.

    These are taken from the claim text itself rather than hardcoded, so
    a hand-edited ledger row is checked against what it actually says.
    """
    if checker == "trustpilot":
        expected: dict[str, str] = {}
        m = re.search(r"([0-9]{1,5})\s+reviews", claim_text, re.I)
        if m:
            expected["reviews"] = m.group(1)
        # "4.4/5" is the displayed rating; a bare "TrustScore 4.5" is the
        # other number and must not be mistaken for it.
        m = re.search(r"([0-9](?:[.,][0-9])?)\s*/\s*5", claim_text)
        if m:
            expected["displayed_rating"] = m.group(1).replace(",", ".")
        m = re.search(r"trustscore\s*([0-9](?:[.,][0-9])?)", claim_text, re.I)
        if m:
            expected["trust_score"] = m.group(1).replace(",", ".")
        return expected
    if checker == "scamadviser":
        expected = {}
        m = re.search(r"trustscore\s*([0-9])", claim_text, re.I)
        if m:
            expected["trust_score"] = m.group(1)
        if "unsafe" in claim_text.lower():
            expected["verdict"] = "Very Likely Unsafe"
        return expected
    if checker == "bol_count":
        # "bol listing count 312 vs 230 own-shop SKUs" -- the listing
        # count is the number that follows the word "count".
        m = re.search(r"count\s+([0-9]{1,5})", claim_text, re.I)
        if m:
            return {"count": m.group(1)}
        m = re.search(r"\b([0-9]{2,5})\s+(?:listing|resultaten)", claim_text, re.I)
        return {"count": m.group(1)} if m else {}
    if checker == "thuiswinkel":
        amounts = re.findall(r"[€\s]?([0-9]{3,4})(?:-([0-9]{3,4}))?", claim_text)
        if amounts:
            return {"amounts": amounts[0][0]}
        return {}
    return {}


def build_claims(text: str) -> list[Claim]:
    """Pull the checkable rows out of the ledger table.

    Only rows naming one of the known checkers are returned; the rest of
    the ledger is prose a machine cannot adjudicate.
    """
    claims: list[Claim] = []
    seen: set[int] = set()
    for line in text.splitlines():
        m = LEDGER_ROW.match(line.strip())
        if not m:
            continue
        number, claim_text = int(m.group(1)), m.group(2)
        status = m.group(3).strip().strip("*").strip()
        if number in seen:
            continue
        checker = _pick_checker(claim_text)
        if checker is None:
            continue
        seen.add(number)
        claims.append(Claim(number=number, text=claim_text, status=status,
                            checker=checker, expected=_expected_for(checker, claim_text)))
    return claims


# --------------------------------------------------------------------------
# rendering
# --------------------------------------------------------------------------
VERDICT_MEANING = {
    "AGREE": "the live page still shows what the ledger asserts",
    "CHANGED": "the live page shows a different value -- update the ledger",
    "UNREACHABLE": "the source could not be read (bot wall, 403, or a moved page)",
    "NO_CHECKER": "no machine check exists for this claim",
}


def render(results: list[CheckResult], ledger_path: str, observed_on: str) -> str:
    counts: dict[str, int] = {}
    for r in results:
        counts[r.verdict] = counts.get(r.verdict, 0) + 1

    lines = [
        "# Claims ledger freshness check",
        "",
        f"- **Ledger checked:** `{ledger_path}`",
        f"- **Observed:** {observed_on}",
        f"- **Checkable claims:** {len(results)}",
        "",
        "| Verdict | Claims | Meaning |",
        "|---|---|---|",
    ]
    for verdict, meaning in VERDICT_MEANING.items():
        lines.append(f"| {verdict} | {counts.get(verdict, 0)} | {meaning} |")

    lines += ["", "## Per-claim detail", "",
              "| # | Claim | Ledger status | Live observation | Verdict |",
              "|---|---|---|---|---|"]
    for r in results:
        obs = ", ".join(f"{k}={v}" for k, v in r.observation.fields.items()) or r.observation.error
        claim = r.claim.text.replace("|", "/")
        lines.append(
            f"| {r.claim.number} | {claim} | {r.claim.status} | {obs} | {r.verdict} |"
        )

    lines += ["", "## What this does not do", "",
              "- It does not edit the client's ledger. The ledger is a human artefact.",
              "- It does not change a claim's status. A CHANGED row needs a human to "
              "decide whether the ledger is wrong or the world moved.",
              "- An unreachable source is never read as agreement.",
              ""]

    changed = [r for r in results if r.verdict == "CHANGED"]
    if changed:
        lines += ["## Rows needing a decision", ""]
        for r in changed:
            lines.append(f"- **Claim {r.claim.number}** -- {r.detail}")
        lines.append("")

    return "\n".join(lines)


# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    parser.add_argument("--out", default=None, help="directory for the report and JSON")
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args(argv)

    ledger = Path(args.ledger)
    if not ledger.exists():
        print(f"ledger not found: {ledger}", file=sys.stderr)
        return 2

    text = ledger.read_text(encoding="utf-8")
    claims = build_claims(text)
    if not claims:
        print("no checkable claims found", file=sys.stderr)
        return 1

    observed_on = date.today().isoformat()
    results = [check(c) for c in claims]

    payload = {
        "observed": observed_on,
        "ledger": str(ledger),
        "claims_checked": len(results),
        "verdict_counts": {
            v: sum(1 for r in results if r.verdict == v) for v in VERDICT_MEANING
        },
        "results": [
            {
                "number": r.claim.number,
                "claim": r.claim.text,
                "ledger_status": r.claim.status,
                "checker": r.claim.checker,
                "expected": r.claim.expected,
                "source": r.observation.source,
                "observed": r.observation.fields,
                "error": r.observation.error,
                "verdict": r.verdict,
                "detail": r.detail,
            }
            for r in results
        ],
    }

    report = render(results, str(ledger), observed_on)

    if args.out:
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = observed_on
        (out_dir / f"claims-freshness-{stamp}.md").write_text(report, encoding="utf-8")
        (out_dir / f"claims-freshness-{stamp}.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    if args.json_out:
        Path(args.json_out).write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"checked {len(results)} claims")
    for verdict, n in payload["verdict_counts"].items():
        if n:
            print(f"  {verdict}: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
