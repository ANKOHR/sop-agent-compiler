"""Parser for the small, explicit SOPC Markdown grammar."""

from __future__ import annotations

from pathlib import Path
import re

from .errors import SOPParseError
from .model import CheckpointConfig, Plan, RetryPolicy, Step

_STEP_HEADER = re.compile(r"^## ([a-z][a-z0-9_-]*) \[(action|decision|checkpoint|parallel)\]$")
_ROLE = re.compile(r"^- ([a-z][a-z0-9_-]*):(?: (.*))?$")
_ID = re.compile(r"^(?:[a-z][a-z0-9_-]*|END)$")
_DURATION = re.compile(r"^(\d+)(ms|s)$")
_RETRY = re.compile(r"^attempts=(\d+), backoff=(\d+(?:ms|s)), factor=(\d+(?:\.\d+)?), max=(\d+(?:ms|s))$")


def parse_file(path: str | Path) -> Plan:
    source = Path(path)
    return parse_text(source.read_text(encoding="utf-8"), filename=str(source))


def parse_text(text: str, filename: str = "<input>") -> Plan:
    lines = text.splitlines()
    rows = [(index, line.strip()) for index, line in enumerate(lines, 1) if line.strip()]
    if not rows:
        raise SOPParseError(filename, 1, "SOP-HEADER", "expected 'SOP: <title>'")

    cursor = 0

    def require(expected: str, rule: str) -> tuple[int, str]:
        nonlocal cursor
        if cursor >= len(rows):
            raise SOPParseError(filename, len(lines) + 1, rule, f"expected {expected}")
        row = rows[cursor]
        if not row[1].startswith(expected):
            raise SOPParseError(filename, row[0], rule, f"expected {expected}")
        cursor += 1
        return row

    line, header = require("SOP:", "SOP-HEADER")
    title = _value(header, "SOP", filename, line, "SOP-HEADER")
    owner_line, owner_row = require("Owner:", "SOP-OWNER")
    owner = _value(owner_row, "Owner", filename, owner_line, "SOP-OWNER")
    trigger_line, trigger_row = require("Trigger:", "SOP-TRIGGER")
    trigger = _value(trigger_row, "Trigger", filename, trigger_line, "SOP-TRIGGER")
    roles_line, roles_row = require("Roles:", "SOP-ROLES")
    if roles_row != "Roles:":
        raise SOPParseError(filename, roles_line, "SOP-ROLES", "write 'Roles:' on its own line")
    roles: dict[str, tuple[str, ...]] = {}
    while cursor < len(rows) and rows[cursor][1] != "Steps:":
        role_line, role_row = rows[cursor]
        match = _ROLE.fullmatch(role_row)
        if not match:
            raise SOPParseError(filename, role_line, "SOP-ROLE-DECLARATION", "expected '- role-name: permission.one, permission.two'")
        role = match.group(1)
        if role in roles:
            raise SOPParseError(filename, role_line, "SOP-ROLE-UNIQUE", f"duplicate role {role!r}")
        permissions = _csv(match.group(2) or "")
        roles[role] = tuple(permissions)
        cursor += 1
    steps_line, steps_row = require("Steps:", "SOP-STEPS")
    if steps_row != "Steps:":
        raise SOPParseError(filename, steps_line, "SOP-STEPS", "write 'Steps:' on its own line")

    raw_steps: list[tuple[int, str, str, dict[str, tuple[int, str]]]] = []
    declared_ids: set[str] = set()
    allowed_fields = {
        "Action", "Preconditions", "Postconditions", "Requires", "Retry", "Timeout",
        "Consequence", "Condition", "True", "False", "Next", "On reject", "On edit",
        "Human", "Branches", "Join",
    }
    while cursor < len(rows):
        step_line, step_header = rows[cursor]
        match = _STEP_HEADER.fullmatch(step_header)
        if not match:
            raise SOPParseError(filename, step_line, "SOP-STEP-HEADER", "expected '## step-id [action|decision|checkpoint|parallel]'")
        sid, kind = match.groups()
        if sid in declared_ids:
            raise SOPParseError(filename, step_line, "SOP-STEP-ID-UNIQUE", f"duplicate step id {sid!r}")
        declared_ids.add(sid)
        cursor += 1
        fields: dict[str, tuple[int, str]] = {}
        while cursor < len(rows) and not rows[cursor][1].startswith("## "):
            field_line, field_row = rows[cursor]
            if ":" not in field_row:
                raise SOPParseError(filename, field_line, "SOP-STEP-FIELD", "expected 'Field: value'")
            name, value = field_row.split(":", 1)
            name, value = name.strip(), value.strip()
            if name not in allowed_fields:
                raise SOPParseError(filename, field_line, "SOP-STEP-FIELD-NAME", f"unknown field {name!r}")
            if name in fields:
                raise SOPParseError(filename, field_line, "SOP-STEP-FIELD-UNIQUE", f"field {name!r} occurs more than once")
            if not value:
                raise SOPParseError(filename, field_line, f"SOP-{name.upper().replace(' ', '-')}", f"{name} must not be empty")
            fields[name] = (field_line, value)
            cursor += 1
        raw_steps.append((step_line, sid, kind, fields))
    if not raw_steps:
        raise SOPParseError(filename, steps_line, "SOP-STEPS-NONEMPTY", "declare at least one step")

    steps: list[Step] = []
    for step_line, sid, kind, fields in raw_steps:
        _check_kind_fields(filename, step_line, sid, kind, fields)
        common_retry = _retry_policy(fields.get("Retry"), filename, step_line)
        timeout = _duration(fields["Timeout"][1], filename, *fields["Timeout"], "SOP-TIMEOUT") if "Timeout" in fields else None
        preconditions = tuple(_semicolon(fields.get("Preconditions", (0, ""))[1]))
        postconditions = tuple(_semicolon(fields.get("Postconditions", (0, ""))[1]))
        permissions = tuple(_csv(fields.get("Requires", (0, ""))[1]))
        if kind == "action":
            steps.append(Step(
                id=sid, kind=kind, action=fields["Action"][1], preconditions=preconditions,
                postconditions=postconditions, required_permissions=permissions, retry_policy=common_retry,
                timeout_ms=timeout, next_step=_target(fields["Next"], filename, "SOP-NEXT"),
                consequence=fields.get("Consequence", (0, ""))[1].lower() or None,
            ))
        elif kind == "decision":
            steps.append(Step(
                id=sid, kind=kind, action="", preconditions=preconditions, postconditions=postconditions,
                required_permissions=permissions, retry_policy=common_retry, timeout_ms=timeout,
                condition=fields.get("Condition", (0, ""))[1] or None,
                true_step=_target(fields["True"], filename, "SOP-DECISION-TRUE"),
                false_step=_target(fields["False"], filename, "SOP-DECISION-FALSE"),
            ))
        elif kind == "checkpoint":
            human = fields.get("Human", (0, "true"))[1].lower()
            if human not in {"true", "false"}:
                field_line = fields["Human"][0]
                raise SOPParseError(filename, field_line, "SOP-CHECKPOINT-HUMAN", "Human must be true or false")
            steps.append(Step(
                id=sid, kind=kind, preconditions=preconditions, postconditions=postconditions,
                required_permissions=permissions, retry_policy=common_retry, timeout_ms=timeout,
                checkpoint_config=CheckpointConfig(
                    human=human == "true",
                    on_reject=_target(fields["On reject"], filename, "SOP-CHECKPOINT-REJECT") if "On reject" in fields else None,
                    on_edit=_target(fields["On edit"], filename, "SOP-CHECKPOINT-EDIT") if "On edit" in fields else None,
                ),
                next_step=_target(fields["Next"], filename, "SOP-NEXT"),
            ))
        else:
            branches = _csv(fields["Branches"][1])
            if len(branches) < 2:
                field_line = fields["Branches"][0]
                raise SOPParseError(filename, field_line, "SOP-PARALLEL-BRANCHES", "parallel steps require at least two branch ids")
            steps.append(Step(
                id=sid, kind=kind, preconditions=preconditions, postconditions=postconditions,
                required_permissions=permissions, retry_policy=common_retry, timeout_ms=timeout,
                branches=tuple(_target((fields["Branches"][0], item), filename, "SOP-PARALLEL-BRANCHES") for item in branches),
                join_step=_target(fields["Join"], filename, "SOP-PARALLEL-JOIN"),
            ))
    return Plan(title=title, owner=owner, trigger=trigger, roles=roles, steps=tuple(steps))


