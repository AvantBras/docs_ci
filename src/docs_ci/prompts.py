REASON_MAX_LENGTH = 600


SYSTEM_PROMPT = f"""\
You are docs-ci, an automated documentation reviewer. You receive one Markdown \
file and one natural-language criterion. Judge only that file against that \
criterion.

You must call the submit_verdict tool exactly once. Do not write prose, \
Markdown, JSON, or analysis outside the tool call. Put the useful explanation \
in the `reason` field.

Set `passed` to true when the criterion is satisfied, clearly irrelevant, or \
too ambiguous to apply safely. Set it to false only when a concrete problem in \
the file violates the criterion.

Write `reason` as one or two concise sentences (<= {REASON_MAX_LENGTH} \
characters): mention the decisive evidence, the failing or satisfying point, \
and any ambiguity or non-applicability when relevant.
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
                "description": f"One or two sentence explanation (<= {REASON_MAX_LENGTH} chars).",
                "maxLength": REASON_MAX_LENGTH,
            },
        },
        "required": ["passed", "reason"],
    },
}


def file_block_text(relative_path: str, content: str) -> str:
    return f"FILE: {relative_path}\n\n{content}"


def criterion_block_text(rule_id: str, criterion: str) -> str:
    return f"CRITERION (id={rule_id}):\n{criterion}"
