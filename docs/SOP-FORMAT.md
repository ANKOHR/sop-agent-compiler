# SOPC Markdown grammar, version 1

SOPC parses a deliberately small, line-oriented format. It does not attempt to infer meaning from arbitrary natural language. The words after fields such as `Action`, `Condition`, and `Preconditions` are retained as data. Control flow, permission declarations, and retry behavior must use the exact field syntax below.

## Document shape

```text
SOP: <non-empty title>
Owner: <non-empty owner>
Trigger: <non-empty trigger>
Roles:
- <role-id>: <permission>, <permission>
Steps:
## <step-id> [<kind>]
<field>: <value>
```

Use one or more role declarations and one or more step blocks. Role and step ids match `[a-z][a-z0-9_-]*`. The first declared step is the entry step. `END` is a special control-flow target. Blank lines are ignored. Fields are case-sensitive and each field can occur at most once per step. Unknown fields fail parsing.

## Common step metadata

These fields may appear where appropriate for a step kind:

| Field | Meaning |
| --- | --- |
| `Preconditions:` | Optional semicolon-separated expressions recorded and checked by the simulator. |
| `Postconditions:` | Optional semicolon-separated expressions recorded and checked by the simulator. |
| `Requires:` | Optional comma-separated permission names. |
| `Retry:` | Optional policy in the exact form `attempts=3, backoff=200ms, factor=2, max=2s`. Defaults to one attempt and zero backoff. |
| `Timeout:` | Optional non-negative integer duration such as `250ms` or `8s`, stored in milliseconds. |

The simulated executor records precondition and postcondition checks. Since SOPC does not interpret the text of those expressions, checks pass by default and can be overridden by explicit `--checks` simulation inputs. `Condition` on a decision step is similarly an opaque expression string whose result must be provided to the simulator.

## Step kinds

### Action

```text
## charge_customer [action]
Action: Charge the approved customer payment.
Consequence: payment
Requires: payments.charge
Next: END
```

`Action` and `Next` are required. `Consequence` is optional; recognized labels include `payment`, `external_send`, and `data_deletion`. SOPC also checks a small conservative vocabulary in action text for these categories.

### Decision

```text
## amount_check [decision]
Condition: refund.amount <= 100
True: auto_approve
False: manager_review
```

`True` and `False` targets are required. `Condition` is required by the verifier. To run a decision in simulation, provide its exact condition text and a boolean using `--conditions`.

### Checkpoint

```text
## manager_approval [checkpoint]
Human: true
Next: issue_refund
On reject: record_rejection
On edit: revise_request
```

`Next` is required. `Human` defaults to `true`, but explicit `Human: false` fails verification. `On reject` and `On edit` are optional routes. Without a rejection route, rejection stops the run. An edit requires a reason and routes to `On edit`, or to `Next` if no edit route is declared.

### Parallel

```text
## prepare [parallel]
Branches: create_profile, provision_device
Join: notify_employee
```

At least two branch ids and a join id are required. The simulator walks branches in declaration order, stopping each branch before it executes the join step, then continues at the join.

## Retry simulation

Retries are deterministic. `attempts` counts the first call. A failed attempt schedules an event containing `backoff_ms`; the executor does not sleep. The next simulated adapter result is consumed from the array supplied for that step. Once the supplied sequence is exhausted, later attempts succeed by default. No random numbers or random seed are used.

## Error format

Parser errors use `filename:line: RULE: message`, for example:

```text
fixtures/malformed_timeout.md:10: SOP-TIMEOUT: invalid duration 'next week'; use integer milliseconds or seconds, such as 250ms or 3s
```

Plan JSON is schema version `1.0`. Unknown fields, missing fields, wrong JSON types, duplicate ids, and unsupported versions have named `PLAN-*` schema errors.
