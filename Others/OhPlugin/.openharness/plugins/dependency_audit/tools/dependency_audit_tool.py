"""Read-only dependency manifest audit backed by OSV.dev."""

from __future__ import annotations

import asyncio
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field

from openharness.tools.base import BaseTool, ToolExecutionContext, ToolResult
from openharness.utils.network_guard import NetworkGuardError, ensure_public_http_url

OSV_QUERY_URL = "https://api.osv.dev/v1/querybatch"
OSV_VULN_URL = "https://api.osv.dev/v1/vulns/"
MAX_MANIFEST_BYTES = 1_000_000
MAX_PACKAGES = 100
MAX_ADVISORIES = 300
MAX_BATCH_RESPONSE_BYTES = 8_000_000
MAX_ADVISORY_RESPONSE_BYTES = 512_000
OSV_TOTAL_TIMEOUT_SECONDS = 180.0
LAST_RESULT_KEY = "dependency_audit_last_result"


class DependencyAuditInput(BaseModel):
    action: Literal["audit", "summary"] = Field(default="audit")
    path: str | None = Field(default=None, description="Folder containing requirements.txt and/or package.json")


class PackageVersion(BaseModel):
    name: str
    version: str
    ecosystem: Literal["PyPI", "npm"]
    manifest: str
    constraint: str | None = None


class DependencyAuditTool(BaseTool):
    name = "dependency_audit"
    description = (
        "Audit requirements.txt and package.json files directly inside a relative or absolute folder "
        "path against OSV.dev. "
        "Use action=summary to retrieve the most recent audit in this session. Read-only."
    )
    input_model = DependencyAuditInput

    def is_read_only(self, arguments: DependencyAuditInput) -> bool:
        del arguments
        return True

    async def execute(self, arguments: DependencyAuditInput, context: ToolExecutionContext) -> ToolResult:
        if arguments.action == "summary":
            state = context.session_state if isinstance(context.session_state, dict) else context.metadata
            result = state.get(LAST_RESULT_KEY)
            if not isinstance(result, dict):
                return ToolResult(output=json.dumps({"status": "no_previous_audit", "findings": []}))
            return ToolResult(output=json.dumps(result, indent=2), metadata={"audit": result})

        if not arguments.path:
            return _error("A folder path is required for an audit.")
        try:
            root = _resolve_audit_root(context.cwd, arguments.path)
            packages, errors, manifest_names = _read_manifests(
                root,
                cwd=context.cwd,
                permission_checker=context.metadata.get("permission_checker"),
            )
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return _error(str(exc))

        if not manifest_names and errors:
            result = _audit_result(
                status="incomplete",
                root=root,
                manifests=manifest_names,
                packages=packages,
                findings=[],
                errors=errors,
            )
            state = context.session_state if isinstance(context.session_state, dict) else context.metadata
            state[LAST_RESULT_KEY] = result
            return ToolResult(output=json.dumps(result, indent=2), metadata={"audit": result})
        if not manifest_names:
            return _error("No supported manifest found. Expected requirements.txt and/or package.json in that folder.")
        if len(packages) > MAX_PACKAGES:
            return _error(f"Manifest package count exceeds the limit of {MAX_PACKAGES}.")

        findings: list[dict[str, Any]] = []
        if packages:
            try:
                findings = await asyncio.wait_for(
                    _query_osv(packages),
                    timeout=OSV_TOTAL_TIMEOUT_SECONDS,
                )
            except (asyncio.TimeoutError, httpx.HTTPError, NetworkGuardError, ValueError) as exc:
                result = _audit_result(
                    status="failed",
                    root=root,
                    manifests=manifest_names,
                    packages=packages,
                    findings=[],
                    errors=[*errors, f"OSV query failed: {exc}"],
                )
                state = context.session_state if isinstance(context.session_state, dict) else context.metadata
                state[LAST_RESULT_KEY] = result
                return ToolResult(output=json.dumps(result, indent=2), is_error=True, metadata={"audit": result})

        status = "incomplete" if errors else "completed"
        result = _audit_result(
            status=status,
            root=root,
            manifests=manifest_names,
            packages=packages,
            findings=findings,
            errors=errors,
        )
        state = context.session_state if isinstance(context.session_state, dict) else context.metadata
        state[LAST_RESULT_KEY] = result
        return ToolResult(output=json.dumps(result, indent=2), metadata={"audit": result})


