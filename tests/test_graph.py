from sopc.graph import render_svg
from sopc.parser import parse_file


def test_graph_contains_checkpoint_and_error_branches(fixture_dir):
    plan = parse_file(fixture_dir / "refund_approval.md")
    svg = render_svg(plan)
    assert "manager_approval [checkpoint]" in svg
    assert "human approval" in svg
    assert "reject" in svg
    assert "error after retries" in svg
    assert "ERROR / retries exhausted" in svg
    assert "retry, 200ms backoff" in svg


def test_graph_bytes_are_deterministic(fixture_dir):
    plan = parse_file(fixture_dir / "refund_approval.md")
    assert render_svg(plan).encode("utf-8") == render_svg(plan).encode("utf-8")
