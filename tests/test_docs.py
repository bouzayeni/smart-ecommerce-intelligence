"""Documentation integrity: every relative link, image and #anchor in the Markdown resolves.

Runs in CI (no database needed), so a renamed file or heading breaks the build instead of the
README.
"""

import re
from pathlib import Path

import pytest

from data_engineering.config import PROJECT_ROOT

SKIP_DIRS = {"node_modules", ".venv", "dbt_packages", "target", ".git", ".pytest_cache"}
LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
FENCE = re.compile(r"^(```|~~~)")


def markdown_files() -> list[Path]:
    return sorted(
        p
        for p in PROJECT_ROOT.rglob("*.md")
        if not SKIP_DIRS.intersection(p.relative_to(PROJECT_ROOT).parts)
    )


def prose_lines(path: Path, strip_code: bool = True) -> list[str]:
    """Lines outside fenced code blocks, optionally with inline code removed."""
    out, in_fence = [], False
    for line in path.read_text(encoding="utf-8").splitlines():
        if FENCE.match(line.strip()):
            in_fence = not in_fence
            continue
        if not in_fence:
            out.append(re.sub(r"`[^`]*`", "", line) if strip_code else line)
    return out


def slug(heading: str) -> str:
    """GitHub's heading anchor: lower case, punctuation dropped, spaces to hyphens."""
    text = re.sub(r"`|\*\*|__", "", heading.strip().lower())
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def anchors(path: Path) -> set[str]:
    seen: dict[str, int] = {}
    out = set()
    for line in prose_lines(path, strip_code=False) if path.suffix == ".md" else []:
        m = re.match(r"^#{1,6}\s+(.*)$", line)
        if not m:
            continue
        base = slug(m.group(1))
        n = seen.get(base, 0)
        out.add(base if n == 0 else f"{base}-{n}")
        seen[base] = n + 1
    return out


def links(path: Path) -> list[str]:
    return [m.group(1) for line in prose_lines(path) for m in LINK.finditer(line)]


FILES = markdown_files()


def test_markdown_files_found():
    names = {p.relative_to(PROJECT_ROOT).as_posix() for p in FILES}
    assert {"README.md", "docs/architecture.md", "docs/portfolio.md"} <= names


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.relative_to(PROJECT_ROOT).as_posix())
def test_relative_links_resolve(path: Path):
    broken = []
    for target in links(path):
        if re.match(r"^[a-z]+:", target):  # http(s), mailto
            continue
        file_part, _, anchor = target.partition("#")
        dest = (path.parent / file_part).resolve() if file_part else path
        if not dest.exists():
            broken.append(f"{target} (missing file)")
        elif anchor and dest.is_file() and anchor not in anchors(dest):
            broken.append(f"{target} (no heading #{anchor})")
    assert not broken, f"{path.relative_to(PROJECT_ROOT)}: " + "; ".join(broken)


def test_slug_matches_github_rules():
    assert slug("Test layers") == "test-layers"
    assert slug("CI (`.github/workflows/ci.yml`)") == "ci-githubworkflowsciyml"
    assert slug("3. Spend is concentrated") == "3-spend-is-concentrated"
    assert slug("### raw.customers".lstrip("# ")) == "rawcustomers"