def _error(message: str) -> ToolResult:
    return ToolResult(output=json.dumps({"status": "failed", "findings": [], "errors": [message]}), is_error=True)


def _resolve_audit_root(cwd: Path, candidate: str) -> Path:
    root = cwd.resolve()
    candidate = candidate.strip()
    if len(candidate) >= 2 and candidate[0] == candidate[-1] and candidate[0] in {"'", '"'}:
        candidate = candidate[1:-1]
    requested = Path(candidate).expanduser()
    is_relative = not requested.is_absolute()
    if is_relative:
        requested = root / requested
    resolved = requested.resolve(strict=True)
    if is_relative:
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError(
                "Relative audit paths must stay inside the current project directory; "
                "use an absolute path for another folder."
            ) from exc
    if not resolved.is_dir():
        raise ValueError("The audit path must name a folder.")
    return resolved


def _read_manifests(
    root: Path,
    *,
    cwd: Path,
    permission_checker: Any = None,
) -> tuple[list[PackageVersion], list[str], list[str]]:
    packages: list[PackageVersion] = []
    errors: list[str] = []
    found: list[str] = []
    for filename in ("requirements.txt", "package.json"):
        path = root / filename
        if not path.exists():
            continue
        resolved = path.resolve(strict=True)
        try:
            resolved.relative_to(root)
        except ValueError:
            errors.append(f"{filename} resolves outside the selected folder and was skipped.")
            continue
        if not resolved.is_file():
            errors.append(f"{filename} is not a regular file and was skipped.")
            continue
        if permission_checker is not None:
            decision = permission_checker.evaluate(
                "dependency_audit",
                is_read_only=True,
                file_path=str(resolved),
            )
            if not decision.allowed:
                errors.append(f"{filename} was denied by OpenHarness permission rules: {decision.reason}")
                continue
        from openharness.sandbox.session import is_docker_sandbox_active

        if is_docker_sandbox_active():
            from openharness.sandbox.path_validator import validate_sandbox_path

            allowed, reason = validate_sandbox_path(resolved, cwd)
            if not allowed:
                errors.append(f"{filename} was denied by the active sandbox: {reason}")
                continue
        if resolved.stat().st_size > MAX_MANIFEST_BYTES:
            errors.append(f"{filename} exceeds the {MAX_MANIFEST_BYTES}-byte size limit and was skipped.")
            continue
        text = resolved.read_text(encoding="utf-8")
        found.append(filename)
        try:
            if filename == "requirements.txt":
                parsed, skipped = _parse_requirements(text, filename)
            else:
                parsed, skipped = _parse_package_json(text, filename)
        except ValueError as exc:
            errors.append(str(exc))
            continue
        packages.extend(parsed)
        errors.extend(skipped)
    if len(packages) > MAX_PACKAGES:
        return packages, errors, found
    return packages, errors, found


def _parse_requirements(text: str, manifest: str) -> tuple[list[PackageVersion], list[str]]:
    packages: list[PackageVersion] = []
    errors: list[str] = []
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        line = line.split(";", 1)[0].strip()
        if line.startswith(("-r", "--requirement", "-e", "--editable")):
            errors.append(f"{manifest}:{line_number}: include and editable requirements are unsupported.")
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.-]+)(?:\[[^]]+\])?\s*(===|==)\s*([A-Za-z0-9][A-Za-z0-9.+!_-]*)", line)
        if not match:
            errors.append(f"{manifest}:{line_number}: skipped non-exact or unsupported requirement.")
            continue
        name = re.sub(r"[-_.]+", "-", match.group(1)).lower()
        packages.append(PackageVersion(name=name, version=match.group(3), ecosystem="PyPI", manifest=manifest))
    return packages, errors


