from pathlib import Path

import pytest

from unified_agent.skills import (
    discover_skills,
    install_skills,
    lint_skill,
    load_skill,
    make_skill,
)
from unified_agent.types import SkillError


def write_skill(root: Path, dirname: str, frontmatter: str, body: str = "Do the thing.") -> Path:
    d = root / dirname
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\n{frontmatter}\n---\n\n{body}")
    return d


def test_load_valid_skill(tmp_path):
    d = write_skill(
        tmp_path,
        "word-count",
        "name: word-count\ndescription: Count words in files. Use when asked for word counts.",
    )
    s = load_skill(d)
    assert s.name == "word-count"
    assert s.description.startswith("Count words")
    assert "Do the thing." in s.body
    assert s.path == d


def test_name_must_match_directory(tmp_path):
    d = write_skill(tmp_path, "other-dir", "name: word-count\ndescription: x")
    with pytest.raises(SkillError, match="directory"):
        load_skill(d)


@pytest.mark.parametrize("bad", ["Deploy", "a--b", "-x", "x-", "a" * 65, "has_underscore"])
def test_invalid_names_rejected(tmp_path, bad):
    d = write_skill(tmp_path, "okdir", f"name: '{bad}'\ndescription: x")
    with pytest.raises(SkillError):
        load_skill(d)


def test_description_required_and_capped(tmp_path):
    d1 = write_skill(tmp_path, "s-one", "name: s-one\ndescription: ''")
    with pytest.raises(SkillError, match="description"):
        load_skill(d1)
    d2 = write_skill(tmp_path, "s-two", f"name: s-two\ndescription: {'y' * 1025}")
    with pytest.raises(SkillError, match="1024"):
        load_skill(d2)


def test_missing_frontmatter_rejected(tmp_path):
    d = tmp_path / "s-three"
    d.mkdir()
    (d / "SKILL.md").write_text("no frontmatter here")
    with pytest.raises(SkillError, match="frontmatter"):
        load_skill(d)


def test_lint_warns_on_claude_only_syntax(tmp_path):
    d = write_skill(
        tmp_path,
        "porta",
        "name: porta\ndescription: x",
        body="Run with $ARGUMENTS and !`git diff` and ${CLAUDE_SKILL_DIR}/x",
    )
    s = load_skill(d)
    warnings = lint_skill(s)
    joined = " ".join(warnings)
    assert "$ARGUMENTS" in joined
    assert "!`" in joined or "injection" in joined
    assert "${CLAUDE_" in joined


def test_make_and_discover(tmp_path):
    make_skill(tmp_path, "alpha-skill", "Does alpha. Use for alpha tasks.", "Body A")
    make_skill(tmp_path, "beta-skill", "Does beta. Use for beta tasks.", "Body B")
    (tmp_path / "not-a-skill").mkdir()
    names = [s.name for s in discover_skills(tmp_path)]
    assert names == ["alpha-skill", "beta-skill"]


def test_install_symlinks_into_both_discovery_dirs(tmp_path):
    src = tmp_path / "skills"
    make_skill(src, "alpha-skill", "Does alpha.", "Body A")
    ws = tmp_path / "ws"
    installed = install_skills(ws, src)
    assert [s.name for s in installed] == ["alpha-skill"]
    for root in [ws / ".claude" / "skills", ws / ".agents" / "skills"]:
        link = root / "alpha-skill"
        assert link.is_symlink()
        assert (link / "SKILL.md").read_text().find("Does alpha.") != -1
        assert link.resolve() == (src / "alpha-skill").resolve()


def test_install_idempotent_and_replaces_stale_symlink(tmp_path):
    src = tmp_path / "skills"
    make_skill(src, "alpha-skill", "Does alpha.", "Body A")
    ws = tmp_path / "ws"
    install_skills(ws, src)
    install_skills(ws, src)  # no error
    # point the link somewhere stale, then reinstall
    link = ws / ".claude" / "skills" / "alpha-skill"
    link.unlink()
    other = tmp_path / "elsewhere"
    other.mkdir()
    link.symlink_to(other)
    install_skills(ws, src)
    assert link.resolve() == (src / "alpha-skill").resolve()


def test_install_refuses_real_dir_without_force(tmp_path):
    src = tmp_path / "skills"
    make_skill(src, "alpha-skill", "Does alpha.", "Body A")
    ws = tmp_path / "ws"
    real = ws / ".agents" / "skills" / "alpha-skill"
    real.mkdir(parents=True)
    (real / "SKILL.md").write_text("preexisting")
    with pytest.raises(SkillError, match="force"):
        install_skills(ws, src)
    install_skills(ws, src, force=True)
    assert (ws / ".agents" / "skills" / "alpha-skill").is_symlink()


def test_install_copy_mode(tmp_path):
    src = tmp_path / "skills"
    make_skill(src, "alpha-skill", "Does alpha.", "Body A")
    ws = tmp_path / "ws"
    install_skills(ws, src, mode="copy")
    target = ws / ".claude" / "skills" / "alpha-skill"
    assert target.is_dir() and not target.is_symlink()
    assert "Does alpha." in (target / "SKILL.md").read_text()
    install_skills(ws, src, mode="copy")  # idempotent re-copy


def test_install_empty_source_errors(tmp_path):
    empty = tmp_path / "skills"
    empty.mkdir()
    with pytest.raises(SkillError, match=r"[Nn]o skills"):
        install_skills(tmp_path / "ws", empty)
