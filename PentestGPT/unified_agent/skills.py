"""Agent Skills (agentskills.io): one canonical skill dir, both agents discover it.

Claude Code reads project skills from ``<ws>/.claude/skills/``; Codex reads the
cross-agent location ``<ws>/.agents/skills/``. ``install_skills`` validates each
skill against the open spec and links it into both, so a single SKILL.md serves
both agents. Validation enforces the spec's shared baseline; ``lint_skill``
flags Claude-only syntax that would degrade on Codex.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .types import SkillError

NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
MAX_NAME_LEN = 64
MAX_DESCRIPTION_LEN = 1024

# Discovery roots inside a workspace, per host.
CLAUDE_SKILLS_DIR = Path(".claude") / "skills"
CODEX_SKILLS_DIR = Path(".agents") / "skills"

# Claude-only constructs that Codex (and other agentskills hosts) ignore.
_PORTABILITY_PATTERNS = [
    ("$ARGUMENTS", "argument substitution ($ARGUMENTS/$1...) is Claude-only"),
    (
        "!`",
        "dynamic shell injection (!`cmd`) is Claude-only and runs before the model sees content",
    ),
    ("${CLAUDE_", "${CLAUDE_*} variables are Claude-only"),
]


@dataclass
class Skill:
    name: str
    description: str
    path: Path
    body: str
    frontmatter: dict = field(default_factory=dict)


def _parse_frontmatter(text: str, where: Path) -> tuple[dict, str]:
    if not text.startswith("---"):
        raise SkillError(f"{where}: SKILL.md must start with YAML frontmatter (--- ... ---)")
    end = text.find("\n---", 3)
    if end == -1:
        raise SkillError(f"{where}: unterminated YAML frontmatter")
    raw = text[3:end]
    body = text[end + 4 :].lstrip("\n")
    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError as e:
        raise SkillError(f"{where}: invalid YAML frontmatter: {e}") from e
    if not isinstance(data, dict):
        raise SkillError(f"{where}: frontmatter must be a YAML mapping")
    return data, body


def load_skill(skill_dir: Path) -> Skill:
    """Load and validate one ``<skill-dir>/SKILL.md`` per the agentskills spec."""
    skill_dir = Path(skill_dir)
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.is_file():
        raise SkillError(f"{skill_dir}: no SKILL.md")
    front, body = _parse_frontmatter(skill_md.read_text(encoding="utf-8"), skill_md)

    name = str(front.get("name") or "")
    description = str(front.get("description") or "")
    if not NAME_RE.match(name) or len(name) > MAX_NAME_LEN:
        raise SkillError(
            f"{skill_md}: invalid skill name {name!r} "
            f"(lowercase/digits/single-hyphens, <= {MAX_NAME_LEN} chars)"
        )
    if name != skill_dir.name:
        raise SkillError(
            f"{skill_md}: skill name {name!r} must match its directory name {skill_dir.name!r}"
        )
    if not description.strip():
        raise SkillError(f"{skill_md}: description is required")
    if len(description) > MAX_DESCRIPTION_LEN:
        raise SkillError(f"{skill_md}: description exceeds {MAX_DESCRIPTION_LEN} chars")
    return Skill(name=name, description=description, path=skill_dir, body=body, frontmatter=front)


def lint_skill(skill: Skill) -> list[str]:
    """Warnings for constructs that work in Claude Code but not in Codex."""
    warnings = []
    for needle, why in _PORTABILITY_PATTERNS:
        if needle in skill.body:
            warnings.append(f"{skill.name}: contains {needle!r} — {why}")
    return warnings


def discover_skills(source_dir: Path) -> list[Skill]:
    source_dir = Path(source_dir)
    if not source_dir.is_dir():
        raise SkillError(f"skills source {source_dir} is not a directory")
    skills = []
    for child in sorted(source_dir.iterdir()):
        if child.is_dir() and (child / "SKILL.md").is_file():
            skills.append(load_skill(child))
    return skills


def make_skill(parent: Path, name: str, description: str, body: str) -> Path:
    """Write a minimal spec-valid skill (used by examples and tests)."""
    d = Path(parent) / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n",
        encoding="utf-8",
    )
    return d


def _install_one(skill: Skill, target_root: Path, mode: str, force: bool) -> None:
    target_root.mkdir(parents=True, exist_ok=True)
    target = target_root / skill.name
    source = skill.path.resolve()

    if target.is_symlink():
        if mode == "symlink" and target.resolve() == source:
            return  # already correct
        target.unlink()
    elif target.exists():
        if not force:
            raise SkillError(
                f"{target} exists and is not a managed symlink; pass force=True to replace it"
            )
        shutil.rmtree(target)

    if mode == "symlink":
        target.symlink_to(source, target_is_directory=True)
    elif mode == "copy":
        shutil.copytree(source, target)
    else:
        raise SkillError(f"unknown install mode {mode!r} (use 'symlink' or 'copy')")


def install_skills(
    workspace: Path,
    source_dir: Path,
    mode: str = "symlink",
    force: bool = False,
) -> list[Skill]:
    """Install every skill under ``source_dir`` into BOTH hosts' discovery dirs.

    Copy mode replaces previously-copied skills on reinstall (the target dirs
    under ``.claude/skills`` / ``.agents/skills`` are treated as managed).
    """
    workspace = Path(workspace)
    skills = discover_skills(source_dir)
    if not skills:
        raise SkillError(f"no skills found under {source_dir}")
    for skill in skills:
        for root in (workspace / CLAUDE_SKILLS_DIR, workspace / CODEX_SKILLS_DIR):
            _install_one(skill, root, mode=mode, force=force or mode == "copy")
    return skills
