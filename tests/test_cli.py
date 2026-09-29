import json
import subprocess
import sys

from sopc.cli import main
from sopc.model import Plan
from sopc.parser import parse_file


def test_cli_fixtures_compile_verify_run_graph_and_test_generation(tmp_path, fixture_dir, capsys):
    package_fixtures = fixture_dir.parent / "sopc" / "fixtures"
    assert {path.name: path.read_bytes() for path in fixture_dir.glob("*.md")} == {
        path.name: path.read_bytes() for path in package_fixtures.glob("*.md")
    }
    out_fixtures = tmp_path / "fixtures-out"
    assert main(["fixtures", "--out", str(out_fixtures)]) == 0
    assert (out_fixtures / "refund_approval.md").exists()
    capsys.readouterr()

    sop_path = out_fixtures / "refund_approval.md"
    plan_path = tmp_path / "refund.json"
    graph_path = tmp_path / "refund.svg"
    test_path = tmp_path / "test_generated_refund.py"
    assert main(["compile", str(sop_path), "--out", str(plan_path), "--graph", str(graph_path), "--tests", str(test_path)]) == 0
    assert plan_path.exists() and graph_path.exists() and test_path.exists()
    capsys.readouterr()

    assert main(["verify", str(plan_path)]) == 0
    assert "all rules passed" in capsys.readouterr().out

    decisions_path = tmp_path / "decisions.json"
    decisions_path.write_text(json.dumps({"manager_approval": "approve", "receipt_approval": "approve"}), encoding="utf-8")
    events_path = tmp_path / "events.json"
    assert main(["run", str(plan_path), "--simulated", "--decisions", str(decisions_path), "--events-out", str(events_path)]) == 0
    run = json.loads(capsys.readouterr().out)
    assert run["status"] == "completed"
    assert json.loads(events_path.read_text(encoding="utf-8"))["events"]

    graph_command_path = tmp_path / "graph-command.svg"
    assert main(["graph", str(plan_path), "--out", str(graph_command_path)]) == 0
    capsys.readouterr()
    assert graph_path.read_bytes() == graph_command_path.read_bytes()

    generated_path = tmp_path / "test_generated_separate.py"
    assert main(["generate-tests", str(plan_path), "--out", str(generated_path)]) == 0
    capsys.readouterr()
    compile(generated_path.read_text(encoding="utf-8"), str(generated_path), "exec")
    assert "test_generated_plan_completes_in_simulation" in generated_path.read_text(encoding="utf-8")
    generated_run = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(generated_path)],
        cwd=str(fixture_dir.parent), capture_output=True, text=True, check=False,
    )
    assert generated_run.returncode == 0, generated_run.stdout + generated_run.stderr


def test_cli_honesty_boundary_is_in_help(capsys):
    try:
        main(["--help"])
    except SystemExit as exc:
        assert exc.code == 0
    output = capsys.readouterr().out
    assert "does not understand arbitrary natural language" in " ".join(output.split())
    assert "generate-tests" in output


def test_cli_parse_error_includes_source_location(tmp_path, capsys):
    malformed = tmp_path / "invalid.md"
    malformed.write_text("SOP: Bad\nOwner: QA\nTrigger: Test\nRoles:\nSteps:\nno step\n", encoding="utf-8")
    assert main(["compile", str(malformed)]) == 2
    error = capsys.readouterr().err
    assert "invalid.md:6: SOP-STEP-HEADER" in error


def test_cli_run_pauses_when_checkpoint_decision_is_missing(tmp_path, fixture_dir, capsys):
    plan_path = tmp_path / "refund.json"
    parse_file(fixture_dir / "refund_approval.md").write(path=plan_path)
    assert main(["run", str(plan_path), "--simulated"]) == 3
    result = json.loads(capsys.readouterr().out)
    assert result["status"] == "paused"
    assert result["paused_at"] == "manager_approval"
