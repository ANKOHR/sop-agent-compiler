import copy
import json

import pytest

from sopc.errors import PlanSchemaError
from sopc.model import Plan
from sopc.parser import parse_file


def test_ir_json_roundtrip_is_stable(fixture_dir):
    plan = parse_file(fixture_dir / "refund_approval.md")
    rendered = plan.to_json()
    loaded = Plan.from_dict(json.loads(rendered))
    assert loaded == plan
    assert loaded.to_json() == rendered
    assert json.loads(rendered)["schema_version"] == "1.0"


@pytest.mark.parametrize(
    ("change", "rule"),
    [
        (lambda data: data.update(schema_version="9.0"), "PLAN-VERSION"),
        (lambda data: data.pop("title"), "PLAN-ROOT"),
        (lambda data: data.update(extra="x"), "PLAN-ROOT"),
        (lambda data: data.update(entry_step="not_first"), "PLAN-ENTRY"),
    ],
)
def test_malformed_ir_has_named_schema_error(fixture_dir, change, rule):
    data = json.loads(parse_file(fixture_dir / "employee_onboarding.md").to_json())
    change(data)
    with pytest.raises(PlanSchemaError) as caught:
        Plan.from_dict(data)
    assert caught.value.rule == rule


def test_wrong_typed_field_has_named_schema_error(fixture_dir):
    data = json.loads(parse_file(fixture_dir / "employee_onboarding.md").to_json())
    data["steps"][0]["required_permissions"] = "employee.read"
    with pytest.raises(PlanSchemaError, match="PLAN-STEP-1-PERMISSIONS"):
        Plan.from_dict(data)
