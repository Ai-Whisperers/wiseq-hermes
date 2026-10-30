"""The live warranty contradiction must be visible, not just documented.

The storefront states one year on the general terms and two years on
the school-facing pages.  That disagreement is on WiseQ's live site and
only Rob can fix it, but the replica must not quietly paper over it:
an agent that reads one page and answers a customer will state a
different rule than an agent that reads another.

These tests pin the *shape* of that refusal so it cannot be removed by
a careless refactor.
"""
from __future__ import annotations

import json

import pytest

from wiseq.agents.warranty_policy import (
    INTERNAL_WARRANTY_YEARS,
    PUBLIC_WARRANTY_YEARS_BY_PAGE,
    decide_warranty,
    public_warranty_contradiction,
    warranty_answer_requires_confirmation,
)


def test_the_public_pages_genuinely_disagree():
    contradiction = public_warranty_contradiction()
    assert contradiction["contradicted"] is True
    assert contradiction["years_found"] == [1, 2]


def test_both_positions_are_attributed_to_real_pages():
    """Neither year may be claimed without saying which pages say it."""
    contradiction = public_warranty_contradiction()
    by_years = contradiction["pages_by_years"]
    assert by_years["1"], "the one-year position needs page attribution"
    assert by_years["2"], "the two-year position needs page attribution"
    assert contradiction["pages_conflicting_with_manual"], (
        "the pages that disagree with the manual must be listed"
    )


def test_the_manual_and_the_pages_are_compared_not_merged():
    """The manual's year is reported separately from the public years.

    Merging them would hide the contradiction, which is the whole
    reason this module exists.
    """
    contradiction = public_warranty_contradiction()
    assert contradiction["internal_manual_years"] == INTERNAL_WARRANTY_YEARS
    assert INTERNAL_WARRANTY_YEARS in contradiction["years_found"]
    assert contradiction["internal_agrees_with"] == ["2"]


def test_the_contradiction_blocks_an_automated_customer_answer():
    assert public_warranty_contradiction()["blocks_automated_customer_answer"] is True
    assert warranty_answer_requires_confirmation() is True


def test_the_resolution_has_a_named_owner():
    contradiction = public_warranty_contradiction()
    assert contradiction["resolution_owner"] == "Rob (WiseQ)"


def test_the_report_is_json_serialisable():
    """The API returns this straight to a client."""
    json.dumps(public_warranty_contradiction())


def test_every_listed_page_is_a_known_page():
    """A typo in a page path would silently weaken the finding."""
    for page in PUBLIC_WARRANTY_YEARS_BY_PAGE:
        assert page.startswith("/")
        assert " " not in page


def test_the_agent_still_applies_the_manual_not_the_pages():
    """The warranty decision must not change because a page says one year.

    The internal manual says two years.  The agent applies the manual.
    If the agent ever starts reading the storefront for its warranty
    period, this test fails.
    """
    from wiseq.agents.warranty_policy import DamageType

    # At 18 months with no physical break, a two-year warranty covers it.
    decision = decide_warranty("WiseQ One", 18, DamageType.NO_PHYSICAL_BREAK)
    assert decision.covered is True


def test_the_public_finding_is_kept_in_sync_with_the_audit():
    """The page list must match what the live audit actually observed.

    If someone re-runs the page audit and the storefront changed, this
    test points at the stale constant.
    """
    audit = public_warranty_contradiction()
    assert audit["years_found"], "the finding must not be empty"

    pages_by_years = audit["pages_by_years"]
    flat = {page for pages in pages_by_years.values() for page in pages}
    assert flat == set(PUBLIC_WARRANTY_YEARS_BY_PAGE)
