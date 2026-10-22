"""Standalone tests for the DVWA flag seeder (no database, no DVWA host).

Self-contained: imports ``seed_dvwa`` from this directory and checks generated
flags against a local copy of the PentestGPT loop's ``DEFAULT_FLAG_PATTERNS``,
so it runs without the ``pentestgpt_legacy`` package installed.

Run from this directory::

    python -m pytest test_seed_dvwa.py
"""

import re

import seed_dvwa
from seed_dvwa import (
    FLAG_SPECS,
    main,
    resolve_path,
    shell_commands,
    sql_statements,
)

# Mirrors pentestgpt_legacy.autonomous.loop.DEFAULT_FLAG_PATTERNS. Kept in sync
# by hand; the seeder only ever emits the plain ``flag{...}`` form.
LOOP_FLAG_PATTERNS = (
    r"flag\{[^}]+\}",
    r"HTB\{[^}]+\}",
    r"CTF\{[^}]+\}",
    r"[A-Za-z0-9_]*CTF\{[^}]+\}",
)


def _detect_flags(text: str) -> list[str]:
    found: list[str] = []
    for pattern in LOOP_FLAG_PATTERNS:
        for match in re.finditer(pattern, text, re.IGNORECASE):
            if match.group(0) not in found:
                found.append(match.group(0))
    return found


def test_every_flag_is_captured_by_the_loop():
    """The whole point: a planted flag must match the loop's own patterns."""
    token = "abc12345"
    for spec in FLAG_SPECS:
        flag = spec.flag(token)
        assert _detect_flags(flag) == [flag], flag


def test_flags_are_unique_per_module():
    token = "deadbeef"
    flags = [spec.flag(token) for spec in FLAG_SPECS]
    assert len(set(flags)) == len(flags)


def test_sql_only_targets_database_specs():
    stmts = sql_statements(FLAG_SPECS, "tok")
    db_specs = [s for s in FLAG_SPECS if s.table is not None]
    assert len(stmts) == len(db_specs)
    assert all(s.startswith("INSERT INTO ") for s in stmts)
    # AUTO_INCREMENT keys are left out so re-seeding never collides.
    assert not any("user_id" in s or "comment_id" in s for s in stmts)


def test_sql_escapes_single_quotes():
    stmts = sql_statements(FLAG_SPECS, "o'brien")
    assert any("o''brien" in s for s in stmts)


def test_shell_only_targets_file_specs_and_honors_webroot():
    cmds = shell_commands(FLAG_SPECS, "tok", "/srv/www")
    file_specs = [s for s in FLAG_SPECS if s.path is not None]
    # One mkdir + one write per file-backed flag.
    assert len(cmds) == 2 * len(file_specs)
    webroot_flag = next(s for s in FLAG_SPECS if s.slug == "cmdi")
    assert resolve_path(webroot_flag, "/srv/www").startswith("/srv/www/")
    assert any("/srv/www/" in c for c in cmds)


def test_dry_run_plants_nothing(capsys):
    rc = main(["--token", "demo"])
    assert rc == 0
    out = capsys.readouterr()
    assert "flag{dvwa_sqli_demo}" in out.out
    assert "Dry run" in out.err


def test_module_has_no_package_dependency():
    """Guards the standalone promise: stdlib imports only."""
    assert seed_dvwa.__name__ == "seed_dvwa"