def _value(row: str, field: str, filename: str, line: int, rule: str) -> str:
    value = row[len(field) + 1:].strip()
    if not value:
        raise SOPParseError(filename, line, rule, f"{field} must not be empty")
    return value


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _semicolon(value: str) -> list[str]:
    return [item.strip() for item in value.split(";") if item.strip()]


def _target(field: tuple[int, str], filename: str, rule: str) -> str:
    line, value = field
    if not _ID.fullmatch(value):
        raise SOPParseError(filename, line, rule, f"invalid target {value!r}; use a step id or END")
    return value


def _duration(value: str, filename: str, line: int, raw: str, rule: str) -> int:
    match = _DURATION.fullmatch(value)
    if not match:
        raise SOPParseError(filename, line, rule, f"invalid duration {raw!r}; use integer milliseconds or seconds, such as 250ms or 3s")
    amount, unit = match.groups()
    return int(amount) * (1000 if unit == "s" else 1)


def _retry_policy(field: tuple[int, str] | None, filename: str, fallback_line: int) -> RetryPolicy:
    if field is None:
        return RetryPolicy()
    line, value = field
    match = _RETRY.fullmatch(value)
    if not match:
        raise SOPParseError(filename, line, "SOP-RETRY", "expected 'attempts=N, backoff=Nms|Ns, factor=N, max=Nms|Ns'")
    attempts, backoff, factor, maximum = match.groups()
    return RetryPolicy(
        attempts=int(attempts),
        backoff_ms=_duration(backoff, filename, line, backoff, "SOP-RETRY-BACKOFF"),
        factor=float(factor),
        max_backoff_ms=_duration(maximum, filename, line, maximum, "SOP-RETRY-MAX"),
    )


