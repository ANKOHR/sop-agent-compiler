from pathlib import Path

import pytest

from sopc.errors import SOPParseError
from sopc.parser import parse_file, parse_text


def test_fixture_sops_parse_to_typed_ir(fixture_dir):
    onboarding = parse_file(fixture_dir / "employee_onboarding.md")
    assert onboarding.title == "Synthetic Employee Onboarding"
    assert onboarding.entry_step == "validate_request"
    assert [step.kind for step in onboarding.steps] == ["action", "parallel", "action", "action", "action"]
    parallel = onboarding.steps[1]
    assert parallel.branches == ("create_profile", "provision_device")
    assert parallel.join_step == "welcome_employee"
    assert onboarding.steps[0].preconditions == ("hiring record exists", "start date is present")
    assert onboarding.steps[0].required_permissions == ("employee.read",)

    refund = parse_file(fixture_dir / "refund_approval.md")
    payment = next(step for step in refund.steps if step.id == "issue_refund")
    assert payment.consequence == "payment"
    assert payment.retry_policy.attempts == 3
    assert payment.retry_policy.backoff_ms == 200
    assert payment.retry_policy.max_backoff_ms == 1000
    assert next(step for step in refund.steps if step.id == "manager_approval").checkpoint_config.human

    broken_payment = parse_file(fixture_dir / "broken_payment_missing_checkpoint.md")
    assert broken_payment.steps[0].consequence == "payment"
    broken_graph = parse_file(fixture_dir / "broken_unreachable_permission_gap.md")
    assert [step.id for step in broken_graph.steps] == ["read_request", "unreachable_archive"]


def test_parser_supports_decisions_and_optional_condition_for_verifier():
    plan = parse_text("""SOP: Decision sample
Owner: QA
Trigger: A sample request arrives.
Roles:
- operator: sample.read
Steps:
## choose [decision]
True: accept
False: reject
## accept [action]
Action: Accept the sample.
Next: END
## reject [action]
Action: Reject the sample.
Next: END
""", filename="decision.md")
    assert plan.steps[0].condition is None
    assert plan.steps[0].true_step == "accept"
    assert plan.steps[0].false_step == "reject"


@pytest.mark.parametrize(
    ("filename", "line", "rule"),
    [
        ("malformed_timeout.md", 10, "SOP-TIMEOUT"),
        ("malformed_missing_next.md", 7, "SOP-NEXT-REQUIRED"),
    ],
)
def test_malformed_fixtures_name_file_line_and_grammar_rule(fixture_dir, filename, line, rule):
    path = fixture_dir / filename
    with pytest.raises(SOPParseError) as caught:
        parse_file(path)
    message = str(caught.value)
    assert f"{filename}:{line}:" in message
    assert rule in message
    if filename == "malformed_timeout.md":
        assert "next week" in message


@pytest.mark.parametrize(
    ("source", "rule", "line"),
    [
        ("", "SOP-HEADER", 1),
        ("SOP: X\nTrigger: missing owner\n", "SOP-OWNER", 2),
        ("SOP: X\nOwner: Y\nTrigger: Z\nRoles:\nSteps:\nwat\n", "SOP-STEP-HEADER", 6),
    ],
)
def test_grammar_errors_have_line_and_named_rule(source, rule, line):
    with pytest.raises(SOPParseError) as caught:
        parse_text(source, filename="bad.md")
    assert f"bad.md:{line}: {rule}:" in str(caught.value)


def test_duplicate_step_ids_are_grammar_errors():
    source = """SOP: X
Owner: Y
Trigger: Z
Roles:
- operator: a.read
Steps:
## one [action]
Action: Do one.
Next: END
## one [action]
Action: Do duplicate.
Next: END
"""
    with pytest.raises(SOPParseError, match="SOP-STEP-ID-UNIQUE"):
        parse_text(source, "duplicate.md")
