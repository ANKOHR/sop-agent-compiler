# SOP to Agent Compiler

SOPC compiles procedures written in its documented SOPC Markdown grammar into a versioned JSON intermediate representation. It checks the plan with named static rules, can generate pytest contract tests, and runs plans against deterministic simulated adapters with an audit event log.

## Quickstart

Python 3.10 or newer is required. The project has no runtime dependencies. Install the CLI and test extra from the repository root:

```powershell
python -m pip install -e '.[test]'
sopc fixtures --out .\examples
sopc compile .\examples\refund_approval.md --out .\refund.plan.json --graph .\refund.svg --tests .\test_refund_plan.py
sopc verify .\refund.plan.json
```

Run a fully approved simulation by creating `decisions.json`:

```json
{
  "manager_approval": "approve",
  "receipt_approval": "approve"
}
```

Then run and render the plan:

```powershell
sopc run .\refund.plan.json --simulated --role operator --decisions .\decisions.json --events-out .\audit.json
sopc graph .\refund.plan.json --out .\refund.svg
pytest .\test_refund_plan.py
```

For an interactive simulated run, use `--interactive`. At each checkpoint, enter `approve`, `reject`, or `edit`; reject and edit require a reason. Without a supplied decision or interactive prompt, execution returns `paused` at the checkpoint and includes its event log. Simulation never calls external services. A simulated action succeeds by default. Use `--outcomes` to supply arrays such as `{"issue_refund": ["failure", "failure", "success"]}`. Decision expressions are not evaluated by an expression engine; pass explicit boolean results with `--conditions`, keyed by the exact condition text. Precondition and postcondition expressions are recorded and pass by default; `--checks` can override them with keys such as `validate_request:preconditions:1`.

`python -m sopc --help` lists all commands. `sopc fixtures --out <dir>` copies the synthetic fixture SOPs.

## SOP format reference

The parser accepts only the explicit document grammar in [docs/SOP-FORMAT.md](docs/SOP-FORMAT.md). A document has a title, owner, trigger, role grants, then ordered typed steps. Every diagnostic identifies the input file, source line, and grammar rule. Blank lines are ignored. Free-form Markdown sections, arbitrary prose, and unrecognized fields are rejected.

## Architecture

```text
SOPC Markdown source
        |
        v
Grammar parser --------------------> file:line:rule diagnostics
        |
        v
Typed Plan IR, schema 1.0 ----------> deterministic JSON
        |
        +----> Static verifier ------> named rule violations
        |
        +----> Test generator -------> pytest contract module
        |
        +----> SVG renderer ---------> deterministic state graph
        |
        +----> Simulated executor ---> state transitions + audit events
```

The parser and output serializers use stable ordering and no random values. There is no random seed because the implementation uses no random number generator. Retry backoff is represented in the event log as a simulated delay and does not sleep or call a real adapter.

## HONESTY BOUNDARY

SOPC performs deterministic grammar-based compilation of SOP documents written in the documented SOPC format. It does not understand arbitrary natural language and does not infer procedure structure from free-form prose. It uses no language model or machine learning. A source must declare its steps, metadata, permissions, and control-flow targets using the supported syntax. The simulator uses explicit supplied results for decisions and never connects to real tools.

## Verifier rule catalogue

Every violation includes a stable code, step id, and rule reference. `sopc verify` runs every applicable rule and reports all violations in one pass.

| Code | Rule reference | Check |
| --- | --- | --- |
| `SOPC101` | `UNREACHABLE_STEP` | Every declared step can be reached from the first step by following its declared control-flow edges. |
| `SOPC102` | `DECISION_NO_CONDITION` | A decision step has a non-empty `Condition`. Its true and false branch targets are declared in the SOP grammar. |
| `SOPC103` | `CONSEQUENTIAL_ACTION_REQUIRES_HUMAN_CHECKPOINT` | A payment, external send, or data deletion action has a human checkpoint that dominates it, so every path to the action passes the checkpoint. The parser uses `Consequence:` labels and a conservative list of action words as detectors. |
| `SOPC104` | `PERMISSION_NOT_GRANTED` | Each permission required by a step appears in at least one declared role grant. Runtime checks the selected role's grant before each step starts. |
| `SOPC105` | `CONTRADICTORY_RETRY_POLICY` | Attempts are positive, backoff values are non-negative and ordered, and the retry factor is finite and at least one. |
| `SOPC106` | `UNKNOWN_STEP_REFERENCE` | Every control-flow target names a declared step or `END`. |
| `SOPC107` | `CHECKPOINT_MUST_BE_HUMAN` | A checkpoint step must declare `Human: true`. |

Malformed versioned JSON is rejected by the named `PLAN-*` schema rules before static verification.

## Fixture catalogue

All examples are explicitly synthetic and fictional.

| Fixture | Expected result |
| --- | --- |
| `employee_onboarding.md` | Clean plan with a parallel device/profile setup. |
| `refund_approval.md` | Clean plan with human approval before the payment and external receipt. |
| `broken_payment_missing_checkpoint.md` | `SOPC103` for a payment action without prior human approval. |
| `broken_unreachable_permission_gap.md` | `SOPC101` and `SOPC104` on the unreachable archive action. |
| `malformed_timeout.md` | Parse error with file, line, and `SOP-TIMEOUT` rule. |
| `malformed_missing_next.md` | Parse error with file, line, and `SOP-NEXT-REQUIRED` rule. |

## Commands

| Command | Purpose |
| --- | --- |
| `sopc fixtures --out DIR` | Copy the synthetic SOP examples. |
| `sopc compile FILE [--out PLAN] [--graph SVG] [--tests PY]` | Parse a grammar document and serialize the typed IR; optional test generation also runs verification. |
| `sopc verify PLAN` | Load the versioned schema and run the static checks. |
| `sopc generate-tests PLAN --out PY` | Generate a portable pytest contract suite for a verified plan. |
| `sopc run PLAN --simulated` | Walk the plan with permission checks, retries, checkpoints, and an ordered event log. |
| `sopc graph PLAN --out SVG` | Render the deterministic SVG state graph with retry and error branches. |

The compiler is an offline local tool. No command publishes files or contacts a public service.
