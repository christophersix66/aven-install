#!/usr/bin/env python3
"""Thin verified entrypoint into the released Aven bootstrap."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from typing import Any, Mapping, Sequence


CHANNEL_SCHEMA = "aven-install.channel.v1"
UNAVAILABLE_SCHEMA = "aven-install.channel-unavailable.v1"
EXPECTED_REPOSITORY = "christophersix66/intelligence-workbench"
INSTALLER_VERSION = "1.0.0"
MINIMUM_TOOL_VERSIONS = {"git": (2, 20, 0), "gh": (2, 0, 0)}
APPROVED_RC = {
    "schema": CHANNEL_SCHEMA,
    "channel": "rc",
    "version": "1.0.0-rc.15",
    "repository": EXPECTED_REPOSITORY,
    "tag": "v1.0.0-rc.15",
    "commit": "ef44b9c325cfdf00195e875c8ceed5964ccbc78f",
    "asset": "aven-v1.0.0-rc.15-bootstrap-ef44b9c325cf.tar",
    "asset_size": 471040,
    "sha256": "b3823e7f6cdda9a35dde910089122f795f62fe19588672d5de124cd5624134ed",
    "checksum_asset": "aven-v1.0.0-rc.15-bootstrap-ef44b9c325cf.tar.sha256",
    "build_report_asset": "aven-v1.0.0-rc.15-bootstrap-ef44b9c325cf.build.json",
    "installation_lock_sha256": "c8a76155830a049383e57fd5f4b9fb538437032db3974afec2086d961837ceba",
    "workbench_runtime_commit": "d1f85f840fb4a0fd505e43a043febafba2785dee",
    "prerelease": True,
}
APPROVED_PREDECESSORS = ({
    "aven_version": "1.0.0-rc.14",
    "installation_lock_sha256": "e2763a208c2d75de6c4b59fa82c845f6a0fdf80d46efec638835b2c7e8545b7c",
    "workbench_commit": "e0bb0630753c4b525d5033506c9f78fa3eead7db",
    "bootstrap_source_commit": "78c3ec5914160f3464663dfa1cd54f9bbfa4a040",
    "bootstrap_manifest_sha256": "5c5af1b7aa457b0198b84310ad4fcc2995167cc5070bf4336605bbeccd579b98",
},)
MAX_MANIFEST_BYTES = 16_384
MAX_RELEASE_JSON_BYTES = 2_000_000
MAX_ARCHIVE_MEMBERS = 128
MAX_ARCHIVE_BYTES = 16 * 1024 * 1024
SAFE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")


class InstallerError(Exception):
    """Expected bounded installer failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _object_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InstallerError("RELEASE_MANIFEST_INVALID", "duplicate JSON key")
        result[key] = value
    return result


