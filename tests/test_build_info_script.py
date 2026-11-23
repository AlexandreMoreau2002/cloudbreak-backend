import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import build_info  # noqa: E402

SHA = "b" * 40


def _git(tmp_path: Path, head: str) -> Path:
    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "HEAD").write_text(head)
    return git_dir


def test_resolves_sha_from_branch_ref_file(tmp_path: Path) -> None:
    git_dir = _git(tmp_path, "ref: refs/heads/develop\n")
    (git_dir / "refs" / "heads").mkdir(parents=True)
    (git_dir / "refs" / "heads" / "develop").write_text(SHA + "\n")

    assert build_info.resolve_sha(git_dir) == SHA


def test_resolves_sha_from_packed_refs_and_detached_head(tmp_path: Path) -> None:
    git_dir = _git(tmp_path, "ref: refs/heads/develop\n")
    (git_dir / "packed-refs").write_text(f"# pack-refs\n{SHA} refs/heads/develop\n")
    assert build_info.resolve_sha(git_dir) == SHA

    (git_dir / "HEAD").write_text(SHA + "\n")
    assert build_info.resolve_sha(git_dir) == SHA


def test_tag_is_only_returned_when_it_points_at_the_sha(tmp_path: Path) -> None:
    git_dir = _git(tmp_path, SHA)
    (git_dir / "packed-refs").write_text(
        f"{SHA} refs/tags/v1.0.1\n{'c' * 40} refs/tags/v0.9.0\n{SHA} refs/tags/not-a-release\n"
    )

    assert build_info.resolve_tag(git_dir, SHA) == "v1.0.1"
    assert build_info.resolve_tag(git_dir, "d" * 40) is None


def test_unreadable_git_dir_gives_empty_info(tmp_path: Path) -> None:
    git_dir = _git(tmp_path, "garbage")

    info = build_info.build_info(git_dir)

    assert info == {"sha": None, "built_at": None, "tag": None}