def _check_kind_fields(filename: str, line: int, sid: str, kind: str, fields: dict[str, tuple[int, str]]) -> None:
    if kind == "action" and "Action" not in fields:
        raise SOPParseError(filename, line, "SOP-ACTION-REQUIRED", f"action step {sid!r} requires Action")
    if kind == "action" and "Next" not in fields:
        raise SOPParseError(filename, line, "SOP-NEXT-REQUIRED", f"action step {sid!r} requires Next")
    if kind == "decision":
        for key in ("True", "False"):
            if key not in fields:
                raise SOPParseError(filename, line, "SOP-DECISION-BRANCHES", f"decision step {sid!r} requires {key}")
    if kind == "checkpoint" and "Next" not in fields:
        raise SOPParseError(filename, line, "SOP-NEXT-REQUIRED", f"checkpoint step {sid!r} requires Next")
    if kind == "parallel":
        for key in ("Branches", "Join"):
            if key not in fields:
                raise SOPParseError(filename, line, "SOP-PARALLEL-SHAPE", f"parallel step {sid!r} requires {key}")
    allowed = {
        "action": {"Action", "Preconditions", "Postconditions", "Requires", "Retry", "Timeout", "Consequence", "Next"},
        "decision": {"Preconditions", "Postconditions", "Requires", "Retry", "Timeout", "Condition", "True", "False"},
        "checkpoint": {"Preconditions", "Postconditions", "Requires", "Retry", "Timeout", "Human", "Next", "On reject", "On edit"},
        "parallel": {"Preconditions", "Postconditions", "Requires", "Retry", "Timeout", "Branches", "Join"},
    }[kind]
    invalid = set(fields) - allowed
    if invalid:
        key = sorted(invalid)[0]
        raise SOPParseError(filename, fields[key][0], "SOP-FIELD-KIND", f"field {key!r} is not valid for {kind} steps")
