from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import httpx
import pytest

from openharness.config.settings import PathRuleConfig, PermissionSettings
from openharness.permissions import PermissionChecker
from openharness.tools.base import ToolExecutionContext

PLUGIN_TOOL = (
    Path(__file__).resolve().parents[2]
    / ".openharness"
    / "plugins"
    / "dependency_audit"
    / "tools"
    / "dependency_audit_tool.py"
)
SPEC = importlib.util.spec_from_file_location("dependency_audit_tool", PLUGIN_TOOL)
assert SPEC is not None and SPEC.loader is not None
TOOL_MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TOOL_MODULE
SPEC.loader.exec_module(TOOL_MODULE)


def test_requirements_parser_accepts_exact_pins_and_extras():
    packages, errors = TOOL_MODULE._parse_requirements(
        "Flask[async]==3.0.0 ; python_version >= '3.10'\n# comment\nrequests>=2.0\n",
        "requirements.txt",
    )

    assert [(item.name, item.version, item.ecosystem) for item in packages] == [
        ("flask", "3.0.0", "PyPI")
    ]
    assert len(errors) == 1
    assert "non-exact" in errors[0]


def test_requirements_parser_reports_includes_and_editable_lines():
    packages, errors = TOOL_MODULE._parse_requirements(
        "requests==2.31.0\n-r other.txt\n-e .\n", "requirements.txt"
    )

    assert [item.name for item in packages] == ["requests"]
    assert len(errors) == 2
    assert all("include and editable" in error for error in errors)


def test_invalid_package_json_does_not_discard_requirements(tmp_path: Path):
    (tmp_path / "requirements.txt").write_text("requests==2.31.0\n", encoding="utf-8")
    (tmp_path / "package.json").write_text("{invalid", encoding="utf-8")

    packages, errors, manifests = TOOL_MODULE._read_manifests(tmp_path, cwd=tmp_path)

    assert [(item.name, item.manifest) for item in packages] == [
        ("requests", "requirements.txt")
    ]
    assert manifests == ["requirements.txt", "package.json"]
    assert len(errors) == 1
    assert "package.json is invalid JSON" in errors[0]


def test_package_json_parser_includes_supported_dependency_sections():
    packages, errors = TOOL_MODULE._parse_package_json(
        '{"dependencies":{"left-pad":"1.3.0"},"devDependencies":{"typescript":"5.4.2"},'
        '"optionalDependencies":{"fsevents":"2.3.3"}}',
        "package.json",
    )

    assert [(item.name, item.version) for item in packages] == [
        ("left-pad", "1.3.0"), ("typescript", "5.4.2"), ("fsevents", "2.3.3")
    ]
    assert errors == []


def test_package_json_parser_preserves_supported_ranges():
    packages, errors = TOOL_MODULE._parse_package_json(
        '{"dependencies":{"react":"^18.2.0"}}', "package.json"
    )

    assert len(packages) == 1
    assert packages[0].constraint == "^18.2.0"
    assert errors == []


def test_package_json_parser_reports_unsupported_range_syntax():
    packages, errors = TOOL_MODULE._parse_package_json(
        '{"dependencies":{"react":"git+https://example.invalid/react.git"}}', "package.json"
    )

    assert packages == []
    assert "unsupported npm version range" in errors[0]


def test_range_check_uses_lowest_matching_affected_version():
    package = TOOL_MODULE.PackageVersion(
        name="react", version="", ecosystem="npm", manifest="package.json", constraint="^1.2.0"
    )
    advisory = {
        "affected": [{
            "package": {"name": "react", "ecosystem": "npm"},
            "versions": ["1.2.3", "1.2.2", "2.0.0"],
        }]
    }

    assert TOOL_MODULE._osv_query(package) == {"package": {"name": "react", "ecosystem": "npm"}}
    assert TOOL_MODULE._lowest_matching_affected_version(advisory, package) == "1.2.2"


