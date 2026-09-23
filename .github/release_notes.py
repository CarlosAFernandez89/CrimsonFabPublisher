"""Print one version's section of CHANGELOG.md, ready to be a release body.

    python .github/release_notes.py 1.2 < CHANGELOG.md

CHANGELOG.md is hard-wrapped so it reads well as a file, but GitHub renders a
release body like a comment, where every newline is a visible line break - a
wrapped paragraph comes out broken mid-sentence. So paragraphs and list items
are joined back onto one line each; headings, blank lines and code blocks are
left alone.

Prints nothing when the changelog has no section for the version, so the
caller can fall back to generated notes.
"""

from __future__ import annotations

import re
import sys

#: Lines that start a new block rather than continuing the previous one.
_BLOCK_START = re.compile(r"^(#{1,6} |[-*+] |\d+\. |>|\|)")


def section(changelog: str, version: str) -> list[str]:
    lines: list[str] = []
    found = False
    for line in changelog.splitlines():
        if line.startswith("## "):
            if found:
                break
            found = line.split()[1] == version if len(line.split()) > 1 else False
            continue
        if found:
            lines.append(line)
    return lines


def unwrap(lines: list[str]) -> str:
    out: list[str] = []
    in_code = False
    for raw in lines:
        line = raw.rstrip()
        if line.lstrip().startswith("```"):
            in_code = not in_code
            out.append(line)
            continue
        if in_code:
            out.append(line)
            continue
        joinable = (
            out
            and out[-1].strip()
            and not out[-1].lstrip().startswith("#")
            and not out[-1].lstrip().startswith("```")
            and line.strip()
            and not _BLOCK_START.match(line.lstrip())
        )
        if joinable:
            out[-1] = out[-1] + " " + line.strip()
        else:
            out.append(line)
    return "\n".join(out).strip() + "\n"


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: release_notes.py VERSION < CHANGELOG.md", file=sys.stderr)
        return 2
    lines = section(sys.stdin.read(), sys.argv[1])
    if any(line.strip() for line in lines):
        sys.stdout.write(unwrap(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
