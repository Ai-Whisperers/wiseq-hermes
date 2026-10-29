"""Shared agent plumbing: audit trail + human-approval gate.

Guardrails come straight from the client operating manual (section 8):
automations must not silently expand client policy.  High-impact actions
(review sends, price changes, strike escalations, assortment switches) are
written to ``approvals`` and wait for a human; everything else is applied
directly but always lands in ``audit_log``.
"""
from __future__ import annotations

import json
from typing import Any

from ..db.db import Database, new_id


def audit(db: Database, actor: str, action: str, entity_type: str | None = None,
          entity_id: str | None = None, detail: Any = None,
          requires_human: bool = False) -> str:
    audit_id = new_id()
    db.execute(
        """INSERT INTO audit_log (audit_id, actor, action, entity_type, entity_id,
                                  detail, requires_human)
           VALUES (?,?,?,?,?,?,?)""",
        (audit_id, actor, action, entity_type, entity_id,
         json.dumps(detail, ensure_ascii=False, default=str) if detail is not None else None,
         1 if requires_human else 0))
    return audit_id


def request_approval(db: Database, agent_name: str, action_type: str,
                      payload: dict, risk: str = "medium") -> str:
    approval_id = new_id()
    db.execute(
        """INSERT INTO approvals (approval_id, agent_name, action_type, payload, risk, status)
           VALUES (?,?,?,?,?, 'pending')""",
        (approval_id, agent_name, action_type,
         json.dumps(payload, ensure_ascii=False, default=str), risk))
    return approval_id


def start_run(db: Database, agent_name: str) -> str:
    run_id = new_id()
    db.execute(
        """INSERT INTO agent_runs (run_id, agent_name, status) VALUES (?,?, 'running')""",
        (run_id, agent_name))
    return run_id


def finish_run(db: Database, run_id: str, processed: int, escalated: int,
                summary: dict) -> None:
    db.execute(
        """UPDATE agent_runs SET finished_at=${NOW}, status='done', processed=?,
               escalated=?, summary=? WHERE run_id=?""".replace("${NOW}", "CURRENT_TIMESTAMP"),
        (processed, escalated, json.dumps(summary, ensure_ascii=False, default=str), run_id))
