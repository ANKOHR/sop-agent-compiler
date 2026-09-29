"""Typed, versioned intermediate representation for compiled procedures."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import re
from typing import Any

from .errors import PlanSchemaError

SCHEMA_VERSION = "1.0"
STEP_KINDS = {"action", "decision", "checkpoint", "parallel"}


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 1
    backoff_ms: int = 0
    factor: float = 2.0
    max_backoff_ms: int = 0


@dataclass(frozen=True)
class CheckpointConfig:
    human: bool = True
    on_reject: str | None = None
    on_edit: str | None = None


@dataclass(frozen=True)
class Step:
    id: str
    kind: str
    action: str = ""
    preconditions: tuple[str, ...] = ()
    postconditions: tuple[str, ...] = ()
    required_permissions: tuple[str, ...] = ()
    retry_policy: RetryPolicy = field(default_factory=RetryPolicy)
    timeout_ms: int | None = None
    checkpoint_config: CheckpointConfig | None = None
    condition: str | None = None
    next_step: str | None = None
    true_step: str | None = None
    false_step: str | None = None
    branches: tuple[str, ...] = ()
    join_step: str | None = None
    consequence: str | None = None

    def outgoing(self) -> tuple[str, ...]:
        values: list[str] = []
        if self.kind == "decision":
            values.extend([self.true_step, self.false_step])
        elif self.kind == "parallel":
            values.extend(self.branches)
        else:
            values.append(self.next_step)
            if self.kind == "checkpoint" and self.checkpoint_config:
                values.extend([self.checkpoint_config.on_reject, self.checkpoint_config.on_edit])
        return tuple(value for value in values if value and value != "END")


@dataclass(frozen=True)
class Plan:
    title: str
    owner: str
    trigger: str
    roles: dict[str, tuple[str, ...]]
    steps: tuple[Step, ...]
    schema_version: str = SCHEMA_VERSION

    @property
    def entry_step(self) -> str | None:
        return self.steps[0].id if self.steps else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "title": self.title,
            "owner": self.owner,
            "trigger": self.trigger,
            "roles": {name: list(perms) for name, perms in self.roles.items()},
            "entry_step": self.entry_step,
            "steps": [step_to_dict(step) for step in self.steps],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n"

    def write(self, path: str | Path) -> None:
        Path(path).write_text(self.to_json(), encoding="utf-8", newline="\n")

    @classmethod
    def from_dict(cls, value: Any) -> "Plan":
        root = _object(value, "PLAN-ROOT")
        _keys(root, {"schema_version", "title", "owner", "trigger", "roles", "entry_step", "steps"}, "PLAN-ROOT")
        version = _string(root.get("schema_version"), "PLAN-VERSION")
        if version != SCHEMA_VERSION:
            raise PlanSchemaError("PLAN-VERSION", f"unsupported schema version {version!r}; expected {SCHEMA_VERSION}")
        title = _string(root.get("title"), "PLAN-TITLE")
        owner = _string(root.get("owner"), "PLAN-OWNER")
        trigger = _string(root.get("trigger"), "PLAN-TRIGGER")
        roles_raw = _object(root.get("roles"), "PLAN-ROLES")
        roles: dict[str, tuple[str, ...]] = {}
        for role, permissions in roles_raw.items():
            if not isinstance(role, str) or not role.strip():
                raise PlanSchemaError("PLAN-ROLE-NAME", "role names must be non-empty strings")
            roles[role] = tuple(_string_list(permissions, f"PLAN-ROLE-{role.upper()}"))
        steps_raw = root.get("steps")
        if not isinstance(steps_raw, list) or not steps_raw:
            raise PlanSchemaError("PLAN-STEPS", "steps must be a non-empty array")
        steps = tuple(_step_from_dict(item, i) for i, item in enumerate(steps_raw, 1))
        ids = [step.id for step in steps]
        if len(ids) != len(set(ids)):
            raise PlanSchemaError("PLAN-STEP-ID-UNIQUE", "step ids must be unique")
        entry = root.get("entry_step")
        expected_entry = steps[0].id
        if entry != expected_entry:
            raise PlanSchemaError("PLAN-ENTRY", f"entry_step must be the first declared step {expected_entry!r}")
        return cls(title=title, owner=owner, trigger=trigger, roles=roles, steps=steps, schema_version=version)

    @classmethod
    def read(cls, path: str | Path) -> "Plan":
        filename = str(path)
        try:
            value = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise PlanSchemaError("PLAN-JSON", f"{filename}: {exc}") from exc
        return cls.from_dict(value)


def step_to_dict(step: Step) -> dict[str, Any]:
    return {
        "id": step.id,
        "kind": step.kind,
        "action": step.action,
        "preconditions": list(step.preconditions),
        "postconditions": list(step.postconditions),
        "required_permissions": list(step.required_permissions),
        "retry_policy": asdict(step.retry_policy),
        "timeout_ms": step.timeout_ms,
        "checkpoint_config": asdict(step.checkpoint_config) if step.checkpoint_config else None,
        "condition": step.condition,
        "next_step": step.next_step,
        "true_step": step.true_step,
        "false_step": step.false_step,
        "branches": list(step.branches),
        "join_step": step.join_step,
        "consequence": step.consequence,
    }


def _object(value: Any, rule: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PlanSchemaError(rule, "expected an object")
    return value


def _keys(value: dict[str, Any], allowed: set[str], rule: str) -> None:
    missing = allowed - value.keys()
    extra = value.keys() - allowed
    if missing:
        raise PlanSchemaError(rule, f"missing fields: {', '.join(sorted(missing))}")
    if extra:
        raise PlanSchemaError(rule, f"unknown fields: {', '.join(sorted(extra))}")


def _string(value: Any, rule: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise PlanSchemaError(rule, "expected a non-empty string")
    return value


def _nullable_string(value: Any, rule: str) -> str | None:
    return None if value is None else _string(value, rule)


def _string_list(value: Any, rule: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        raise PlanSchemaError(rule, "expected an array of non-empty strings")
    return value


def _integer(value: Any, rule: str, nullable: bool = False) -> int | None:
    if nullable and value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise PlanSchemaError(rule, "expected an integer" + (" or null" if nullable else ""))
    return value


def _step_from_dict(value: Any, index: int) -> Step:
    prefix = f"PLAN-STEP-{index}"
    raw = _object(value, prefix)
    expected = {
        "id", "kind", "action", "preconditions", "postconditions", "required_permissions",
        "retry_policy", "timeout_ms", "checkpoint_config", "condition", "next_step",
        "true_step", "false_step", "branches", "join_step", "consequence",
    }
    _keys(raw, expected, prefix)
    sid = _string(raw.get("id"), f"{prefix}-ID")
    if not re.fullmatch(r"[a-z][a-z0-9_-]*", sid):
        raise PlanSchemaError(f"{prefix}-ID", "step id must match [a-z][a-z0-9_-]*")
    kind = _string(raw.get("kind"), f"{prefix}-KIND")
    if kind not in STEP_KINDS:
        raise PlanSchemaError(f"{prefix}-KIND", f"unsupported step kind {kind!r}")
    retry_raw = _object(raw.get("retry_policy"), f"{prefix}-RETRY")
    _keys(retry_raw, {"attempts", "backoff_ms", "factor", "max_backoff_ms"}, f"{prefix}-RETRY")
    factor = retry_raw.get("factor")
    if isinstance(factor, bool) or not isinstance(factor, (int, float)):
        raise PlanSchemaError(f"{prefix}-RETRY-FACTOR", "expected a number")
    checkpoint = None
    check_raw = raw.get("checkpoint_config")
    if check_raw is not None:
        check_raw = _object(check_raw, f"{prefix}-CHECKPOINT")
        _keys(check_raw, {"human", "on_reject", "on_edit"}, f"{prefix}-CHECKPOINT")
        if not isinstance(check_raw.get("human"), bool):
            raise PlanSchemaError(f"{prefix}-CHECKPOINT-HUMAN", "expected a boolean")
        checkpoint = CheckpointConfig(
            human=check_raw["human"],
            on_reject=_nullable_string(check_raw.get("on_reject"), f"{prefix}-REJECT"),
            on_edit=_nullable_string(check_raw.get("on_edit"), f"{prefix}-EDIT"),
        )
    timeout = _integer(raw.get("timeout_ms"), f"{prefix}-TIMEOUT", nullable=True)
    step = Step(
        id=sid,
        kind=kind,
        action=_string(raw.get("action"), f"{prefix}-ACTION", allow_empty=True),
        preconditions=tuple(_string_list(raw.get("preconditions"), f"{prefix}-PRECONDITIONS")),
        postconditions=tuple(_string_list(raw.get("postconditions"), f"{prefix}-POSTCONDITIONS")),
        required_permissions=tuple(_string_list(raw.get("required_permissions"), f"{prefix}-PERMISSIONS")),
        retry_policy=RetryPolicy(
            attempts=_integer(retry_raw.get("attempts"), f"{prefix}-RETRY-ATTEMPTS"),
            backoff_ms=_integer(retry_raw.get("backoff_ms"), f"{prefix}-RETRY-BACKOFF"),
            factor=float(factor),
            max_backoff_ms=_integer(retry_raw.get("max_backoff_ms"), f"{prefix}-RETRY-MAX"),
        ),
        timeout_ms=timeout,
        checkpoint_config=checkpoint,
        condition=_nullable_string(raw.get("condition"), f"{prefix}-CONDITION"),
        next_step=_nullable_string(raw.get("next_step"), f"{prefix}-NEXT"),
        true_step=_nullable_string(raw.get("true_step"), f"{prefix}-TRUE"),
        false_step=_nullable_string(raw.get("false_step"), f"{prefix}-FALSE"),
        branches=tuple(_string_list(raw.get("branches"), f"{prefix}-BRANCHES")),
        join_step=_nullable_string(raw.get("join_step"), f"{prefix}-JOIN"),
        consequence=_nullable_string(raw.get("consequence"), f"{prefix}-CONSEQUENCE"),
    )
    if step.timeout_ms is not None and step.timeout_ms < 0:
        raise PlanSchemaError(f"{prefix}-TIMEOUT", "timeout_ms must be non-negative")
    if kind == "action" and (not step.action.strip() or not step.next_step):
        raise PlanSchemaError(f"{prefix}-ACTION-SHAPE", "action steps require a non-empty action and next_step")
    if kind == "decision" and (not step.true_step or not step.false_step):
        raise PlanSchemaError(f"{prefix}-DECISION-SHAPE", "decision steps require true_step and false_step")
    if kind == "checkpoint" and (not step.next_step or step.checkpoint_config is None):
        raise PlanSchemaError(f"{prefix}-CHECKPOINT-SHAPE", "checkpoint steps require next_step and checkpoint_config")
    if kind == "parallel" and (len(step.branches) < 2 or not step.join_step):
        raise PlanSchemaError(f"{prefix}-PARALLEL-SHAPE", "parallel steps require at least two branches and join_step")
    if kind == "action" and any((step.checkpoint_config is not None, step.condition is not None, step.true_step is not None,
                                  step.false_step is not None, bool(step.branches), step.join_step is not None)):
        raise PlanSchemaError(f"{prefix}-ACTION-SHAPE", "action steps cannot carry decision, checkpoint, or parallel fields")
    if kind == "decision" and any((step.action, step.checkpoint_config is not None, step.next_step is not None,
                                    bool(step.branches), step.join_step is not None, step.consequence is not None)):
        raise PlanSchemaError(f"{prefix}-DECISION-SHAPE", "decision steps cannot carry action, checkpoint, or parallel fields")
    if kind == "checkpoint" and any((step.action, step.condition is not None, step.true_step is not None,
                                      step.false_step is not None, bool(step.branches), step.join_step is not None,
                                      step.consequence is not None)):
        raise PlanSchemaError(f"{prefix}-CHECKPOINT-SHAPE", "checkpoint steps cannot carry action, decision, or parallel fields")
    if kind == "parallel" and any((step.action, step.checkpoint_config is not None, step.condition is not None,
                                    step.next_step is not None, step.true_step is not None, step.false_step is not None,
                                    step.consequence is not None)):
        raise PlanSchemaError(f"{prefix}-PARALLEL-SHAPE", "parallel steps cannot carry action, decision, or checkpoint fields")
    return step
