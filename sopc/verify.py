"""Static plan checks with stable rule identifiers."""

from __future__ import annotations

from dataclasses import dataclass
import math

from .errors import VerificationError
from .model import Plan, Step


@dataclass(frozen=True)
class Violation:
    code: str
    step_id: str
    reference: str
    message: str

    def __str__(self) -> str:
        return f"{self.code} step={self.step_id} rule={self.reference}: {self.message}"


RULES = {
    "SOPC101": "UNREACHABLE_STEP",
    "SOPC102": "DECISION_NO_CONDITION",
    "SOPC103": "CONSEQUENTIAL_ACTION_REQUIRES_HUMAN_CHECKPOINT",
    "SOPC104": "PERMISSION_NOT_GRANTED",
    "SOPC105": "CONTRADICTORY_RETRY_POLICY",
    "SOPC106": "UNKNOWN_STEP_REFERENCE",
    "SOPC107": "CHECKPOINT_MUST_BE_HUMAN",
}

_CONSEQUENCE_WORDS = {
    "payment": ("charge", "payment", "refund card", "issue refund"),
    "external_send": ("send", "email", "notify", "publish", "message customer"),
    "data_deletion": ("delete", "erase", "remove records", "purge"),
}


def verify(plan: Plan, raise_on_error: bool = True) -> tuple[Violation, ...]:
    by_id = {step.id: step for step in plan.steps}
    violations: list[Violation] = []

    def add(code: str, step: Step, message: str) -> None:
        violations.append(Violation(code, step.id, RULES[code], message))

    for step in plan.steps:
        for target in _all_references(step):
            if target != "END" and target not in by_id:
                add("SOPC106", step, f"target {target!r} does not name a declared step")

        if step.kind == "decision" and not (step.condition and step.condition.strip()):
            add("SOPC102", step, "decision steps require a non-empty Condition")
        if step.kind == "checkpoint" and (step.checkpoint_config is None or not step.checkpoint_config.human):
            add("SOPC107", step, "checkpoint steps must declare a human approval checkpoint")

        retry = step.retry_policy
        if (
            retry.attempts < 1
            or retry.backoff_ms < 0
            or retry.max_backoff_ms < 0
            or not math.isfinite(retry.factor)
            or retry.factor < 1
            or retry.max_backoff_ms < retry.backoff_ms
        ):
            add("SOPC105", step, "attempts must be positive, factor at least 1, and max backoff at least initial backoff")

        declared = {permission for perms in plan.roles.values() for permission in perms}
        missing = sorted(set(step.required_permissions) - declared)
        if missing:
            add("SOPC104", step, f"no declared role grants: {', '.join(missing)}")

    reachable: set[str] = set()
    if plan.entry_step:
        pending = [plan.entry_step]
        while pending:
            current = pending.pop()
            if current in reachable or current not in by_id:
                continue
            reachable.add(current)
            pending.extend(by_id[current].outgoing())
    for step in plan.steps:
        if step.id not in reachable:
            add("SOPC101", step, "step cannot be reached from the declared entry step")

    dominators = _dominators(plan, by_id, reachable)
    checkpoints = {
        step.id for step in plan.steps
        if step.kind == "checkpoint" and step.checkpoint_config is not None and step.checkpoint_config.human
    }
    for step in plan.steps:
        consequence = _consequence(step)
        if step.kind == "action" and consequence and not (dominators.get(step.id, set()) & checkpoints):
            add("SOPC103", step, f"{consequence} action has no human checkpoint on every path before execution")

    result = tuple(violations)
    if result and raise_on_error:
        raise VerificationError(result)
    return result


def _all_references(step: Step) -> tuple[str, ...]:
    refs: list[str] = list(step.outgoing())
    if step.kind == "parallel" and step.join_step:
        refs.append(step.join_step)
    return tuple(refs)


def _consequence(step: Step) -> str | None:
    if step.consequence:
        label = step.consequence.lower().replace(" ", "_")
        if label in {"payment", "external_send", "data_deletion"}:
            return label
        return "consequential"
    content = step.action.lower()
    for category, terms in _CONSEQUENCE_WORDS.items():
        if any(term in content for term in terms):
            return category
    return None


def _dominators(plan: Plan, by_id: dict[str, Step], reachable: set[str]) -> dict[str, set[str]]:
    entry = plan.entry_step
    if entry is None:
        return {}
    predecessors: dict[str, set[str]] = {step_id: set() for step_id in reachable}
    for step in plan.steps:
        if step.id not in reachable:
            continue
        for target in step.outgoing():
            if target in reachable:
                predecessors[target].add(step.id)
    dom: dict[str, set[str]] = {node: set(reachable) for node in reachable}
    dom[entry] = {entry}
    changed = True
    while changed:
        changed = False
        for node in sorted(reachable):
            if node == entry:
                continue
            incoming = predecessors[node]
            common = set.intersection(*(dom[parent] for parent in incoming)) if incoming else set()
            updated = {node} | common
            if updated != dom[node]:
                dom[node] = updated
                changed = True
    return dom
