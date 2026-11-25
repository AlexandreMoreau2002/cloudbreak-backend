"""Écrit build_info.json (sha, date de build, tag) à partir du dossier .git du build.

Dokploy clone le dépôt sans transmettre le commit au build : ce script le relit dans .git,
sans binaire git. Un échec n'interrompt jamais le build (l'endpoint répond alors « unknown »).
"""

import json
import re
from datetime import UTC, datetime
from pathlib import Path

SHA = re.compile(r"[0-9a-f]{40}")
TAG = re.compile(r"v\d+\.\d+\.\d+")


def _packed_refs(git_dir: Path) -> dict[str, str]:
    refs: dict[str, str] = {}
    path = git_dir / "packed-refs"
    if path.is_file():
        for line in path.read_text().splitlines():
            parts = line.split(" ", 1)
            if len(parts) == 2 and SHA.fullmatch(parts[0]):
                refs[parts[1].strip()] = parts[0]
    return refs


def resolve_sha(git_dir: Path) -> str | None:
    head = (git_dir / "HEAD").read_text().strip()
    if SHA.fullmatch(head):
        return head
    if not head.startswith("ref: "):
        return None
    ref = head.removeprefix("ref: ").strip()
    ref_file = git_dir / ref
    if ref_file.is_file():
        value = ref_file.read_text().strip()
        return value if SHA.fullmatch(value) else None
    return _packed_refs(git_dir).get(ref)


def resolve_tag(git_dir: Path, sha: str) -> str | None:
    tags = sorted(
        name.removeprefix("refs/tags/")
        for name, value in _packed_refs(git_dir).items()
        if value == sha and name.startswith("refs/tags/")
    )
    tags += sorted(
        path.name
        for path in (git_dir / "refs" / "tags").glob("*")
        if path.is_file() and path.read_text().strip() == sha
    )
    return next((tag for tag in tags if TAG.fullmatch(tag)), None)


def build_info(git_dir: Path) -> dict[str, str | None]:
    sha = resolve_sha(git_dir)
    if sha is None:
        return {"sha": None, "built_at": None, "tag": None}
    built_at = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"sha": sha, "built_at": built_at, "tag": resolve_tag(git_dir, sha)}


def main() -> None:
    try:
        info = build_info(Path(".git"))
    except OSError:
        info = {"sha": None, "built_at": None, "tag": None}
    Path("build_info.json").write_text(json.dumps(info))


if __name__ == "__main__":
    main()
