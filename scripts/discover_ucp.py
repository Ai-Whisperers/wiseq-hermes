"""Discover what WiseQ's live UCP endpoint actually supports.

Why this exists
---------------
The UCP connector has a hard-coded allow list of read-only tools.  That
list was written from the tool names the endpoint published when the
connector was first written.  Two things can make it wrong:

  * the storefront can add a tool, and the connector would then refuse
    a call that is actually safe and read-only;
  * the storefront can change its advertised UCP *version*, and a
    connector that negotiates against a stale version is silently
    speaking a protocol the server no longer supports.

Neither shows up as an error.  The connector just keeps using the old
list against a server that moved on.

So this script asks the server what it publishes, right now, and
compares the answer against what the connector assumes.  The result is
evidence, and it is written to ``data/public/`` so the claim "the
connector covers the live catalogue" is checkable rather than
asserted.

It also captures the ``/.well-known/ucp`` discovery document.  That
document is the negotiation surface: it names the protocol version, the
capabilities, and the service endpoints.  It changes when the
storefront upgrades, and it is the thing to diff when something breaks.

Read-only.  It calls ``initialize`` and ``tools/list``, both of which
are reads.  It never calls a write tool.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from wiseq.connectors.ucp import (  # noqa: E402
    DEFAULT_DISCOVERY,
    DEFAULT_MCP,
    DEFAULT_STORE,
    READ_ONLY_TOOLS,
    WRITE_TOOLS,
    UCPClient,
)

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)


def fetch_discovery(url: str = DEFAULT_DISCOVERY, timeout: int = 30) -> dict:
    """Fetch the storefront's UCP discovery document."""
    request = urllib.request.Request(
        url,
        headers={"accept": "application/json", "user-agent": BROWSER_UA},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def normalise_discovery(document: dict) -> dict:
    """Pull the parts that matter out of a discovery document."""
    ucp = document.get("ucp") or document
    capabilities = ucp.get("capabilities") or {}
    services = ucp.get("services") or {}

    endpoints = []
    for service_id, bindings in services.items():
        for binding in bindings or []:
            endpoints.append({
                "service": service_id,
                "transport": binding.get("transport"),
                "version": binding.get("version"),
                "endpoint": binding.get("endpoint"),
                "schema": binding.get("schema"),
                "spec": binding.get("spec"),
            })

    return {
        "version": ucp.get("version"),
        "supported_versions": sorted((ucp.get("supported_versions") or {}).keys()),
        "capabilities": sorted(capabilities.keys()),
        "capability_versions": {
            name: sorted({b.get("version") for b in (bindings or []) if b.get("version")})
            for name, bindings in capabilities.items()
        },
        "services": endpoints,
        "payment_handlers": ucp.get("payment_handlers") or [],
    }


def compare_with_connector(tools: list[dict]) -> dict:
    """Compare the server's tool list with the connector's allow list.

    The comparison has to distinguish three groups, not two.  A tool the
    server publishes that the connector blocks *on purpose* -- a
    checkout, a cart mutation -- is correct behaviour, not drift.  A
    tool the server publishes that the connector does not know about at
    all, and that reads data, IS drift: the connector would refuse a
    safe call.
    """
    published = sorted({t.get("name") for t in tools if t.get("name")})
    allowed = sorted(READ_ONLY_TOOLS)
    blocked = sorted(WRITE_TOOLS)

    unknown = sorted(set(published) - set(allowed) - set(blocked))
    return {
        "published_tools": published,
        "published_count": len(published),
        "connector_read_only_allow_list": allowed,
        "connector_write_block_list": blocked,
        "allowed_but_not_published": sorted(set(allowed) - set(published)),
        "published_but_blocked_on_purpose": sorted(set(published) & set(blocked)),
        "published_but_unknown": unknown,
        "covered": sorted(set(published) & set(allowed)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="data/public")
    parser.add_argument("--store", default=DEFAULT_STORE)
    parser.add_argument("--endpoint", default=None,
                        help="MCP endpoint (defaults to the store's /api/ucp/mcp)")
    args = parser.parse_args()

    endpoint = args.endpoint or f"{args.store.rstrip('/')}/api/ucp/mcp"

    report: dict = {
        "observed": time.strftime("%Y-%m-%d"),
        "store": args.store,
        "mcp_endpoint": endpoint,
    }

    # -- the discovery document -------------------------------------
    try:
        document = fetch_discovery(f"{args.store.rstrip('/')}/.well-known/ucp.json")
        report["discovery"] = normalise_discovery(document)
        report["discovery_ok"] = True
    except Exception as exc:  # noqa: BLE001 -- the report records the failure
        report["discovery_ok"] = False
        report["discovery_error"] = f"{type(exc).__name__}: {exc}"

    # -- the tools the server publishes -----------------------------
    client = UCPClient(endpoint=endpoint, profile=f"{args.store.rstrip('/')}/.well-known/ucp.json")
    try:
        server_info = client.initialize()
        tools = client.list_tools()
        report["server_info"] = server_info
        report["comparison"] = compare_with_connector(tools)
        report["tools_ok"] = True
    except Exception as exc:  # noqa: BLE001
        report["tools_ok"] = False
        report["tools_error"] = f"{type(exc).__name__}: {exc}"

    # -- the verdict ------------------------------------------------
    problems = []
    if not report.get("discovery_ok"):
        problems.append("could not read the discovery document")
    if not report.get("tools_ok"):
        problems.append("could not list the published tools")

    comparison = report.get("comparison") or {}
    unknown = comparison.get("published_but_unknown") or []
    if unknown:
        problems.append(
            "the server publishes tools the connector does not classify: "
            + ", ".join(unknown)
        )
    allowed_not_published = comparison.get("allowed_but_not_published") or []
    if allowed_not_published:
        problems.append(
            "the connector allows tools the server does not publish: "
            + ", ".join(allowed_not_published)
        )

    report["problems"] = problems
    report["verdict"] = "ALIGNED" if not problems else "DRIFT"

    # -- write it out ------------------------------------------------
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = report["observed"]
    json_path = out_dir / f"ucp-discovery-{stamp}.json"
    json_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "ucp-discovery-latest.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    # -- a human-readable summary ------------------------------------
    lines = [
        "# WiseQ UCP discovery",
        "",
        f"Observed {stamp} against `{args.store}`.",
        "",
    ]
    if report.get("discovery_ok"):
        discovery = report["discovery"]
        lines += [
            "## Protocol",
            "",
            f"- advertised version: `{discovery['version']}`",
            f"- also supported: {', '.join(discovery['supported_versions']) or '(none listed)'}",
            "",
            "## Capabilities",
            "",
        ]
        for capability in discovery["capabilities"]:
            versions = ", ".join(discovery["capability_versions"].get(capability) or [])
            lines.append(f"- `{capability}` ({versions})")
        lines += ["", "## Service endpoints", ""]
        for service in discovery["services"]:
            lines.append(
                f"- `{service['service']}` via {service['transport']}: "
                f"{service['endpoint'] or '(embedded)'} v{service['version']}"
            )
        lines.append("")
    else:
        lines += ["## Discovery", "", f"FAILED: {report.get('discovery_error')}", ""]

    if report.get("tools_ok"):
        comparison = report["comparison"]
        lines += [
            "## Tool coverage",
            "",
            f"- server publishes: {comparison['published_count']} tool(s)",
            f"- connector allows: {len(comparison['connector_read_only_allow_list'])} read-only tool(s)",
            f"- covered: {', '.join(comparison['covered']) or '(none)'}",
            "",
        ]
        if comparison["published_but_blocked_on_purpose"]:
            lines.append("**published, blocked on purpose (writes):**")
            lines += [f"- `{t}`" for t in comparison["published_but_blocked_on_purpose"]]
            lines.append("")
        if comparison["published_but_unknown"]:
            lines.append("**published but unclassified:**")
            lines += [f"- `{t}`" for t in comparison["published_but_unknown"]]
            lines.append("")
        if comparison["allowed_but_not_published"]:
            lines.append("**allowed but not published:**")
            lines += [f"- `{t}`" for t in comparison["allowed_but_not_published"]]
            lines.append("")
    else:
        lines += ["## Tools", "", f"FAILED: {report.get('tools_error')}", ""]

    lines += [
        "## Verdict",
        "",
        f"**{report['verdict']}**",
        "",
    ]
    if problems:
        lines += ["Problems:"] + [f"- {p}" for p in problems] + [""]
    else:
        lines += ["The connector's allow list matches what the server publishes."] + [""]

    md_path = out_dir / f"ucp-discovery-{stamp}.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")
    (out_dir / "ucp-discovery-latest.md").write_text("\n".join(lines), encoding="utf-8")

    print(f"verdict={report['verdict']}")
    print(f"wrote {md_path}")
    if problems:
        for problem in problems:
            print(f"  problem: {problem}")
    return 0 if report["verdict"] == "ALIGNED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
