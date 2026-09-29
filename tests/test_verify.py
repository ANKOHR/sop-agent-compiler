from dataclasses import replace

from sopc.model import CheckpointConfig, RetryPolicy
from sopc.parser import parse_file
from sopc.verify import RULES, verify


def test_clean_fixtures_verify(fixture_dir):
    for filename in ("employee_onboarding.md", "refund_approval.md"):
        assert verify(parse_file(fixture_dir / filename), raise_on_error=False) == ()


def test_broken_fixtures_raise_exact_intended_rules(fixture_dir):
    missing_approval = verify(parse_file(fixture_dir / "broken_payment_missing_checkpoint.md"), False)
    assert [(item.code, item.step_id) for item in missing_approval] == [
        ("SOPC103", "issue_payment"),
    ]

    unreachable_gap = verify(parse_file(fixture_dir / "broken_unreachable_permission_gap.md"), False)
    assert {(item.code, item.step_id) for item in unreachable_gap} == {
        ("SOPC101", "unreachable_archive"),
        ("SOPC104", "unreachable_archive"),
    }
    assert all(item.reference == RULES[item.code] for item in missing_approval + unreachable_gap)


def test_verifier_reports_decision_condition_retry_and_checkpoint_rules(fixture_dir):
    plan = parse_file(fixture_dir / "employee_onboarding.md")
    decision = replace(
        plan.steps[0], kind="decision", action="", condition=None,
        next_step=None, true_step="prepare_workspace", false_step="prepare_workspace",
    )
    checkpoint = replace(
        plan.steps[1], kind="checkpoint", branches=(), join_step=None, next_step="create_profile",
        checkpoint_config=CheckpointConfig(human=False),
    )
    action = replace(
        plan.steps[2], retry_policy=RetryPolicy(attempts=0, backoff_ms=5, factor=0.5, max_backoff_ms=1),
        next_step="missing_target",
    )
    malformed = replace(plan, steps=(decision, checkpoint, action, *plan.steps[3:]))
    violations = verify(malformed, False)
    codes = {item.code for item in violations}
    assert {"SOPC102", "SOPC105", "SOPC106", "SOPC107"} <= codes
    assert all(item.step_id and item.reference and item.code for item in violations)


def test_consequential_action_must_be_behind_checkpoint_on_every_path():
    source = """SOP: Synthetic bypass test
Owner: QA
Trigger: A fictional payment is requested.
Roles:
- operator: payments.issue
Steps:
## branch [decision]
Condition: request.approved
True: approval
False: issue
## approval [checkpoint]
Next: issue
## issue [action]
Action: Charge fictional payment.
Consequence: payment
Requires: payments.issue
Next: END
"""
    from sopc.parser import parse_text

    violation = verify(parse_text(source), False)
    assert [(item.code, item.step_id) for item in violation] == [("SOPC103", "issue")]
