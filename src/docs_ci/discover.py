from collections.abc import Iterator
from pathlib import Path


def iter_docs(root: Path) -> Iterator[Path]:
    yield from sorted(p for p in root.rglob("*.md") if p.is_file())
