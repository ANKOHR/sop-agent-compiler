from sopc.graph import render_svg
from sopc.parser import parse_file


def test_compilation_and_graph_are_byte_identical_across_repeated_runs(fixture_dir):
    path = fixture_dir / "refund_approval.md"
    first = parse_file(path)
    second = parse_file(path)
    assert first.to_json().encode("utf-8") == second.to_json().encode("utf-8")
    assert render_svg(first).encode("utf-8") == render_svg(second).encode("utf-8")
