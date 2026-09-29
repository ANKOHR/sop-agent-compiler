from sopc.executor import execute
from sopc.parser import parse_file


def test_onboarding_parallel_happy_path_completes_and_logs_all_steps(fixture_dir):
    plan = parse_file(fixture_dir / "employee_onboarding.md")
    result = execute(plan, role="operator")
    assert result.status == "completed"
    assert result.completed_steps == [
        "validate_request", "create_profile", "provision_device", "prepare_workspace", "welcome_employee",
    ]
    assert [event["seq"] for event in result.events] == list(range(1, len(result.events) + 1))
    assert any(event["type"] == "parallel.joined" for event in result.events)


def test_checkpoint_reject_route_and_unrouted_rejection(fixture_dir):
    plan = parse_file(fixture_dir / "refund_approval.md")
    routed = execute(plan, role="operator", checkpoint_decisions={
        "manager_approval": {"decision": "reject", "reason": "Outside fictional policy."},
    })
    assert routed.status == "completed"
    assert "issue_refund" not in routed.completed_steps
    assert "record_rejection" in routed.completed_steps
    assert any(event["type"] == "checkpoint.decided" and event["decision"] == "reject" for event in routed.events)

    from sopc.parser import parse_text

    no_rejection_route = parse_text("""SOP: Synthetic rejection
Owner: QA
Trigger: A fictional payment is reviewed.
Roles:
- operator: payments.issue
Steps:
## approval [checkpoint]
Next: issue
## issue [action]
Action: Charge the fictional payment.
Consequence: payment
Requires: payments.issue
Next: END
""")
    stopped = execute(no_rejection_route, role="operator", checkpoint_decisions={
        "approval": {"decision": "reject", "reason": "Declined."},
    })
    assert stopped.status == "rejected"
    assert stopped.error_code == "SOPC-RUN-CHECKPOINT-REJECTED"
    assert "issue" not in stopped.completed_steps


def test_checkpoint_pauses_and_edit_reason_routes_then_reapproval(fixture_dir):
    plan = parse_file(fixture_dir / "refund_approval.md")
    paused = execute(plan, role="operator")
    assert paused.status == "paused"
    assert paused.paused_at == "manager_approval"
    assert paused.events[-1]["type"] == "checkpoint.waiting"

    edited = execute(plan, role="operator", checkpoint_decisions={
        "manager_approval": [
            {"decision": "edit", "reason": "Correct the fictional order reference."},
            "approve",
        ],
        "receipt_approval": "approve",
    })
    assert edited.status == "completed"
    assert "revise_request" in edited.completed_steps
    assert edited.completed_steps.count("manager_approval") == 2
    edit_event = next(event for event in edited.events if event["type"] == "checkpoint.edited")
    assert edit_event["reason"] == "Correct the fictional order reference."


def test_checkpoint_edit_requires_reason(fixture_dir):
    plan = parse_file(fixture_dir / "refund_approval.md")
    result = execute(plan, role="operator", checkpoint_decisions={"manager_approval": "edit"})
    assert result.status == "failed"
    assert result.error_code == "SOPC-RUN-CHECKPOINT-REASON"
    assert not any(event["step_id"] == "issue_refund" and event["type"] == "step.started" for event in result.events)


def test_retries_use_declared_backoff_and_stop_after_attempt_limit(fixture_dir):
    plan = parse_file(fixture_dir / "refund_approval.md")
    decisions = {"manager_approval": "approve", "receipt_approval": "approve"}
    result = execute(plan, role="operator", checkpoint_decisions=decisions,
                     adapter_outcomes={"issue_refund": ["failure", "failure", "success"]})
    assert result.status == "completed"
    retries = [event["backoff_ms"] for event in result.events if event["type"] == "retry.scheduled"]
    assert retries == [200, 400]
    attempts = [event["attempt"] for event in result.events if event.get("step_id") == "issue_refund" and event["type"] == "adapter.result"]
    assert attempts == [1, 2, 3]

    exhausted = execute(plan, role="operator", checkpoint_decisions=decisions,
                        adapter_outcomes={"issue_refund": ["failure", "failure", "failure"]})
    assert exhausted.status == "failed"
    assert exhausted.error_code == "SOPC-RUN-STEP-FAILED"
    assert [event["backoff_ms"] for event in exhausted.events if event["type"] == "retry.scheduled"] == [200, 400]


def test_permission_denial_is_logged_before_step_starts(fixture_dir):
    plan = parse_file(fixture_dir / "employee_onboarding.md")
    result = execute(plan, role="missing-role")
    assert result.status == "failed"
    assert result.error_code == "SOPC-RUN-PERMISSION-DENIED"
    assert result.events[-1]["type"] == "permission.denied"
    assert result.events[-1]["step_id"] == "validate_request"
    assert not any(event["type"] == "step.started" for event in result.events)


def test_invalid_consequential_plan_is_refused_before_simulation(fixture_dir):
    plan = parse_file(fixture_dir / "broken_payment_missing_checkpoint.md")
    result = execute(plan, role="operator")
    assert result.status == "failed"
    assert result.error_code == "SOPC-RUN-PLAN-INVALID"
    assert "SOPC103" in result.message
    assert result.events == []


def test_condition_routes_using_explicit_simulated_result():
    from sopc.parser import parse_text

    plan = parse_text("""SOP: Synthetic decision run
Owner: QA
Trigger: A fictional decision sample is ready.
Roles:
- operator: sample.read
Steps:
## choose [decision]
Condition: sample.approved
True: yes
False: no
## yes [action]
Action: Record fictional approval.
Next: END
## no [action]
Action: Record fictional rejection.
Next: END
""")
    result = execute(plan, condition_results={"sample.approved": False})
    assert result.status == "completed"
    assert "no" in result.completed_steps
    assert "yes" not in result.completed_steps