def _load_json(payload: bytes, *, code: str, limit: int) -> Mapping[str, Any]:
    if not payload or len(payload) > limit:
        raise InstallerError(code, "JSON input is empty or exceeds its bound")
    try:
        value = json.loads(
            payload.decode("utf-8"),
            object_pairs_hook=_object_pairs,
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except (UnicodeError, ValueError, json.JSONDecodeError) as error:
        raise InstallerError(code, "JSON input is malformed") from error
    if not isinstance(value, dict):
        raise InstallerError(code, "JSON input must be an object")
    return value


def load_channel(path: Path, requested_channel: str) -> Mapping[str, Any]:
    try:
        payload = path.read_bytes()
    except OSError as error:
        raise InstallerError("RELEASE_MANIFEST_INVALID", "channel manifest is unreadable") from error
    value = _load_json(payload, code="RELEASE_MANIFEST_INVALID", limit=MAX_MANIFEST_BYTES)
    if value.get("schema") == UNAVAILABLE_SCHEMA:
        if set(value) != {"schema", "channel", "status", "reason"}:
            raise InstallerError("RELEASE_MANIFEST_INVALID", "unavailable channel manifest has unexpected fields")
        if value.get("channel") != requested_channel or value.get("status") != "UNAVAILABLE":
            raise InstallerError("RELEASE_MANIFEST_INVALID", "unavailable channel manifest is inconsistent")
        raise InstallerError("STABLE_RELEASE_UNAVAILABLE", str(value.get("reason", "selected channel is unavailable")))

    expected_keys = {
        "schema", "channel", "version", "repository", "tag", "commit",
        "asset", "asset_size", "sha256", "checksum_asset", "build_report_asset",
        "installation_lock_sha256", "workbench_runtime_commit", "prerelease",
    }
    if set(value) != expected_keys or value.get("schema") != CHANNEL_SCHEMA:
        raise InstallerError("RELEASE_MANIFEST_INVALID", "channel manifest schema or fields are invalid")
    for field in ("channel", "version", "tag", "asset", "checksum_asset", "build_report_asset"):
        item = value.get(field)
        if not isinstance(item, str) or SAFE_TOKEN.fullmatch(item) is None:
            raise InstallerError("RELEASE_MANIFEST_INVALID", f"unsafe {field}")
    if value["channel"] != requested_channel:
        raise InstallerError("RELEASE_MANIFEST_INVALID", "selected channel does not match manifest")
    if value.get("repository") != EXPECTED_REPOSITORY:
        raise InstallerError("RELEASE_MANIFEST_INVALID", "unexpected release repository")
    if not isinstance(value.get("commit"), str) or HEX40.fullmatch(value["commit"]) is None:
        raise InstallerError("RELEASE_MANIFEST_INVALID", "invalid source commit")
    for field in ("sha256", "installation_lock_sha256"):
        if not isinstance(value.get(field), str) or HEX64.fullmatch(value[field]) is None:
            raise InstallerError("RELEASE_MANIFEST_INVALID", f"invalid {field}")
    runtime = value.get("workbench_runtime_commit")
    if not isinstance(runtime, str) or HEX40.fullmatch(runtime) is None:
        raise InstallerError("RELEASE_MANIFEST_INVALID", "invalid Workbench runtime commit")
    if type(value.get("asset_size")) is not int or not 1 <= value["asset_size"] <= MAX_ARCHIVE_BYTES:
        raise InstallerError("RELEASE_MANIFEST_INVALID", "invalid asset size")
    if type(value.get("prerelease")) is not bool:
        raise InstallerError("RELEASE_MANIFEST_INVALID", "invalid release posture")
    expected_asset = f"aven-v{value['version']}-bootstrap-{value['commit'][:12]}.tar"
    if value["tag"] != f"v{value['version']}" or value["asset"] != expected_asset:
        raise InstallerError("RELEASE_MANIFEST_INVALID", "version, tag, commit, and asset are not exactly bound")
    if value["checksum_asset"] != f"{expected_asset}.sha256":
        raise InstallerError("RELEASE_MANIFEST_INVALID", "checksum asset is not exactly bound")
    if value["build_report_asset"] != f"{expected_asset[:-4]}.build.json":
        raise InstallerError("RELEASE_MANIFEST_INVALID", "build report asset is not exactly bound")
    if value != APPROVED_RC:
        raise InstallerError(
            "RELEASE_IDENTITY_NOT_APPROVED",
            "the rc channel does not match the exact owner-approved Aven v1.0.0-rc.15 release",
        )
    return value


def _run(
    command: Sequence[str],
    *,
    timeout: int = 30,
    inherit: bool = False,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            list(command),
            cwd=cwd,
            env=env,
            stdin=None if inherit else subprocess.DEVNULL,
            stdout=None if inherit else subprocess.PIPE,
            stderr=None if inherit else subprocess.PIPE,
            text=True,
            timeout=timeout,
            check=False,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise InstallerError("COMMAND_FAILED", f"could not run {command[0]}") from error
    if not inherit and len((completed.stdout or "") + (completed.stderr or "")) > MAX_RELEASE_JSON_BYTES:
        raise InstallerError("COMMAND_OUTPUT_BOUND_EXCEEDED", f"{command[0]} output exceeded the installer bound")
    return completed


def _run_gh(
    gh: str,
    arguments: Sequence[str],
    *,
    timeout: int,
    inherit: bool = False,
    env: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ if env is None else env)
    environment["GH_TELEMETRY"] = "0"
    environment["GH_NO_UPDATE_NOTIFIER"] = "1"
    environment["GH_NO_EXTENSION_UPDATE_NOTIFIER"] = "1"
    temp_parent = os.environ.get("AVEN_INSTALL_TMPDIR")
    with tempfile.TemporaryDirectory(prefix="aven-install-gh-state-", dir=temp_parent) as state_directory:
        environment["XDG_STATE_HOME"] = state_directory
        if os.name == "nt":
            environment["LOCALAPPDATA"] = state_directory
        return _run((gh, *arguments), timeout=timeout, inherit=inherit, cwd=Path.home(), env=environment)


def _resolve_executable(command: str) -> str | None:
    path = shutil.which(command)
    if not path:
        return None
    if not Path(path).is_absolute():
        raise InstallerError("UNTRUSTED_EXECUTABLE_PATH", f"refusing relative executable path for {command}")
    try:
        resolved = Path(path).resolve(strict=True)
        current = Path.cwd().resolve(strict=True)
    except OSError as error:
        raise InstallerError("UNTRUSTED_EXECUTABLE_PATH", f"could not resolve {command} safely") from error
    if resolved == current or resolved.parent == current:
        raise InstallerError("UNTRUSTED_EXECUTABLE_PATH", f"refusing {command} from the current working directory")
    return str(resolved)


def _version(command: str) -> tuple[str, str] | None:
    path = _resolve_executable(command)
    if path is None:
        return None
    completed = _run_gh(path, ("--version",), timeout=10) if command == "gh" else _run((path, "--version"), timeout=10)
    if completed.returncode != 0:
        return path, "UNUSABLE"
    line = (completed.stdout or completed.stderr).splitlines()
    return path, line[0][:160] if line else "AVAILABLE"


def _numeric_version(name: str, text: str) -> tuple[int, int, int] | None:
    patterns = {
        "git": r"\bgit version (\d+)\.(\d+)(?:\.(\d+))?",
        "gh": r"\bgh version (\d+)\.(\d+)(?:\.(\d+))?",
    }
    match = re.search(patterns[name], text, flags=re.IGNORECASE)
    if match is None:
        return None
    return tuple(int(item or 0) for item in match.groups())


def _usable_tool(name: str, observed: tuple[str, str] | None) -> bool:
    if observed is None or observed[1] == "UNUSABLE":
        return False
    version = _numeric_version(name, observed[1])
    return version is not None and version >= MINIMUM_TOOL_VERSIONS[name]


def platform_identity() -> tuple[str, str]:
    observed = platform.system().lower()
    system = "macos" if observed == "darwin" else observed
    architecture = platform.machine().lower()
    aliases = {"amd64": "x86_64", "aarch64": "arm64"}
    architecture = aliases.get(architecture, architecture)
    if system not in {"linux", "macos", "windows"}:
        raise InstallerError("UNSUPPORTED_OS", f"unsupported operating system: {system}")
    if architecture not in {"x86_64", "arm64"}:
        raise InstallerError("UNSUPPORTED_ARCHITECTURE", f"unsupported architecture: {architecture}")
    return system, architecture


def _sudo_prefix() -> list[str]:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return []
    sudo = _resolve_executable("sudo")
    if sudo:
        return [sudo]
    raise InstallerError("PRIVILEGE_TOOL_UNAVAILABLE", "required package installation needs sudo or an administrator shell")


def prerequisite_install_commands(system: str, missing: Sequence[str]) -> list[list[str]]:
    if not missing:
        return []
    package_names = {"git": "git", "gh": "gh"}
    brew = _resolve_executable("brew") if system == "macos" else None
    if brew:
        return [[brew, "install", *(package_names[item] for item in missing)]]
    winget = _resolve_executable("winget") if system == "windows" else None
    if winget:
        identifiers = {"git": "Git.Git", "gh": "GitHub.cli"}
        return [
            [winget, "install", "--id", identifiers[item], "--exact", "--accept-package-agreements", "--accept-source-agreements"]
            for item in missing
        ]
    if system == "linux":
        prefix = _sudo_prefix()
        for manager, arguments in (
            ("apt-get", ("install", "-y")),
            ("dnf", ("install", "-y")),
            ("pacman", ("-S", "--needed")),
        ):
            executable = _resolve_executable(manager)
            if executable:
                return [[*prefix, executable, *arguments, *(package_names[item] for item in missing)]]
    raise InstallerError(
        "UNSUPPORTED_PACKAGE_MANAGER",
        "install Python 3.11+, Git, and GitHub CLI using the platform's supported package manager",
    )


def _prompt(question: str, *, assume_yes: bool, non_interactive: bool) -> bool:
    if assume_yes:
        return True
    if non_interactive:
        return False
    try:
        with open("/dev/tty", "r", encoding="utf-8") as reader, open("/dev/tty", "w", encoding="utf-8") as writer:
            writer.write(f"{question} [y/N] ")
            writer.flush()
            return reader.readline().strip().lower() in {"y", "yes"}
    except OSError:
        return input(f"{question} [y/N] ").strip().lower() in {"y", "yes"}


def ensure_required_tools(system: str, *, check_only: bool, assume_yes: bool, non_interactive: bool) -> Mapping[str, Mapping[str, str]]:
    observed = {name: _version(name) for name in ("git", "gh")}
    missing = [name for name, version in observed.items() if not _usable_tool(name, version)]
    if not missing:
        return {name: {"path": value[0], "version": value[1]} for name, value in observed.items() if value is not None}
    labels = ", ".join(missing)
    if check_only:
        raise InstallerError("PREREQUISITE_MISSING", f"missing or unusable required tools: {labels}")
    commands = prerequisite_install_commands(system, missing)
    print(f"Required prerequisites are missing: {labels}")
    for command in commands:
        print("Proposed command: " + " ".join(command))
    if not _prompt("Install the missing prerequisites? Elevation may be requested.", assume_yes=assume_yes, non_interactive=non_interactive):
        raise InstallerError("PREREQUISITE_INSTALL_DECLINED", "required prerequisite installation was not approved")
    for command in commands:
        if _run(command, timeout=600, inherit=True).returncode != 0:
            raise InstallerError("PREREQUISITE_INSTALL_FAILED", f"package manager failed while installing {labels}")
    observed = {name: _version(name) for name in ("git", "gh")}
    if any(not _usable_tool(name, value) for name, value in observed.items()):
        raise InstallerError("PREREQUISITE_INSTALL_FAILED", "required tools remain unavailable after package installation")
    return {name: {"path": value[0], "version": value[1]} for name, value in observed.items() if value is not None}


def ensure_github_access(gh: str, *, check_only: bool, assume_yes: bool, non_interactive: bool) -> None:
    if _run_gh(gh, ("auth", "status"), timeout=20).returncode != 0:
        if check_only:
            raise InstallerError("GITHUB_NOT_AUTHENTICATED", "GitHub CLI is not authenticated")
        print("GitHub authentication is required to acquire Aven's private components.")
        if not _prompt("Run GitHub CLI authentication now?", assume_yes=assume_yes, non_interactive=non_interactive):
            raise InstallerError("GITHUB_NOT_AUTHENTICATED", "run: gh auth login")
        if _run_gh(gh, ("auth", "login"), timeout=900, inherit=True).returncode != 0:
            raise InstallerError("GITHUB_NOT_AUTHENTICATED", "GitHub CLI authentication did not complete")
        if _run_gh(gh, ("auth", "status"), timeout=20).returncode != 0:
            raise InstallerError("GITHUB_NOT_AUTHENTICATED", "GitHub CLI remains unauthenticated")
    access = _run_gh(gh, ("api", f"repos/{EXPECTED_REPOSITORY}", "--jq", ".full_name"), timeout=30)
    if access.returncode != 0 or access.stdout.strip() != EXPECTED_REPOSITORY:
        raise InstallerError("GITHUB_REPOSITORY_ACCESS_DENIED", f"authenticated GitHub identity cannot read {EXPECTED_REPOSITORY}")


def resolve_release(gh: str, channel: Mapping[str, Any]) -> Mapping[str, Any]:
    repository = channel["repository"]
    tag = channel["tag"]
    tag_result = _run_gh(gh, ("api", f"repos/{repository}/git/ref/tags/{tag}"), timeout=30)
    if tag_result.returncode != 0:
        raise InstallerError("RELEASE_TAG_NOT_FOUND", "approved release tag is unavailable")
    tag_value = _load_json(tag_result.stdout.encode(), code="RELEASE_TAG_MISMATCH", limit=MAX_RELEASE_JSON_BYTES)
    target = tag_value.get("object")
    if isinstance(target, dict) and target.get("type") == "tag":
        tag_object_sha = target.get("sha")
        if not isinstance(tag_object_sha, str) or HEX40.fullmatch(tag_object_sha) is None:
            raise InstallerError("RELEASE_TAG_MISMATCH", "annotated release tag identity is invalid")
        annotated_result = _run_gh(
            gh,
            ("api", f"repos/{repository}/git/tags/{tag_object_sha}"),
            timeout=30,
        )
        if annotated_result.returncode != 0:
            raise InstallerError("RELEASE_TAG_MISMATCH", "annotated release tag is unavailable")
        annotated = _load_json(
            annotated_result.stdout.encode(),
            code="RELEASE_TAG_MISMATCH",
            limit=MAX_RELEASE_JSON_BYTES,
        )
        target = annotated.get("object")
    if not isinstance(target, dict) or target.get("type") != "commit" or target.get("sha") != channel["commit"]:
        raise InstallerError("RELEASE_TAG_MISMATCH", "approved release tag does not point to the declared commit")

    release_result = _run_gh(gh, ("api", f"repos/{repository}/releases/tags/{tag}"), timeout=30)
    if release_result.returncode != 0:
        raise InstallerError("RELEASE_NOT_FOUND", "approved GitHub release is unavailable")
    release = _load_json(release_result.stdout.encode(), code="RELEASE_MANIFEST_INVALID", limit=MAX_RELEASE_JSON_BYTES)
    if (
        release.get("tag_name") != tag
        or release.get("draft") is not False
        or release.get("prerelease") is not channel["prerelease"]
    ):
        raise InstallerError("RELEASE_TAG_MISMATCH", "GitHub release posture does not match the approved channel")
    assets = release.get("assets")
    if not isinstance(assets, list):
        raise InstallerError("RELEASE_ASSET_NOT_FOUND", "GitHub release assets are unavailable")
    named_assets = [item for item in assets if isinstance(item, dict) and isinstance(item.get("name"), str)]
    names = [item["name"] for item in named_assets]
    if len(names) != len(set(names)):
        raise InstallerError("RELEASE_ASSET_MISMATCH", "GitHub release contains ambiguous duplicate asset names")
    by_name = {item["name"]: item for item in named_assets}
    required = (channel["asset"], channel["checksum_asset"], channel["build_report_asset"])
    if any(name not in by_name for name in required):
        raise InstallerError("RELEASE_ASSET_NOT_FOUND", "an approved release asset is missing")
    canonical = by_name[channel["asset"]]
    if canonical.get("state") not in {None, "uploaded"} or canonical.get("size") != channel["asset_size"]:
        raise InstallerError("RELEASE_ASSET_MISMATCH", "canonical asset size does not match the channel")
    digest = canonical.get("digest")
    if digest is not None and digest != f"sha256:{channel['sha256']}":
        raise InstallerError("RELEASE_ASSET_MISMATCH", "GitHub asset digest does not match the channel")
    return release


def _conventional_aven(system: str) -> Path:
    home = Path.home()
    if system == "windows":
        data = Path(os.environ.get("LOCALAPPDATA", home / "AppData/Local"))
        return data / "aven/bin/aven.cmd"
    return home / ".local/bin/aven"


def inspect_existing_aven(system: str, channel: Mapping[str, Any]) -> str:
    conventional = _conventional_aven(system)
    if not conventional.is_file():
        return "NOT_INSTALLED"
    command = str(conventional)
    version = _run((command, "--json", "version"), timeout=30)
    if version.returncode != 0:
        raise InstallerError("AVEN_EXISTING_UNREADABLE", "an existing Aven command could not report exact version identity")
    value = _load_json(version.stdout.encode(), code="AVEN_EXISTING_UNREADABLE", limit=MAX_RELEASE_JSON_BYTES)
    same = (
        value.get("status") == "INSTALLED"
        and value.get("aven_version") == channel["version"]
        and value.get("installation_lock_sha256") == channel["installation_lock_sha256"]
        and value.get("workbench_commit") == channel["workbench_runtime_commit"]
    )
    distribution = value.get("distribution")
    approved_predecessor = next((
        predecessor for predecessor in APPROVED_PREDECESSORS
        if value.get("status") == "INSTALLED"
        and value.get("aven_version") == predecessor["aven_version"]
        and value.get("installation_lock_sha256") == predecessor["installation_lock_sha256"]
        and value.get("workbench_commit") == predecessor["workbench_commit"]
        and isinstance(distribution, dict)
        and distribution.get("bootstrap_source_commit") == predecessor["bootstrap_source_commit"]
        and distribution.get("bootstrap_manifest_sha256") == predecessor["bootstrap_manifest_sha256"]
    ), None)
    if not same and not approved_predecessor:
        raise InstallerError("AVEN_DIFFERENT_INSTALLATION", "a different Aven version or lock is installed; use Aven lifecycle commands explicitly")
    status = _run((command, "--json", "status"), timeout=60)
    if status.returncode != 0:
        raise InstallerError("AVEN_REPAIR_REQUIRED", "the exact installed Aven version is unhealthy; run: aven status")
    status_value = _load_json(status.stdout.encode(), code="AVEN_EXISTING_UNREADABLE", limit=MAX_RELEASE_JSON_BYTES)
    if status_value.get("status") != "HEALTHY":
        raise InstallerError("AVEN_REPAIR_REQUIRED", "the exact installed Aven version requires repair")
    return (
        "ALREADY_INSTALLED" if same
        else "APPROVED_PREDECESSOR:" + approved_predecessor["aven_version"]
    )


def download_release(gh: str, channel: Mapping[str, Any], destination: Path) -> None:
    command = [
        gh, "release", "download", channel["tag"],
        "--repo", channel["repository"], "--dir", str(destination),
    ]
    for name in (channel["asset"], channel["checksum_asset"], channel["build_report_asset"]):
        command.extend(("--pattern", name))
    completed = _run_gh(gh, tuple(command[1:]), timeout=300)
    if completed.returncode != 0:
        raise InstallerError("RELEASE_DOWNLOAD_FAILED", "GitHub CLI could not download the approved release assets")


def verify_download(channel: Mapping[str, Any], directory: Path) -> Path:
    archive = directory / channel["asset"]
    checksum_path = directory / channel["checksum_asset"]
    report_path = directory / channel["build_report_asset"]
    for path in (archive, checksum_path, report_path):
        if not path.is_file() or path.is_symlink():
            raise InstallerError("RELEASE_ASSET_NOT_FOUND", f"downloaded asset is missing: {path.name}")
    if archive.stat().st_size != channel["asset_size"]:
        raise InstallerError("ARTIFACT_SHA256_MISMATCH", "downloaded archive size is incorrect")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != channel["sha256"]:
        raise InstallerError("ARTIFACT_SHA256_MISMATCH", "downloaded archive digest is incorrect")
    try:
        checksum = checksum_path.read_text(encoding="utf-8").strip().split()
    except OSError as error:
        raise InstallerError("ARTIFACT_SHA256_MISMATCH", "checksum file is unreadable") from error
    if checksum != [channel["sha256"], channel["asset"]]:
        raise InstallerError("ARTIFACT_SHA256_MISMATCH", "checksum file does not exactly bind the archive")
    report = _load_json(report_path.read_bytes(), code="RELEASE_ASSET_MISMATCH", limit=MAX_MANIFEST_BYTES)
    if (
        report.get("artifact") != channel["asset"]
        or report.get("artifact_sha256") != channel["sha256"]
        or report.get("source_commit") != channel["commit"]
        or report.get("installation_lock_sha256") != channel["installation_lock_sha256"]
        or report.get("contains_credentials") is not False
        or report.get("contains_component_repositories") is not False
    ):
        raise InstallerError("RELEASE_ASSET_MISMATCH", "build report does not match the approved channel")
    return archive


def safe_extract(archive: Path, destination: Path) -> None:
    try:
        with tarfile.open(archive, mode="r:") as source:
            members = source.getmembers()
            if not members or len(members) > MAX_ARCHIVE_MEMBERS:
                raise InstallerError("ARCHIVE_UNSAFE", "archive member count is outside the allowed bound")
            names: set[str] = set()
            folded: set[str] = set()
            total = 0
            validated: list[tuple[tarfile.TarInfo, Path]] = []
            root = destination.resolve(strict=True)
            for member in members:
                name = member.name
                pure = PurePosixPath(name)
                if (
                    not name
                    or "\\" in name
                    or pure.is_absolute()
                    or any(part in {"", ".", ".."} for part in pure.parts)
                    or name in names
                    or name.casefold() in folded
                    or not (member.isdir() or member.isfile())
                ):
                    raise InstallerError("ARCHIVE_UNSAFE", "archive contains an unsafe member")
                target = destination.joinpath(*pure.parts)
                if not target.resolve(strict=False).is_relative_to(root):
                    raise InstallerError("ARCHIVE_UNSAFE", "archive member escapes extraction root")
                names.add(name)
                folded.add(name.casefold())
                total += member.size if member.isfile() else 0
                if total > MAX_ARCHIVE_BYTES:
                    raise InstallerError("ARCHIVE_UNSAFE", "archive expands beyond the allowed bound")
                validated.append((member, target))
            for member, target in validated:
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                extracted = source.extractfile(member)
                if extracted is None:
                    raise InstallerError("ARCHIVE_UNSAFE", "archive file content is unavailable")
                with extracted, target.open("xb") as output:
                    shutil.copyfileobj(extracted, output, length=1024 * 1024)
                target.chmod(0o700 if target.name == "aven-bootstrap" else 0o600)
    except InstallerError:
        raise
    except (OSError, tarfile.TarError) as error:
        raise InstallerError("ARCHIVE_UNSAFE", "archive could not be safely extracted") from error


def _bootstrap_git_environment(gh: str, directory: Path) -> Mapping[str, str]:
    git_config = directory / "gitconfig"
    git_config.write_bytes(b"")
    if os.name != "nt":
        git_config.chmod(0o600)
    environment = os.environ.copy()
    environment["GIT_CONFIG_GLOBAL"] = str(git_config)
    environment["AVEN_BOOTSTRAP_INSTALL_CHANNEL"] = "PRIVATE_RELEASE_CANDIDATE"
    configured = _run_gh(
        gh,
        ("auth", "setup-git", "--hostname", "github.com"),
        timeout=30,
        env=environment,
    )
    if configured.returncode != 0:
        raise InstallerError(
            "GITHUB_GIT_CREDENTIAL_SETUP_FAILED",
            "GitHub CLI could not configure the transient Git credential helper",
        )
    return environment


def _ensure_git_repository_access(
    git: str,
    channel: Mapping[str, Any],
    *,
    env: Mapping[str, str],
) -> None:
    completed = _run(
        (git, "ls-remote", "--exit-code", f"https://github.com/{channel['repository']}.git", "HEAD"),
        timeout=60,
        cwd=Path.home(),
        env=env,
    )
    if completed.returncode != 0:
        raise InstallerError(
            "GITHUB_GIT_REPOSITORY_ACCESS_DENIED",
            "the transient Git credential path cannot read the approved private repository",
        )


def _invoke_bootstrap(
    python: str,
    bootstrap: Path,
    action: str,
    *,
    inherit: bool,
    env: Mapping[str, str] | None = None,
) -> None:
    completed = _run(
        (python, str(bootstrap), "setup", action),
        timeout=1800,
        inherit=inherit,
        cwd=bootstrap.parent,
        env=env,
    )
    if completed.returncode != 0:
        code = "AVEN_SETUP_PLAN_FAILED" if action == "--plan" else "AVEN_SETUP_APPLY_FAILED"
        raise InstallerError(code, f"Aven bootstrap setup {action} did not succeed")


def _invoke_predecessor_uninstall(
    system: str, action: str, *, predecessor_version: str, inherit: bool
) -> None:
    command = _conventional_aven(system)
    if not command.is_file():
        raise InstallerError(
            "AVEN_UPGRADE_PREDECESSOR_MISSING",
            f"the exact approved Aven {predecessor_version} predecessor is no longer available",
        )
    completed = _run(
        (str(command), "uninstall", action),
        timeout=600,
        inherit=inherit,
        cwd=Path.home(),
    )
    if completed.returncode != 0:
        code = (
            "AVEN_UPGRADE_UNINSTALL_PLAN_FAILED"
            if action == "--plan"
            else "AVEN_UPGRADE_UNINSTALL_APPLY_FAILED"
        )
        raise InstallerError(code, f"the exact Aven {predecessor_version} uninstall {action} did not succeed")


def post_install_health(system: str, channel: Mapping[str, Any]) -> Path:
    expected = _conventional_aven(system)
    if not expected.is_file():
        raise InstallerError("AVEN_POST_INSTALL_UNHEALTHY", "installed Aven launcher was not found")
    command = str(expected)
    for arguments in (("version",), ("status",), ("doctor", "--installation-only")):
        completed = _run((command, *arguments), timeout=180, inherit=True)
        if completed.returncode != 0:
            raise InstallerError("AVEN_POST_INSTALL_UNHEALTHY", f"aven {arguments[0]} did not report healthy")
    if inspect_existing_aven(system, channel) != "ALREADY_INSTALLED":
        raise InstallerError("AVEN_POST_INSTALL_UNHEALTHY", "installed Aven identity could not be confirmed")
    return Path(command)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install the exact approved private Aven release")
    parser.add_argument("--manifest", type=Path, required=True, help=argparse.SUPPRESS)
    parser.add_argument("--channel", choices=("rc", "stable"), default="rc")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--yes", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        system, architecture = platform_identity()
        channel = load_channel(arguments.manifest, arguments.channel)
        if sys.version_info < (3, 11):
            raise InstallerError("PYTHON_TOO_OLD", "Python 3.11 or newer is required")
        tools = ensure_required_tools(
            system,
            check_only=arguments.check,
            assume_yes=arguments.yes,
            non_interactive=arguments.non_interactive,
        )
        print("Aven Installer")
        print(f"System: {system} {architecture}")
        print(f"Python: {platform.python_version()}")
        print(f"Git: {tools['git']['version']}")
        print(f"GitHub CLI: {tools['gh']['version']}")
        print(f"Channel: {channel['channel']} ({channel['version']})")
        print(f"Codex: {'DETECTED' if shutil.which('codex') else 'NOT_DETECTED_OPTIONAL'}")
        print(f"Claude: {'DETECTED' if shutil.which('claude') else 'NOT_DETECTED_OPTIONAL'}")
        print("Voice: optional; configured by Aven after installation")

        ensure_github_access(
            tools["gh"]["path"],
            check_only=arguments.check,
            assume_yes=arguments.yes,
            non_interactive=arguments.non_interactive,
        )
        print(f"GitHub private repository access: {EXPECTED_REPOSITORY}")
        resolve_release(tools["gh"]["path"], channel)
        print(f"Approved release: {channel['tag']} at {channel['commit']}")
        existing = inspect_existing_aven(system, channel)
        if existing == "ALREADY_INSTALLED":
            print("Aven: ALREADY INSTALLED — exact release and lock are healthy")
            return 0
        if arguments.check:
            if existing.startswith("APPROVED_PREDECESSOR:"):
                predecessor_version = existing.split(":", 1)[1]
                print(f"Approved predecessor: {predecessor_version}")
                print(f"Target release: {channel['version']}")
                print("Ready to upgrade: YES")
            else:
                print("Aven: NOT_INSTALLED")
                print("Ready to install: YES")
            print("Mutations performed: 0")
            return 0
        if arguments.non_interactive and not arguments.yes:
            raise InstallerError("EXPLICIT_CONFIRMATION_REQUIRED", "non-interactive installation requires --yes")

        temp_parent = os.environ.get("AVEN_INSTALL_TMPDIR")
        with tempfile.TemporaryDirectory(prefix="aven-install-", dir=temp_parent) as temporary:
            root = Path(temporary)
            download = root / "download"
            extracted = root / "bootstrap"
            download.mkdir(mode=0o700)
            extracted.mkdir(mode=0o700)
            download_release(tools["gh"]["path"], channel, download)
            archive = verify_download(channel, download)
            print(f"Artifact SHA-256 verified: {channel['sha256']}")
            safe_extract(archive, extracted)
            bootstrap = extracted / "aven-bootstrap"
            if not bootstrap.is_file() or bootstrap.is_symlink():
                raise InstallerError("ARCHIVE_UNSAFE", "verified archive did not contain the bootstrap entrypoint")
            bootstrap_environment = _bootstrap_git_environment(tools["gh"]["path"], root)
            _ensure_git_repository_access(
                tools["git"]["path"],
                channel,
                env=bootstrap_environment,
            )
            upgrading = existing.startswith("APPROVED_PREDECESSOR:")
            predecessor_version = existing.split(":", 1)[1] if upgrading else None
            if upgrading:
                _invoke_predecessor_uninstall(
                    system, "--plan", predecessor_version=predecessor_version, inherit=True
                )
            else:
                _invoke_bootstrap(
                    sys.executable,
                    bootstrap,
                    "--plan",
                    inherit=True,
                    env=bootstrap_environment,
                )
            question = (
                f"Upgrade Aven from exact {predecessor_version} to {channel['version']} now?"
                if upgrading else "Install Aven now?"
            )
            if not _prompt(question, assume_yes=arguments.yes, non_interactive=arguments.non_interactive):
                print("Installation cancelled after the zero-effect Aven setup plan.")
                return 0
            if upgrading:
                if inspect_existing_aven(system, channel) != existing:
                    raise InstallerError(
                        "AVEN_UPGRADE_PREDECESSOR_CHANGED",
                        f"the installed Aven {predecessor_version} predecessor changed after planning",
                    )
                _invoke_predecessor_uninstall(
                    system, "--apply", predecessor_version=predecessor_version, inherit=True
                )
                _invoke_bootstrap(
                    sys.executable,
                    bootstrap,
                    "--plan",
                    inherit=True,
                    env=bootstrap_environment,
                )
            _invoke_bootstrap(
                sys.executable,
                bootstrap,
                "--apply",
                inherit=True,
                env=bootstrap_environment,
            )

        launcher = post_install_health(system, channel)
        print()
        print("Aven is ready.")
        print(f"Version: {channel['version']}")
        print(f"Platform: {system} {architecture}")
        print(f"Launcher: {launcher}")
        if launcher.parent not in [Path(item) for item in os.environ.get("PATH", "").split(os.pathsep) if item]:
            print(f"PATH guidance: add {launcher.parent} to your user PATH")
        print("You can start with the capabilities already available.")
        print("Optional capabilities can be added later.")
        print("Run: aven setup")
        print('Or activate Aven and ask: "What options do I have?"')
        print("Try: aven | aven analyze | aven improve --plan | aven doctor")
        print("New local project: aven create --plan --objective \"Build me a project\"")
        print("Uninstall: aven uninstall --plan, then aven uninstall --apply")
        return 0
    except InstallerError as error:
        print(f"Aven Installer stopped: {error.code}", file=sys.stderr)
        print(error.message, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
