"""Resumable UCP catalogue scans.

The storefront's UCP/MCP endpoint rate-limits aggressively.  A full
139-SKU scan trips the limit partway through, and the connector already
stops and reports that honestly rather than pretending the catalogue is
empty.

But stopping is only half the job: a scan that throws away every price
it already fetched is expensive to repeat, and the storefront's back-off
window is measured in *tens of minutes*.  The right behaviour is to keep
the prices that were already resolved, remember where the scan stopped,
and continue from there on the next run.

This module holds that progress.  It is deliberately simple and
dependency-free:

  * progress lives in a JSON file next to the database, so a scan
    survives a process restart and a container rebuild;
  * the file is written *after* each successful SKU, so a crash loses at
    most one lookup;
  * a resume only re-requests SKUs that were never resolved, so the
    storefront sees fewer calls on every attempt, not more.
"""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class ScanProgress:
    """The state of a catalogue scan that may span several runs."""

    #: SKUs whose price has been resolved.  Value is the price in EUR.
    resolved: dict[str, float] = field(default_factory=dict)
    #: SKUs the catalogue genuinely does not have.
    not_found: list[str] = field(default_factory=list)
    #: SKUs whose lookup failed for a non-rate-limit reason.
    failed: list[str] = field(default_factory=list)
    #: Titles seen alongside the resolved prices.
    titles: dict[str, str] = field(default_factory=dict)
    #: When the scan last made progress.
    updated_at: str = ""
    #: How many separate runs this scan has taken.
    runs: int = 0

    def pending(self, skus: list[str]) -> list[str]:
        """The SKUs still worth asking about.

        A resolved SKU and a SKU the catalogue genuinely does not have are
        both settled and must not be asked about again -- re-asking them
        wastes the storefront's rate-limit budget on SKUs whose answer
        will not change.

        A *failed* SKU is different: it failed for a transient reason (a
        connection error, a malformed response), not because the product
        does not exist.  Those are retried on the next run, otherwise one
        flaky network moment would permanently drop a product from the
        catalogue.
        """
        settled = set(self.resolved) | set(self.not_found)
        return [s for s in skus if s not in settled]

    def as_dict(self) -> dict[str, Any]:
        return {
            "resolved": self.resolved,
            "not_found": sorted(self.not_found),
            "failed": sorted(self.failed),
            "titles": self.titles,
            "updated_at": self.updated_at,
            "runs": self.runs,
        }


class ScanStore:
    """Persists scan progress to a JSON file, atomically."""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> ScanProgress:
        if not self.path.exists():
            return ScanProgress()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # A corrupt progress file must not stop a scan; it just means
            # the scan restarts from scratch.
            return ScanProgress()
        if not isinstance(payload, dict):
            return ScanProgress()
        return ScanProgress(
            resolved={str(k): float(v) for k, v in (payload.get("resolved") or {}).items()},
            not_found=list(payload.get("not_found") or []),
            failed=list(payload.get("failed") or []),
            titles={str(k): str(v) for k, v in (payload.get("titles") or {}).items()},
            updated_at=str(payload.get("updated_at") or ""),
            runs=int(payload.get("runs") or 0),
        )

    def save(self, progress: ScanProgress) -> None:
        progress.updated_at = datetime.now(timezone.utc).isoformat()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Write to a temp file and rename, so a crash mid-write cannot
        # leave a half-written progress file behind.
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(progress.as_dict(), handle, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise


def default_store_path(db=None) -> Path:
    """Where the scan progress lives for a given database."""
    if db is not None:
        for attr in ("path", "dsn", "database_url"):
            value = getattr(db, attr, None)
            if isinstance(value, str) and value.startswith("sqlite:///"):
                raw = value[len("sqlite:///"):]
                return Path(raw).with_suffix(".ucp_scan.json")
    return Path("./wiseq.ucp_scan.json")
