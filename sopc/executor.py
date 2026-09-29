"""Deterministic state-machine executor with simulated adapters and audit events."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

from .model import Plan, Step
from .verify import verify


@dataclass
class ExecutionResult:
    status: str
    events: list[dict[str, Any]] = field(default_factory=list)
    completed_steps: list[str] = field(default_factory=list)
    paused_at: str | None = None
    error_code: str | None = None
    message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "completed_steps": self.completed_steps,
            "paused_at": self.paused_at,
            "error_code": self.error_code,
            "message": self.message,
            "events": self.events,
        }


class _Stop(Exception):
    def __init__(self, status: str, step_id: str | None = None, code: str | None = None, message: str | None = None):
        self.status = status
        self.step_id = step_id
        self.code = code
        self.message = message


class SimulatedExecutor:
    """Run a plan without external side effects; adapters are deterministic test inputs."""

    def __init__(
        self,
        plan: Plan,
        role: str,
        *,
        checkpoint_decisions: dict[str, Any] | None = None,
        condition_results: dict[str, bool] | None = None,
        adapter_outcomes: dict[str, list[str | bool]] | None = None,
        check_results: dict[str, bool] | None = None,
        checkpoint_handler: Any = None,
        max_step_visits: int = 1000,
    ):
        self.plan = plan
        self.role = role
        self.grants = set(plan.roles.get(role, ()))
        self.checkpoint_decisions = {
            key: list(value) if isinstance(value, list) else value
            for key, value in (checkpoint_decisions or {}).items()
        }
        self.condition_results = condition_results or {}
        self.adapter_outcomes = adapter_outcomes or {}
        self.check_results = check_results or {}
        self.checkpoint_handler = checkpoint_handler
        self.max_step_visits = max_step_visits
        self.by_id = {step.id: step for step in plan.steps}
        self.events: list[dict[str, Any]] = []
        self.completed: list[str] = []
        self.visits: dict[str, int] = {}

    def run(self) -> ExecutionResult:
        if not self.plan.entry_step:
            return ExecutionResult("failed", error_code="SOPC-RUN-EMPTY", message="plan has no entry step")
        violations = verify(self.plan, raise_on_error=False)
        if violations:
            return ExecutionResult(
                "failed",
                error_code="SOPC-RUN-PLAN-INVALID",
                message="\n".join(str(violation) for violation in violations),
            )
        try:
            outcome, paused_at = self._walk(self.plan.entry_step)
            status = "paused" if outcome == "paused" else "completed"
            return ExecutionResult(status, self.events, self.completed, paused_at=paused_at)
        except _Stop as stop:
            return ExecutionResult(
                status=stop.status,
                events=self.events,
                completed_steps=self.completed,
                paused_at=stop.step_id if stop.status == "paused" else None,
                error_code=stop.code,
                message=stop.message,
            )

    def _event(self, event_type: str, step: Step | None = None, **data: Any) -> None:
        item = {"seq": len(self.events) + 1, "type": event_type}
        if step is not None:
            item["step_id"] = step.id
        item.update(data)
        self.events.append(item)

    def _walk(self, start: str, stop_before: str | None = None) -> tuple[str, str | None]:
        cursor = start
        while cursor != "END":
            if stop_before and cursor == stop_before:
                return "joined", None
            step = self.by_id.get(cursor)
            if step is None:
                raise _Stop("failed", cursor, "SOPC-RUN-UNKNOWN-STEP", f"step {cursor!r} is not present")
            self.visits[cursor] = self.visits.get(cursor, 0) + 1
            if self.visits[cursor] > self.max_step_visits:
                raise _Stop("failed", cursor, "SOPC-RUN-STEP-LIMIT", "maximum step visit count exceeded")
            self._authorize(step)
            if not self._check_expressions(step, "preconditions", step.preconditions):
                raise _Stop("failed", step.id, "SOPC-RUN-PRECONDITION-FAILED", "precondition check failed")

            if step.kind == "action":
                self._run_action(step)
                if not self._check_expressions(step, "postconditions", step.postconditions):
                    raise _Stop("failed", step.id, "SOPC-RUN-POSTCONDITION-FAILED", "postcondition check failed")
                self.completed.append(step.id)
                cursor = step.next_step or "END"
            elif step.kind == "decision":
                self._event("decision.evaluated", step, condition=step.condition)
                if not step.condition or step.condition not in self.condition_results:
                    raise _Stop("paused", step.id, "SOPC-RUN-DECISION-NEEDS-RESULT", "supply a simulated result for this condition")
                result = bool(self.condition_results[step.condition])
                target = step.true_step if result else step.false_step
                self._event("decision.routed", step, result=result, target=target)
                self.completed.append(step.id)
                cursor = target or "END"
            elif step.kind == "checkpoint":
                cursor = self._checkpoint(step)
                if cursor is None:
                    return "paused", step.id
            elif step.kind == "parallel":
                self._event("parallel.started", step, branches=list(step.branches), join=step.join_step)
                if not step.join_step:
                    raise _Stop("failed", step.id, "SOPC-RUN-PARALLEL-JOIN", "parallel step has no join step")
                for branch in step.branches:
                    outcome, paused_at = self._walk(branch, stop_before=step.join_step)
                    if outcome == "paused":
                        return "paused", paused_at
                    if outcome != "joined":
                        raise _Stop("failed", step.id, "SOPC-RUN-PARALLEL-JOIN", f"branch {branch!r} ended before join {step.join_step!r}")
                self._event("parallel.joined", step, join=step.join_step)
                self.completed.append(step.id)
                cursor = step.join_step
            else:
                raise _Stop("failed", step.id, "SOPC-RUN-UNKNOWN-KIND", f"unsupported step kind {step.kind!r}")
        if stop_before:
            raise _Stop("failed", stop_before, "SOPC-RUN-PARALLEL-JOIN", f"path ended before join {stop_before!r}")
        return "completed", None

    def _authorize(self, step: Step) -> None:
        missing = sorted(set(step.required_permissions) - self.grants)
        if missing:
            self._event("permission.denied", step, role=self.role, missing=missing)
            raise _Stop("failed", step.id, "SOPC-RUN-PERMISSION-DENIED", f"role {self.role!r} lacks {', '.join(missing)}")
        self._event("permission.checked", step, role=self.role, required=list(step.required_permissions))

    def _check_expressions(self, step: Step, group: str, expressions: tuple[str, ...]) -> bool:
        for index, expression in enumerate(expressions, 1):
            key = f"{step.id}:{group}:{index}"
            passed = self.check_results.get(key, True)
            self._event(f"{group}.checked", step, expression=expression, passed=passed)
            if not passed:
                return False
        return True

    def _run_action(self, step: Step) -> None:
        attempts = step.retry_policy.attempts
        outcomes = self.adapter_outcomes.get(step.id, [])
        self._event("step.started", step, action=step.action)
        next_delay = step.retry_policy.backoff_ms
        for attempt in range(1, attempts + 1):
            outcome: str | bool = outcomes[attempt - 1] if attempt <= len(outcomes) else "success"
            succeeded = outcome is True or (isinstance(outcome, str) and outcome.lower() in {"success", "ok", "succeed"})
            self._event("adapter.result", step, attempt=attempt, outcome="success" if succeeded else "failure")
            if succeeded:
                self._event("step.succeeded", step, attempts=attempt)
                return
            if attempt < attempts:
                delay = min(next_delay, step.retry_policy.max_backoff_ms)
                self._event("retry.scheduled", step, failed_attempt=attempt, next_attempt=attempt + 1, backoff_ms=delay)
                scaled = delay * step.retry_policy.factor
                next_delay = step.retry_policy.max_backoff_ms if not math.isfinite(scaled) or scaled >= step.retry_policy.max_backoff_ms else int(scaled)
        self._event("step.failed", step, attempts=attempts)
        raise _Stop("failed", step.id, "SOPC-RUN-STEP-FAILED", f"simulated action failed after {attempts} attempt(s)")

    def _checkpoint(self, step: Step) -> str | None:
        self._event("checkpoint.waiting", step, human=bool(step.checkpoint_config and step.checkpoint_config.human))
        supplied = self.checkpoint_decisions.get(step.id)
        if isinstance(supplied, list):
            supplied = supplied.pop(0) if supplied else None
        if supplied is None and self.checkpoint_handler is not None:
            supplied = self.checkpoint_handler(step)
        if supplied is None:
            return None
        if isinstance(supplied, str):
            decision, reason = supplied.lower(), ""
        elif isinstance(supplied, dict):
            decision = str(supplied.get("decision", "")).lower()
            reason = str(supplied.get("reason", ""))
        else:
            decision, reason = "", ""
        if decision not in {"approve", "reject", "edit"}:
            raise _Stop("failed", step.id, "SOPC-RUN-CHECKPOINT-DECISION", "decision must be approve, reject, or edit")
        if decision in {"reject", "edit"} and not reason.strip():
            raise _Stop("failed", step.id, "SOPC-RUN-CHECKPOINT-REASON", f"{decision} requires a reason")
        self._event("checkpoint.decided", step, decision=decision, reason=reason)
        if decision == "reject":
            target = step.checkpoint_config.on_reject if step.checkpoint_config else None
            if not target:
                raise _Stop("rejected", step.id, "SOPC-RUN-CHECKPOINT-REJECTED", reason)
            self.completed.append(step.id)
            return target
        if decision == "edit":
            target = (step.checkpoint_config.on_edit if step.checkpoint_config else None) or step.next_step or "END"
            self._event("checkpoint.edited", step, reason=reason, target=target)
            self.completed.append(step.id)
            return target
        self.completed.append(step.id)
        return step.next_step or "END"


def execute(plan: Plan, role: str = "operator", **kwargs: Any) -> ExecutionResult:
    return SimulatedExecutor(plan, role, **kwargs).run()
