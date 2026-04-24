from pathlib import Path

import pytest
from pydantic import ValidationError

from docs_ci.config import RulesConfig, Severity, load_rules

FIXTURE = Path(__file__).parent / "fixtures" / "rules.yaml"


def test_load_valid_yaml():
    cfg = load_rules(FIXTURE)
    assert {r.id for r in cfg.rules} == {"has-title", "has-example"}
    assert next(r for r in cfg.rules if r.id == "has-title").severity == Severity.error
    assert next(r for r in cfg.rules if r.id == "has-example").severity == Severity.warning


def test_missing_id_rejected():
    with pytest.raises(ValidationError):
        RulesConfig.model_validate({"rules": [{"severity": "error", "criterion": "x"}]})


def test_extra_field_rejected():
    with pytest.raises(ValidationError):
        RulesConfig.model_validate(
            {"rules": [{"id": "ok", "severity": "error", "criterion": "x", "bogus": True}]}
        )


def test_non_kebab_id_rejected():
    with pytest.raises(ValidationError):
        RulesConfig.model_validate(
            {"rules": [{"id": "CamelCase", "severity": "error", "criterion": "x"}]}
        )


def test_duplicate_ids_rejected():
    with pytest.raises(ValidationError):
        RulesConfig.model_validate(
            {
                "rules": [
                    {"id": "a", "severity": "error", "criterion": "x"},
                    {"id": "a", "severity": "warning", "criterion": "y"},
                ]
            }
        )


def test_severity_defaults_to_error():
    cfg = RulesConfig.model_validate({"rules": [{"id": "a", "criterion": "x"}]})
    assert cfg.rules[0].severity == Severity.error
