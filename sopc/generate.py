"""Generate a portable pytest contract suite for a compiled plan."""

from __future__ import annotations

from pathlib import Path

from .model import Plan


def render_pytest(plan: Plan) -> str:
    serialized = repr(plan.to_json())
    return f'''"""Generated contract tests for the compiled SOP plan."""

import json

from sopc.executor import execute
from sopc.graph import render_svg
from sopc.model import Plan
from sopc.verify import verify

PLAN = Plan.from_dict(json.loads({serialized}))


def test_generated_plan_passes_static_verification():
    assert verify(PLAN, raise_on_error=False) == ()


def test_generated_plan_has_valid_typed_targets_and_retries():
    declared = {{step.id for step in PLAN.steps}}
    for step in PLAN.steps:
        assert all(target == "END" or target in declared for target in step.outgoing())
        assert step.retry_policy.attempts >= 1
        assert step.retry_policy.factor >= 1
        assert step.retry_policy.max_backoff_ms >= step.retry_policy.backoff_ms


def test_generated_plan_completes_in_simulation():
    grants = sorted({{permission for values in PLAN.roles.values() for permission in values}})
    simulated_plan = Plan(
        title=PLAN.title,
        owner=PLAN.owner,
        trigger=PLAN.trigger,
        roles={{**PLAN.roles, "generated_test": tuple(grants)}},
        steps=PLAN.steps,
        schema_version=PLAN.schema_version,
    )
    checkpoints = {{step.id: "approve" for step in PLAN.steps if step.kind == "checkpoint"}}
    conditions = {{step.condition: True for step in PLAN.steps if step.kind == "decision" and step.condition}}
    result = execute(simulated_plan, role="generated_test", checkpoint_decisions=checkpoints, condition_results=conditions)
    assert result.status == "completed", result.to_dict()


def test_generated_graph_is_deterministic():
    assert render_svg(PLAN) == render_svg(PLAN)
'''


def write_pytest(plan: Plan, path: str | Path) -> None:
    Path(path).write_text(render_pytest(plan), encoding="utf-8", newline="\n")