def test_range_check_intersects_manifest_and_osv_semver_ranges():
    package = TOOL_MODULE.PackageVersion(
        name="react", version="", ecosystem="npm", manifest="package.json", constraint="^1.2.0"
    )
    advisory = {
        "affected": [{
            "package": {"name": "react", "ecosystem": "npm"},
            "ranges": [{
                "type": "SEMVER",
                "events": [{"introduced": "1.2.2"}, {"fixed": "1.2.4"}],
            }],
        }]
    }

    assert TOOL_MODULE._lowest_matching_affected_version(advisory, package) == "1.2.2"


def test_range_check_handles_osv_zero_introduction_boundary():
    package = TOOL_MODULE.PackageVersion(
        name="react", version="", ecosystem="npm", manifest="package.json", constraint="1.2"
    )
    advisory = {
        "affected": [{
            "package": {"name": "react", "ecosystem": "npm"},
            "ranges": [{
                "type": "SEMVER",
                "events": [{"introduced": "0"}, {"fixed": "1.2.2"}],
            }],
        }]
    }

    assert TOOL_MODULE._lowest_matching_affected_version(advisory, package) == "1.2.0"


def test_range_check_ignores_advisory_outside_manifest_range():
    package = TOOL_MODULE.PackageVersion(
        name="react", version="", ecosystem="npm", manifest="package.json", constraint="^1.2.0"
    )
    advisory = {
        "affected": [{
            "package": {"name": "react", "ecosystem": "npm"},
            "ranges": [{
                "type": "SEMVER",
                "events": [{"introduced": "2.0.0"}, {"fixed": "2.1.0"}],
            }],
        }]
    }

    assert TOOL_MODULE._lowest_matching_affected_version(advisory, package) is None


def test_audit_root_accepts_absolute_path_outside_project(tmp_path: Path):
    project = tmp_path / "project"
    outside = tmp_path / "outside"
    project.mkdir()
    outside.mkdir()

    assert TOOL_MODULE._resolve_audit_root(project, str(outside)) == outside.resolve()


def test_audit_root_rejects_relative_path_traversal(tmp_path: Path):
    project = tmp_path / "project"
    outside = tmp_path / "outside"
    project.mkdir()
    outside.mkdir()

    try:
        TOOL_MODULE._resolve_audit_root(project, "../outside")
    except ValueError as exc:
        assert "Relative audit paths must stay inside" in str(exc)
    else:
        raise AssertionError("relative path traversal was accepted")


def test_manifest_file_path_rules_are_checked_before_reading(tmp_path: Path):
    folder = tmp_path / "project"
    folder.mkdir()
    manifest = folder / "requirements.txt"
    manifest.write_text("requests==2.31.0\n", encoding="utf-8")
    checker = PermissionChecker(
        PermissionSettings(path_rules=[PathRuleConfig(pattern=str(manifest.resolve()), allow=False)])
    )

    packages, errors, manifests = TOOL_MODULE._read_manifests(
        folder,
        cwd=tmp_path,
        permission_checker=checker,
    )

    assert packages == []
    assert manifests == []
    assert "denied by OpenHarness permission rules" in errors[0]


def test_severity_is_unknown_when_osv_does_not_supply_a_known_level():
    assert TOOL_MODULE._severity({"severity": [{"type": "CVSS_V3", "score": "CVSS:3.1/..."}]}) == "UNKNOWN"
    assert TOOL_MODULE._severity({"database_specific": {"severity": "high"}}) == "HIGH"
    assert TOOL_MODULE._severity({"database_specific": {"severity": "MODERATE"}}) == "MEDIUM"


def test_severity_uses_cvss_v3_vector_when_database_severity_is_missing():
    advisory = {
        "severity": [{
            "type": "CVSS_V3",
            "score": "CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:U/C:H/I:H/A:H",
        }]
    }
    assert TOOL_MODULE._cvss_v3_base_score(advisory["severity"][0]["score"]) == 9.8
    assert TOOL_MODULE._severity(advisory) == "CRITICAL"
    assert TOOL_MODULE._cvss_v3_base_score("CVSS:3.1/AV:N") is None


@pytest.mark.asyncio
async def test_osv_json_reader_rejects_responses_over_the_byte_limit():
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, json={"payload": "too large"}, request=request)
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(ValueError, match="size limit"):
            await TOOL_MODULE._request_json(client, "GET", "https://api.osv.dev/example", max_bytes=2)