def _parse_package_json(text: str, manifest: str) -> tuple[list[PackageVersion], list[str]]:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"{manifest} is invalid JSON: {exc.msg} at line {exc.lineno}.") from exc
    if not isinstance(data, dict):
        raise ValueError(f"{manifest} must contain a JSON object.")
    packages: list[PackageVersion] = []
    errors: list[str] = []
    for section in ("dependencies", "devDependencies", "optionalDependencies"):
        dependencies = data.get(section, {})
        if not isinstance(dependencies, dict):
            errors.append(f"{manifest}: {section} must be an object and was skipped.")
            continue
        for name, constraint in dependencies.items():
            exact_version = (
                isinstance(constraint, str)
                and re.fullmatch(r"v?[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?", constraint)
            )
            if not isinstance(name, str) or not isinstance(constraint, str):
                errors.append(f"{manifest}: skipped {name!s}; dependency name and version must be strings.")
                continue
            if not exact_version and _npm_range_intervals(constraint) is None:
                errors.append(f"{manifest}: skipped {name!s}; unsupported npm version range {constraint!r}.")
                continue
            packages.append(
                PackageVersion(
                    name=name,
                    version=constraint.removeprefix("v") if exact_version else "",
                    ecosystem="npm",
                    manifest=manifest,
                    constraint=None if exact_version else constraint,
                )
            )
    return packages, errors


def _semver_tuple(value: Any) -> tuple[int, int, int] | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:\+[A-Za-z0-9.-]+)?", value)
    if not match:
        return None
    return tuple(int(part) for part in match.groups())


def _npm_range_intervals(
    constraint: str,
) -> list[tuple[tuple[int, int, int], tuple[int, int, int] | None]] | None:
    """Parse a conservative subset of npm ranges as inclusive-low/exclusive-high intervals."""
    intervals = []
    for alternative in constraint.split("||"):
        raw = alternative.strip()
        if not raw:
            return None
        if raw.startswith(("^", "~")):
            operator, raw = raw[0], raw[1:].strip()
        else:
            operator = ""
        if operator:
            parsed = _npm_partial_version(raw)
            if parsed is None:
                return None
            low, high = parsed
            major, minor, patch = low
            if operator == "^":
                if major:
                    high = (major + 1, 0, 0)
                elif minor:
                    high = (0, minor + 1, 0)
                elif raw.count(".") < 2:
                    high = (1, 0, 0) if raw.count(".") == 0 else (0, 1, 0)
                else:
                    high = (0, 0, patch + 1)
            elif raw.count(".") == 0:
                high = (major + 1, 0, 0)
            else:
                high = (major, minor + 1, 0)
            intervals.append((low, high))
            continue

        terms = raw.split()
        if len(terms) == 1:
            parsed = _npm_partial_version(terms[0])
            if parsed is None:
                return None
            intervals.append(parsed)
            continue
        low, high = (0, 0, 0), None
        for term in terms:
            if term.startswith(">="):
                bound = _semver_tuple(term[2:])
                if bound is None or bound > low:
                    if bound is None:
                        return None
                    low = bound
            elif term.startswith("<") and not term.startswith("<="):
                bound = _semver_tuple(term[1:])
                if bound is None or high is None or bound < high:
                    if bound is None:
                        return None
                    high = bound
            else:
                return None
        intervals.append((low, high))
    return intervals


