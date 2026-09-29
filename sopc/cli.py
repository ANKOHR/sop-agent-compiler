"""Command line interface for SOPC."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sys
from typing import Any

from .errors import SOPCError, SOPParseError, VerificationError
from .executor import execute
from .generate import write_pytest
from .graph import write_svg
from .model import Plan
from .parser import parse_file
from .verify import verify

HONESTY = "SOPC compiles only SOP documents written in its documented grammar. It does not understand arbitrary natural language."


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sopc",
        description="Compile SOPC grammar documents into typed, verifiable state machines. " + HONESTY,
        epilog="Deterministic grammar-based compilation only. No natural-language understanding is performed.",
    )
    subs = parser.add_subparsers(dest="command", required=True)

    fixtures_parser = subs.add_parser("fixtures", help="copy synthetic example SOP documents", description=HONESTY)
    fixtures_parser.add_argument("--out", required=True, help="directory to receive the fixture SOPs")

    compile_parser = subs.add_parser("compile", help="compile one documented SOP source", description=HONESTY)
    compile_parser.add_argument("sop", help="SOP source in the documented SOPC grammar")
    compile_parser.add_argument("--out", help="write versioned plan JSON to this file; defaults to stdout")
    compile_parser.add_argument("--graph", help="also write a deterministic SVG graph to this file")
    compile_parser.add_argument("--tests", help="also generate a pytest contract suite at this path")

    tests_parser = subs.add_parser("generate-tests", help="generate pytest contract tests for a verified plan", description=HONESTY)
    tests_parser.add_argument("plan", help="versioned plan JSON")
    tests_parser.add_argument("--out", required=True, help="pytest module output file")

    verify_parser = subs.add_parser("verify", help="run all static verification rules", description=HONESTY)
    verify_parser.add_argument("plan", help="versioned plan JSON")

    run_parser = subs.add_parser("run", help="execute against simulated tool adapters", description=HONESTY)
    run_parser.add_argument("plan", help="versioned plan JSON")
    run_parser.add_argument("--simulated", action="store_true", required=True, help="required: use deterministic simulated adapters")
    run_parser.add_argument("--role", default="operator", help="role whose declared permissions are checked (default: operator)")
    run_parser.add_argument("--decisions", help="JSON mapping checkpoint step ids to decisions and reasons")
    run_parser.add_argument("--conditions", help="JSON mapping condition text to simulated boolean results")
    run_parser.add_argument("--outcomes", help="JSON mapping action step ids to arrays of success/failure results")
    run_parser.add_argument("--checks", help="JSON mapping step precondition/postcondition keys to booleans")
    run_parser.add_argument("--events-out", help="also save the complete run result and audit log to this file")
    run_parser.add_argument("--interactive", action="store_true", help="prompt for checkpoint decisions during this simulated run")

    graph_parser = subs.add_parser("graph", help="render a deterministic state machine SVG", description=HONESTY)
    graph_parser.add_argument("plan", help="versioned plan JSON")
    graph_parser.add_argument("--out", required=True, help="SVG output file")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "fixtures":
            return _fixtures(args.out)
        if args.command == "compile":
            plan = parse_file(args.sop)
            if args.out:
                plan.write(args.out)
                print(f"Compiled {args.sop} -> {args.out}")
            else:
                sys.stdout.write(plan.to_json())
            if args.graph:
                write_svg(plan, args.graph)
            if args.tests:
                verify(plan)
                write_pytest(plan, args.tests)
            return 0
        if args.command == "verify":
            plan = Plan.read(args.plan)
            violations = verify(plan, raise_on_error=False)
            if violations:
                for violation in violations:
                    print(str(violation), file=sys.stderr)
                return 2
            print(f"Verified {args.plan}: {len(plan.steps)} steps, all rules passed")
            return 0
        if args.command == "generate-tests":
            plan = Plan.read(args.plan)
            verify(plan)
            write_pytest(plan, args.out)
            print(f"Generated pytest contract suite: {args.out}")
            return 0
        if args.command == "run":
            plan = Plan.read(args.plan)
            result = execute(
                plan,
                role=args.role,
                checkpoint_decisions=_read_json_mapping(args.decisions),
                condition_results=_read_json_mapping(args.conditions),
                adapter_outcomes=_read_json_mapping(args.outcomes),
                check_results=_read_json_mapping(args.checks),
                checkpoint_handler=_prompt_checkpoint if args.interactive else None,
            )
            output = json.dumps(result.to_dict(), ensure_ascii=False, indent=2) + "\n"
            if args.events_out:
                Path(args.events_out).write_text(output, encoding="utf-8", newline="\n")
            sys.stdout.write(output)
            return 2 if result.status == "failed" else 3 if result.status == "paused" else 0
        if args.command == "graph":
            plan = Plan.read(args.plan)
            write_svg(plan, args.out)
            print(f"Rendered {args.plan} -> {args.out}")
            return 0
    except SOPParseError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except VerificationError as exc:
        for violation in exc.violations:
            print(str(violation), file=sys.stderr)
        return 2
    except SOPCError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"SOPC-IO: {exc}", file=sys.stderr)
        return 2
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"SOPC-INPUT: {exc}", file=sys.stderr)
        return 2
    return 0


def _read_json_mapping(filename: str | None) -> dict[str, Any]:
    if not filename:
        return {}
    value = json.loads(Path(filename).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{filename}: expected a JSON object")
    return value


def _fixtures(out: str) -> int:
    source = Path(__file__).resolve().parent.parent / "fixtures"
    if not source.exists():
        source = Path(__file__).resolve().parent / "fixtures"
    destination = Path(out)
    destination.mkdir(parents=True, exist_ok=True)
    files = sorted(source.glob("*.md"))
    for file in files:
        shutil.copyfile(file, destination / file.name)
    print(f"Copied {len(files)} synthetic SOP fixtures to {destination}")
    for file in files:
        print(f"  {file.name}")
    return 0


def _prompt_checkpoint(step: Any) -> dict[str, str]:
    while True:
        decision = input(f"Checkpoint {step.id}: approve, reject, or edit? ").strip().lower()
        if decision not in {"approve", "reject", "edit"}:
            print("Enter approve, reject, or edit.", file=sys.stderr)
            continue
        reason = input("Reason: ").strip() if decision in {"reject", "edit"} else ""
        if decision in {"reject", "edit"} and not reason:
            print("A reason is required for reject and edit.", file=sys.stderr)
            continue
        return {"decision": decision, "reason": reason}


if __name__ == "__main__":
    raise SystemExit(main())
