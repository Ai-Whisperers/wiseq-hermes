"""Every audited issue type must carry a concrete fix.

A finding a reader cannot act on is a finding they will skip. The audit
report lists issue types by name; this test makes sure each one also says
what to do about it, so the report is usable rather than merely complete.

It also guards the reverse case: a new issue type added to the audit
without guidance would otherwise show up in the report with no remedy
and nobody would notice.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import audit_pages  # noqa: E402


class TestIssueFixGuidance:
    def test_every_issue_type_the_audit_can_emit_has_a_fix(self):
        # These are exactly the keys the audit writes into result["issues"].
        emitted = {
            "unreachable",
            "noindex",
            "missing_meta_description",
            "missing_canonical",
            "missing_structured_data",
            "malformed_structured_data",
            "missing_h1",
            "multiple_h1",
            "missing_viewport",
            "missing_open_graph",
        }
        missing = emitted - set(audit_pages.ISSUE_FIXES)
        assert not missing, f"issue types with no guidance: {sorted(missing)}"

    def test_no_guidance_for_an_issue_type_that_does_not_exist(self):
        emitted = {
            "unreachable", "noindex", "missing_meta_description",
            "missing_canonical", "missing_structured_data",
            "malformed_structured_data", "missing_h1", "multiple_h1",
            "missing_viewport", "missing_open_graph",
        }
        extra = set(audit_pages.ISSUE_FIXES) - emitted
        assert not extra, f"guidance for unknown issue types: {sorted(extra)}"

    def test_each_fix_is_a_real_sentence_not_a_placeholder(self):
        for name, fix in audit_pages.ISSUE_FIXES.items():
            assert fix.strip(), f"{name} has empty guidance"
            assert len(fix) > 40, f"{name} guidance is too terse to act on"
            assert fix.endswith("."), f"{name} guidance is not a sentence"

    def test_the_rendered_report_includes_the_fix_column(self):
        result = {
            "observed": "2026-10-30",
            "store": "https://www.wiseq.nl",
            "discovered": {},
            "audited": {"pages": 2, "products_sampled": 0},
            "pages": [],
            "product_sample": [],
            "findings": [],
            "issues": {
                "missing_meta_description": ["https://example.invalid/x"],
                "unreachable": [],
                "noindex": [],
                "missing_canonical": [],
                "missing_structured_data": [],
                "malformed_structured_data": [],
                "missing_h1": [],
                "multiple_h1": [],
                "missing_viewport": [],
                "missing_open_graph": [],
            },
        }
        report = audit_pages.render_report(result)
        assert "What to do" in report
        assert "Fix:" in report
        assert "https://example.invalid/x" in report
        # The guidance text itself must appear, not just the heading.
        assert audit_pages.ISSUE_FIXES["missing_meta_description"] in report

    def test_a_clean_audit_says_so_and_omits_the_table(self):
        result = {
            "observed": "2026-10-30",
            "store": "https://www.wiseq.nl",
            "discovered": {},
            "audited": {"pages": 1, "products_sampled": 0},
            "pages": [],
            "product_sample": [],
            "findings": [],
            "issues": {
                "unreachable": [], "noindex": [], "missing_meta_description": [],
                "missing_canonical": [], "missing_structured_data": [],
                "malformed_structured_data": [], "missing_h1": [],
                "multiple_h1": [], "missing_viewport": [], "missing_open_graph": [],
            },
        }
        report = audit_pages.render_report(result)
        assert "No technical issue was found" in report
        assert "What to do" not in report