def _npm_partial_version(
    raw: str,
) -> tuple[tuple[int, int, int], tuple[int, int, int] | None] | None:
    raw = raw.removeprefix("v")
    parts = raw.split(".")
    if len(parts) > 3 or not parts:
        return None
    wildcard_index = next((i for i, part in enumerate(parts) if part.lower() in {"x", "*"}), None)
    if any(not part.isdigit() and part.lower() not in {"x", "*"} for part in parts):
        return None
    if wildcard_index is not None and any(part.isdigit() for part in parts[wildcard_index + 1:]):
        return None
    nums = [int(part) if part.isdigit() else 0 for part in parts]
    if wildcard_index is not None:
        nums = (nums + [0, 0, 0])[:3]
        low = tuple(nums)
        if wildcard_index == 0:
            return low, None
        high_values = list(low)
        high_values[wildcard_index - 1] += 1
        for index in range(wildcard_index, 3):
            high_values[index] = 0
        return low, tuple(high_values)
    nums = (nums + [0, 0, 0])[:3]
    low = tuple(nums)
    if len(parts) == 1:
        return low, (nums[0] + 1, 0, 0)
    if len(parts) == 2:
        return low, (nums[0], nums[1] + 1, 0)
    return low, (nums[0], nums[1], nums[2] + 1)


def _osv_query(package: PackageVersion) -> dict[str, Any]:
    query: dict[str, Any] = {"package": {"name": package.name, "ecosystem": package.ecosystem}}
    if package.constraint is None:
        query["version"] = package.version
    return query


def _lowest_matching_affected_version(advisory: dict[str, Any], package: PackageVersion) -> str | None:
    manifest_ranges = _npm_range_intervals(package.constraint or "")
    if manifest_ranges is None:
        raise ValueError(f"Unsupported npm version range {package.constraint!r}.")
    affected = advisory.get("affected", [])
    if not isinstance(affected, list):
        raise ValueError("OSV advisory contains malformed affected package data.")
    candidates: list[tuple[int, int, int]] = []
    for entry in affected:
        if not isinstance(entry, dict):
            raise ValueError("OSV advisory contains malformed affected package data.")
        affected_package = entry.get("package")
        if not isinstance(affected_package, dict) or affected_package.get("name") != package.name:
            continue
        if affected_package.get("ecosystem") not in {None, package.ecosystem}:
            continue
        versions = entry.get("versions", [])
        if not isinstance(versions, list):
            raise ValueError("OSV advisory contains malformed affected versions.")
        listed_candidates = []
        for version in versions:
            parsed = _semver_tuple(version)
            if parsed is not None and any(low <= parsed and (high is None or parsed < high)
                                          for low, high in manifest_ranges):
                listed_candidates.append(parsed)
        range_candidates = []
        ranges = entry.get("ranges", [])
        if not isinstance(ranges, list):
            raise ValueError("OSV advisory contains malformed affected ranges.")
        for affected_range in ranges:
            if not isinstance(affected_range, dict):
                raise ValueError("OSV advisory contains malformed affected ranges.")
            if affected_range.get("type") != "SEMVER":
                raise ValueError("OSV returned a range type this npm range checker cannot evaluate.")
            events = affected_range.get("events", [])
            if not isinstance(events, list):
                raise ValueError("OSV advisory contains malformed range events.")
            start = None
            for event in events:
                if not isinstance(event, dict):
                    raise ValueError("OSV advisory contains malformed range events.")
                if "introduced" in event:
                    start = (0, 0, 0) if event["introduced"] == "0" else _semver_tuple(event["introduced"])
                    if start is None:
                        raise ValueError("OSV returned an unsupported introduced version.")
                elif "fixed" in event or "last_affected" in event:
                    end_key = "fixed" if "fixed" in event else "last_affected"
                    end = _semver_tuple(event[end_key])
                    if end is None:
                        raise ValueError("OSV returned an unsupported affected range boundary.")
                    inclusive_end = end_key == "last_affected"
                    if start is not None:
                        for low, high in manifest_ranges:
                            candidate = max(start, low)
                            if (high is None or candidate < high) and (candidate < end or (inclusive_end and candidate == end)):
                                range_candidates.append(candidate)
                    start = None
            if start is not None:
                for low, high in manifest_ranges:
                    candidate = max(start, low)
                    if high is None or candidate < high:
                        range_candidates.append(candidate)
        candidates.extend(listed_candidates or range_candidates)
    if not candidates:
        return None
    candidate = min(candidates)
    return ".".join(str(part) for part in candidate)


