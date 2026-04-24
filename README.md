# docs_ci

CI tools for documentation.

`docs_ci` is a small command-line tool that lints and validates Markdown documentation files.
It checks for common issues such as unclosed fenced code blocks, empty headings, trailing
whitespace, and broken relative links.

## Installation

```bash
pip install -e .
```

## Usage

```bash
# Check all Markdown files in the current directory
docs-ci

# Check a specific file or directory
docs-ci path/to/docs/

# Recurse into sub-directories
docs-ci --recursive path/to/docs/

# Suppress warnings, report errors only
docs-ci --no-warnings path/to/docs/
```

## Checks

| Check | Level |
|---|---|
| Unclosed fenced code block | error |
| Empty heading | error |
| Broken relative link | error |
| Trailing whitespace | warning |

## Development

```bash
pip install -e ".[dev]"
pytest
```
