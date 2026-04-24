SYSTEM_PROMPT = """\
You are a documentation reviewer. You are given the content of a single \
documentation file and a single criterion written in natural language. \
Judge whether the file satisfies the criterion.

Call the submit_verdict tool with `passed` (bool) and `reason` (short \
justification, <= 280 characters). If the criterion is ambiguous or \
clearly not applicable to this file, prefer passed=true and note the \
ambiguity in the reason.
"""


SUBMIT_VERDICT_TOOL = {
    "name": "submit_verdict",
    "description": "Record a pass/fail verdict for the file against the criterion.",
    "input_schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "passed": {
                "type": "boolean",
                "description": "True if the file satisfies the criterion.",
            },
            "reason": {
                "type": "string",
                "description": "Short justification (<= 280 chars).",
                "maxLength": 280,
            },
        },
        "required": ["passed", "reason"],
    },
}


def file_block_text(relative_path: str, content: str) -> str:
    return f"FILE: {relative_path}\n\n{content}"


def criterion_block_text(rule_id: str, criterion: str) -> str:
    return f"CRITERION (id={rule_id}):\n{criterion}"