async def _query_osv(packages: list[PackageVersion]) -> list[dict[str, Any]]:
    if not packages:
        return []
    await ensure_public_http_url(OSV_QUERY_URL)
    timeout = httpx.Timeout(connect=5.0, read=25.0, write=10.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
        body = await _request_json(
            client,
            "POST",
            OSV_QUERY_URL,
            max_bytes=MAX_BATCH_RESPONSE_BYTES,
            json={
                "queries": [_osv_query(package) for package in packages]
            },
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        results = body.get("results") if isinstance(body, dict) else None
        if not isinstance(results, list) or len(results) != len(packages):
            raise ValueError("OSV returned an invalid batch response.")
        advisory_ids: list[tuple[int, str]] = []
        for index, item in enumerate(results):
            if not isinstance(item, dict):
                raise ValueError("OSV returned a malformed result entry.")
            vulns = item.get("vulns", [])
            if not isinstance(vulns, list):
                raise ValueError("OSV returned a malformed vulnerabilities list.")
            for vuln in vulns:
                if not isinstance(vuln, dict) or not isinstance(vuln.get("id"), str):
                    raise ValueError("OSV returned a malformed advisory reference.")
                advisory_id = vuln["id"]
                if not re.fullmatch(r"[A-Za-z0-9._-]{1,200}", advisory_id):
                    raise ValueError("OSV returned an invalid advisory identifier.")
                advisory_ids.append((index, advisory_id))
        if len(advisory_ids) > MAX_ADVISORIES:
            raise ValueError(f"OSV response exceeds the {MAX_ADVISORIES}-advisory limit.")

        await ensure_public_http_url(OSV_VULN_URL)
        semaphore = asyncio.Semaphore(10)

        async def _fetch_finding(index: int, advisory_id: str) -> dict[str, Any] | None:
            async with semaphore:
                detail = await _request_json(
                    client,
                    "GET",
                    OSV_VULN_URL + advisory_id,
                    max_bytes=MAX_ADVISORY_RESPONSE_BYTES,
                    headers={"Accept": "application/json"},
                )
            if not isinstance(detail, dict):
                raise ValueError(f"OSV returned a malformed advisory for {advisory_id}.")
            package = packages[index]
            aliases = detail.get("aliases", [])
            if not isinstance(aliases, list):
                aliases = []
            candidate_version = None
            if package.constraint is not None:
                candidate_version = _lowest_matching_affected_version(detail, package)
                if candidate_version is None:
                    return None
            return {
                "package": package.name,
                "version": candidate_version or package.version,
                "manifest": package.manifest,
                **({"declared_version": package.constraint, "candidate_version": candidate_version}
                   if package.constraint is not None else {}),
                "vulnerability_id": advisory_id,
                "aliases": [alias for alias in aliases if isinstance(alias, str)],
                "severity": _severity(detail),
                "severity_data": detail.get("severity", []) if isinstance(detail.get("severity"), list) else [],
                "summary": detail.get("summary") if isinstance(detail.get("summary"), str) else "",
                "source": "OSV",
            }

        results = await asyncio.gather(*(_fetch_finding(index, advisory_id) for index, advisory_id in advisory_ids))
        return [finding for finding in results if finding is not None]


async def _request_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_bytes: int,
    **kwargs: Any,
) -> Any:
    chunks = bytearray()
    async with client.stream(method, url, **kwargs) as response:
        response.raise_for_status()
        content_length = response.headers.get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > max_bytes:
            raise ValueError("OSV response exceeded the configured size limit.")
        async for chunk in response.aiter_bytes():
            if len(chunks) + len(chunk) > max_bytes:
                raise ValueError("OSV response exceeded the configured size limit.")
            chunks.extend(chunk)
    try:
        return json.loads(chunks)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("OSV returned invalid JSON.") from exc


def _severity(advisory: dict[str, Any]) -> str:
    database_specific = advisory.get("database_specific")
    if isinstance(database_specific, dict):
        severity = database_specific.get("severity")
        if isinstance(severity, str):
            normalized = severity.upper()
            if normalized == "MODERATE":
                return "MEDIUM"
            if normalized in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}:
                return normalized
    severity_data = advisory.get("severity")
    if isinstance(severity_data, list):
        for item in severity_data:
            if not isinstance(item, dict) or item.get("type") != "CVSS_V3":
                continue
            score = _cvss_v3_base_score(item.get("score"))
            if score is not None:
                if score >= 9.0:
                    return "CRITICAL"
                if score >= 7.0:
                    return "HIGH"
                if score >= 4.0:
                    return "MEDIUM"
                return "LOW"
    return "UNKNOWN"


