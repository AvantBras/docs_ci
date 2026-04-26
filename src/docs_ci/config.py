from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, field_validator


class Severity(StrEnum):
    error = "error"
    warning = "warning"


class Provider(StrEnum):
    anthropic = "anthropic"
    openrouter = "openrouter"
    nvidia = "nvidia"


class Rule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    severity: Severity = Severity.error
    criterion: str

    @field_validator("id")
    @classmethod
    def _kebab_id(cls, v: str) -> str:
        if not v or v != v.lower() or not all(c.isalnum() or c == "-" for c in v):
            raise ValueError(
                "id must be kebab-case: lowercase letters, digits, and hyphens only"
            )
        return v


class RulesConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rules: list[Rule]

    @field_validator("rules")
    @classmethod
    def _unique_ids(cls, rules: list[Rule]) -> list[Rule]:
        ids = [r.id for r in rules]
        dupes = sorted({x for x in ids if ids.count(x) > 1})
        if dupes:
            raise ValueError(f"duplicate rule IDs: {dupes}")
        return rules


class Verdict(BaseModel):
    file: Path
    rule_id: str
    severity: Severity
    passed: bool
    reason: str


def load_rules(path: Path) -> RulesConfig:
    with path.open("r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return RulesConfig.model_validate(raw or {})