def _cvss_v3_base_score(vector: Any) -> float | None:
    """Calculate a CVSS v3.0/v3.1 base score from a complete base vector."""
    if not isinstance(vector, str):
        return None
    parts = vector.split("/")
    if not parts or parts[0] not in {"CVSS:3.0", "CVSS:3.1"}:
        return None
    metrics: dict[str, str] = {}
    for part in parts[1:]:
        if ":" not in part:
            return None
        key, value = part.split(":", 1)
        if key in metrics:
            return None
        metrics[key] = value
    weights = {
        "AV": {"N": .85, "A": .62, "L": .55, "P": .2},
        "AC": {"L": .77, "H": .44},
        "PR": {"N": 0, "L": 0, "H": 0},
        "UI": {"N": .85, "R": .62},
        "S": {"U": "U", "C": "C"},
        "C": {"H": .56, "L": .22, "N": 0},
        "I": {"H": .56, "L": .22, "N": 0},
        "A": {"H": .56, "L": .22, "N": 0},
    }
    required = ("AV", "AC", "PR", "UI", "S", "C", "I", "A")
    if any(key not in metrics or metrics[key] not in weights[key] for key in required):
        return None
    scope_changed = metrics["S"] == "C"
    pr_values = {"N": .85, "L": .68 if scope_changed else .62, "H": .5 if scope_changed else .27}
    exploitability = 8.22 * weights["AV"][metrics["AV"]] * weights["AC"][metrics["AC"]] * pr_values[metrics["PR"]] * weights["UI"][metrics["UI"]]
    impact_sub = 1 - (1 - weights["C"][metrics["C"]]) * (1 - weights["I"][metrics["I"]]) * (1 - weights["A"][metrics["A"]])
    if impact_sub == 0:
        return 0.0
    impact = 6.42 * impact_sub if not scope_changed else 7.52 * (impact_sub - .029) - 3.25 * (impact_sub - .02) ** 15
    score = min(impact + exploitability, 10) if not scope_changed else min(1.08 * (impact + exploitability), 10)
    if parts[0] == "CVSS:3.0":
        score = math.floor(score * 10 + 0.5) / 10
    else:
        score = math.ceil(score * 10 - 1e-9) / 10
    score = min(score, 10)
    return score


def _audit_result(
    *, status: str, root: Path, manifests: list[str], packages: list[PackageVersion],
    findings: list[dict[str, Any]], errors: list[str],
) -> dict[str, Any]:
    return {
        "status": status,
        "folder": str(root),
        "manifests": manifests,
        "packages_scanned": len(packages),
        "vulnerable_packages": len({(item["manifest"], item["package"], item["version"]) for item in findings}),
        "findings": findings,
        "errors": errors,
        "source": "OSV.dev",
        "retrieved_at": datetime.now(timezone.utc).isoformat(),
    }
