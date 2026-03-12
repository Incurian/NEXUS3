#!/usr/bin/env python3
"""Plan or execute a full tracked-files-only project hard rename."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
RESIDUAL_SEARCH_COMMANDS = (
    (
        r"rg -n "
        r"'NEXUS3|nexus3|\.nexus3|NEXUS3_API_KEY|python -m nexus3|"
        r"import nexus3|from nexus3|nexus3\.server|nexus3_current_agent_id' ."
    ),
    (
        r"rg -n "
        r"'NEXUS_|NEXUS\.md|NEXUS-DEFAULT\.md|X-Nexus-|x-nexus-|"
        r"get_nexus_|nxk_' ."
    ),
    (
        r"rg -n "
        r"'Nexus|nexus_|nexus-|\\bnexus\\b|\\bNEXUS\\b' "
        r"AGENTS.md CLAUDE.md README.md docs nexus3 tests pyproject.toml"
    ),
)


@dataclass(frozen=True)
class RenameSpec:
    root_lower: str
    root_upper: str
    brand_lower: str
    brand_title: str
    brand_upper: str
    repo_slug: str
    dot_dir_name: str
    api_key_prefix: str


@dataclass(frozen=True)
class ReplacementRule:
    label: str
    old: str
    new: str
    regex: bool = False


@dataclass(frozen=True)
class FileRewritePlan:
    source_path: str
    dest_path: str
    path_changed: bool
    content_changed: bool
    applied_labels: tuple[str, ...]


CURRENT_SPEC = RenameSpec(
    root_lower="nexus3",
    root_upper="NEXUS3",
    brand_lower="nexus",
    brand_title="Nexus",
    brand_upper="NEXUS",
    repo_slug="NEXUS3",
    dot_dir_name=".nexus3",
    api_key_prefix="nxk_",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--spec",
        type=Path,
        help="JSON spec describing the future rename surfaces.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Optional JSON file to write the planned operations to.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Apply the planned rename. Default behavior is dry-run only.",
    )
    parser.add_argument(
        "--allow-dirty",
        action="store_true",
        help="Allow execute mode on a dirty tracked worktree.",
    )
    parser.add_argument(
        "--print-spec-template",
        action="store_true",
        help="Print a JSON template for the rename spec and exit.",
    )
    args = parser.parse_args()
    if not args.print_spec_template and args.spec is None:
        parser.error("--spec is required unless --print-spec-template is used")
    return args


def spec_template() -> dict[str, str]:
    return {
        "root_lower": "orbit",
        "root_upper": "ORBIT",
        "brand_lower": "orbit",
        "brand_title": "Orbit",
        "brand_upper": "ORBIT",
        "repo_slug": "ORBIT",
        "dot_dir_name": ".orbit",
        "api_key_prefix": "orb_",
    }


def load_spec(path: Path) -> RenameSpec:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"rename spec must be a JSON object: {path}")
    try:
        spec = RenameSpec(
            root_lower=str(payload["root_lower"]),
            root_upper=str(payload["root_upper"]),
            brand_lower=str(payload["brand_lower"]),
            brand_title=str(payload["brand_title"]),
            brand_upper=str(payload["brand_upper"]),
            repo_slug=str(payload["repo_slug"]),
            dot_dir_name=str(payload["dot_dir_name"]),
            api_key_prefix=str(payload["api_key_prefix"]),
        )
    except KeyError as exc:
        raise ValueError(f"rename spec missing key: {exc.args[0]}") from exc
    validate_spec(spec)
    return spec


def _assert_differs(name: str, actual: str, current: str) -> None:
    if actual == current:
        raise ValueError(f"{name} must differ from the current value")


def _assert_no_legacy_brand(name: str, actual: str) -> None:
    if "nexus" in actual.lower():
        raise ValueError(f"{name} must not contain the legacy 'nexus' marker")


def validate_spec(spec: RenameSpec) -> None:
    _assert_differs("root_lower", spec.root_lower, CURRENT_SPEC.root_lower)
    _assert_differs("root_upper", spec.root_upper, CURRENT_SPEC.root_upper)
    _assert_differs("brand_lower", spec.brand_lower, CURRENT_SPEC.brand_lower)
    _assert_differs("brand_title", spec.brand_title, CURRENT_SPEC.brand_title)
    _assert_differs("brand_upper", spec.brand_upper, CURRENT_SPEC.brand_upper)
    _assert_differs("repo_slug", spec.repo_slug, CURRENT_SPEC.repo_slug)
    _assert_differs("dot_dir_name", spec.dot_dir_name, CURRENT_SPEC.dot_dir_name)
    _assert_differs("api_key_prefix", spec.api_key_prefix, CURRENT_SPEC.api_key_prefix)

    lower_name_pattern = re.compile(r"^[a-z][a-z0-9_]*$")
    title_name_pattern = re.compile(r"^[A-Z][A-Za-z0-9]*$")
    upper_name_pattern = re.compile(r"^[A-Z][A-Z0-9_]*$")
    repo_pattern = re.compile(r"^[A-Za-z0-9._-]+$")
    prefix_pattern = re.compile(r"^[a-z][a-z0-9]*_$")

    if lower_name_pattern.fullmatch(spec.root_lower) is None:
        raise ValueError(
            "root_lower must be a lowercase import/CLI-safe token like 'orbit'"
        )
    if upper_name_pattern.fullmatch(spec.root_upper) is None:
        raise ValueError(
            "root_upper must be an uppercase token like 'ORBIT'"
        )
    if lower_name_pattern.fullmatch(spec.brand_lower) is None:
        raise ValueError(
            "brand_lower must be a lowercase token like 'orbit'"
        )
    if title_name_pattern.fullmatch(spec.brand_title) is None:
        raise ValueError(
            "brand_title must be a TitleCase token like 'Orbit'"
        )
    if upper_name_pattern.fullmatch(spec.brand_upper) is None:
        raise ValueError(
            "brand_upper must be an uppercase token like 'ORBIT'"
        )
    if repo_pattern.fullmatch(spec.repo_slug) is None:
        raise ValueError(
            "repo_slug must be a path-safe token like 'ORBIT' or 'orbit-cli'"
        )
    if prefix_pattern.fullmatch(spec.api_key_prefix) is None:
        raise ValueError(
            "api_key_prefix must look like 'orb_' or 'orbit_'"
        )
    if (
        not spec.dot_dir_name.startswith(".")
        or "/" in spec.dot_dir_name
        or "\\" in spec.dot_dir_name
    ):
        raise ValueError("dot_dir_name must be a single dot-prefixed directory name")

    for name, value in (
        ("root_lower", spec.root_lower),
        ("root_upper", spec.root_upper),
        ("brand_lower", spec.brand_lower),
        ("brand_title", spec.brand_title),
        ("brand_upper", spec.brand_upper),
        ("repo_slug", spec.repo_slug),
        ("dot_dir_name", spec.dot_dir_name),
        ("api_key_prefix", spec.api_key_prefix),
    ):
        _assert_no_legacy_brand(name, value)


def run_git_command(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def tracked_files() -> list[Path]:
    result = run_git_command("ls-files", "-z")
    return [REPO_ROOT / rel for rel in result.stdout.split("\0") if rel]


def ensure_clean_tracked_worktree() -> None:
    result = run_git_command("status", "--porcelain", "--untracked-files=no")
    if result.stdout.strip():
        raise RuntimeError(
            "tracked worktree is dirty; commit or stash tracked changes first, "
            "or rerun with --allow-dirty"
        )


def build_content_rules(spec: RenameSpec) -> list[ReplacementRule]:
    return [
        ReplacementRule(
            label="repo_url_git",
            old="https://github.com/Incurian/NEXUS3.git",
            new=f"https://github.com/Incurian/{spec.repo_slug}.git",
        ),
        ReplacementRule(
            label="repo_url_https",
            old="https://github.com/Incurian/NEXUS3",
            new=f"https://github.com/Incurian/{spec.repo_slug}",
        ),
        ReplacementRule(
            label="repo_abs_path",
            old="/home/inc/repos/NEXUS3",
            new=f"/home/inc/repos/{spec.repo_slug}",
        ),
        ReplacementRule(
            label="api_key_env",
            old="NEXUS3_API_KEY",
            new=f"{spec.root_upper}_API_KEY",
        ),
        ReplacementRule(
            label="dev_env",
            old="NEXUS_DEV",
            new=f"{spec.brand_upper}_DEV",
        ),
        ReplacementRule(
            label="server_symbol",
            old="NEXUS_SERVER",
            new=f"{spec.brand_upper}_SERVER",
        ),
        ReplacementRule(
            label="brand_upper_prefix",
            old="NEXUS_",
            new=f"{spec.brand_upper}_",
        ),
        ReplacementRule(
            label="logger_context",
            old="nexus3_current_agent_id",
            new=f"{spec.root_lower}_current_agent_id",
        ),
        ReplacementRule(
            label="logger_name",
            old="nexus3.server",
            new=f"{spec.root_lower}.server",
        ),
        ReplacementRule(
            label="module_invocation",
            old="python -m nexus3",
            new=f"python -m {spec.root_lower}",
        ),
        ReplacementRule(
            label="prompt_default_filename",
            old="NEXUS-DEFAULT.md",
            new=f"{spec.brand_upper}-DEFAULT.md",
        ),
        ReplacementRule(
            label="prompt_filename",
            old="NEXUS.md",
            new=f"{spec.brand_upper}.md",
        ),
        ReplacementRule(
            label="rpc_header_capability_lower",
            old="x-nexus-capability",
            new=f"x-{spec.brand_lower}-capability",
        ),
        ReplacementRule(
            label="rpc_header_agent_lower",
            old="x-nexus-agent",
            new=f"x-{spec.brand_lower}-agent",
        ),
        ReplacementRule(
            label="rpc_header_capability_title",
            old="X-Nexus-Capability",
            new=f"X-{spec.brand_title}-Capability",
        ),
        ReplacementRule(
            label="rpc_header_agent_title",
            old="X-Nexus-Agent",
            new=f"X-{spec.brand_title}-Agent",
        ),
        ReplacementRule(
            label="api_key_prefix_literal",
            old="nxk_",
            new=spec.api_key_prefix,
        ),
        ReplacementRule(
            label="root_lower",
            old="nexus3",
            new=spec.root_lower,
        ),
        ReplacementRule(
            label="root_upper",
            old="NEXUS3",
            new=spec.root_upper,
        ),
        ReplacementRule(
            label="dot_dir",
            old=".nexus3",
            new=spec.dot_dir_name,
        ),
        ReplacementRule(
            label="getter_prefix",
            old="get_nexus_",
            new=f"get_{spec.brand_lower}_",
        ),
        ReplacementRule(
            label="tool_prefix",
            old="nexus_",
            new=f"{spec.brand_lower}_",
        ),
        ReplacementRule(
            label="hyphen_compound",
            old="nexus-",
            new=f"{spec.brand_lower}-",
        ),
        ReplacementRule(
            label="server_value",
            old="nexus_server",
            new=f"{spec.brand_lower}_server",
        ),
        ReplacementRule(
            label="brand_title",
            old="Nexus",
            new=spec.brand_title,
        ),
        ReplacementRule(
            label="brand_upper",
            old=r"\bNEXUS\b",
            new=spec.brand_upper,
            regex=True,
        ),
        ReplacementRule(
            label="brand_lower",
            old=r"\bnexus\b",
            new=spec.brand_lower,
            regex=True,
        ),
    ]


def build_path_rules(spec: RenameSpec) -> list[ReplacementRule]:
    return [
        ReplacementRule(
            label="prompt_default_filename",
            old="NEXUS-DEFAULT.md",
            new=f"{spec.brand_upper}-DEFAULT.md",
        ),
        ReplacementRule(
            label="prompt_filename",
            old="NEXUS.md",
            new=f"{spec.brand_upper}.md",
        ),
        ReplacementRule(
            label="tool_prefix",
            old="nexus_",
            new=f"{spec.brand_lower}_",
        ),
        ReplacementRule(
            label="hyphen_compound",
            old="nexus-",
            new=f"{spec.brand_lower}-",
        ),
        ReplacementRule(
            label="dot_dir",
            old=".nexus3",
            new=spec.dot_dir_name,
        ),
        ReplacementRule(
            label="root_lower",
            old="nexus3",
            new=spec.root_lower,
        ),
        ReplacementRule(
            label="root_upper",
            old="NEXUS3",
            new=spec.root_upper,
        ),
    ]


def apply_rules(text: str, rules: list[ReplacementRule]) -> tuple[str, tuple[str, ...]]:
    updated = text
    labels: list[str] = []
    for rule in rules:
        if rule.regex:
            updated, count = re.subn(rule.old, rule.new, updated)
        else:
            count = updated.count(rule.old)
            if count:
                updated = updated.replace(rule.old, rule.new)
        if count:
            labels.append(rule.label)
    return updated, tuple(labels)


def read_tracked_text(path: Path) -> str:
    if path.is_symlink():
        raise RuntimeError(f"tracked symlink needs manual handling: {path}")
    raw = path.read_bytes()
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise RuntimeError(
            f"tracked file is not valid UTF-8 text and needs manual handling: {path}"
        ) from exc


def plan_file_rewrite(
    relative_path: Path,
    content: str,
    path_rules: list[ReplacementRule],
    content_rules: list[ReplacementRule],
) -> tuple[FileRewritePlan | None, str]:
    new_relative, path_labels = apply_rules(relative_path.as_posix(), path_rules)
    new_content, content_labels = apply_rules(content, content_rules)
    path_changed = new_relative != relative_path.as_posix()
    content_changed = new_content != content
    if not path_changed and not content_changed:
        return None, content
    plan = FileRewritePlan(
        source_path=relative_path.as_posix(),
        dest_path=new_relative,
        path_changed=path_changed,
        content_changed=content_changed,
        applied_labels=tuple(dict.fromkeys((*path_labels, *content_labels))),
    )
    return plan, new_content


def validate_destination_collisions(
    plans: list[FileRewritePlan],
    tracked_relative_paths: set[str],
) -> None:
    plans_by_source = {plan.source_path: plan for plan in plans}
    for plan in plans:
        if not plan.path_changed:
            continue
        if plan.dest_path not in tracked_relative_paths:
            continue
        if plan.dest_path == plan.source_path:
            continue
        occupant_plan = plans_by_source.get(plan.dest_path)
        if occupant_plan is None or not occupant_plan.path_changed:
            raise RuntimeError(
                "destination collision: "
                f"{plan.source_path} would overwrite tracked path {plan.dest_path}"
            )


def validate_untracked_destination_collisions(
    plans: list[FileRewritePlan],
    tracked_relative_paths: set[str],
) -> None:
    for plan in plans:
        if not plan.path_changed:
            continue
        dest_abs = REPO_ROOT / plan.dest_path
        symlink_path = find_symlink_in_path(dest_abs)
        if symlink_path is not None:
            raise RuntimeError(
                "destination collision: "
                f"{plan.source_path} resolves through symlinked path "
                f"{symlink_path.relative_to(REPO_ROOT)}"
            )
        blocking_ancestor = find_non_directory_ancestor(dest_abs)
        if blocking_ancestor is not None:
            raise RuntimeError(
                "destination collision: "
                f"{plan.source_path} resolves through non-directory path "
                f"{blocking_ancestor.relative_to(REPO_ROOT)}"
            )
        if plan.dest_path in tracked_relative_paths:
            continue
        if dest_abs.exists() or dest_abs.is_symlink():
            raise RuntimeError(
                "destination collision: "
                f"{plan.source_path} would overwrite untracked path {plan.dest_path}"
            )


def find_symlink_in_path(path: Path) -> Path | None:
    current = path
    while True:
        if current.is_symlink():
            return current
        if current == REPO_ROOT:
            return None
        parent = current.parent
        if parent == current:
            return None
        current = parent


def find_non_directory_ancestor(path: Path) -> Path | None:
    current = path.parent
    while True:
        if current == REPO_ROOT:
            return None
        if current.exists() and not current.is_dir():
            return current
        parent = current.parent
        if parent == current:
            return None
        current = parent


def build_plan(spec: RenameSpec) -> tuple[list[FileRewritePlan], dict[str, str], int]:
    path_rules = build_path_rules(spec)
    content_rules = build_content_rules(spec)
    plans: list[FileRewritePlan] = []
    rewritten_content: dict[str, str] = {}
    rewritten_paths: dict[str, str] = {}
    tracked = tracked_files()
    tracked_relative_paths = {
        source_path.relative_to(REPO_ROOT).as_posix()
        for source_path in tracked
    }

    for source_path in tracked:
        relative_path = source_path.relative_to(REPO_ROOT)
        content = read_tracked_text(source_path)
        plan, new_content = plan_file_rewrite(
            relative_path, content, path_rules, content_rules
        )
        if plan is None:
            continue
        previous_source = rewritten_paths.get(plan.dest_path)
        if previous_source is not None and previous_source != plan.source_path:
            raise RuntimeError(
                "path collision: "
                f"{previous_source} and {plan.source_path} both map to "
                f"{plan.dest_path}"
            )
        rewritten_paths[plan.dest_path] = plan.source_path
        plans.append(plan)
        rewritten_content[plan.source_path] = new_content

    validate_destination_collisions(plans, tracked_relative_paths)
    validate_untracked_destination_collisions(plans, tracked_relative_paths)
    plans.sort(key=lambda item: item.source_path)
    return plans, rewritten_content, len(tracked)


def manifest_payload(
    spec: RenameSpec,
    plans: list[FileRewritePlan],
    tracked_files_scanned: int,
) -> dict[str, Any]:
    return {
        "repo_root": str(REPO_ROOT),
        "current_spec": asdict(CURRENT_SPEC),
        "target_spec": asdict(spec),
        "summary": {
            "tracked_files_scanned": tracked_files_scanned,
            "planned_files": len(plans),
            "path_renames": sum(1 for plan in plans if plan.path_changed),
            "content_rewrites": sum(1 for plan in plans if plan.content_changed),
        },
        "operations": [
            {
                "source_path": plan.source_path,
                "dest_path": plan.dest_path,
                "path_changed": plan.path_changed,
                "content_changed": plan.content_changed,
                "applied_labels": list(plan.applied_labels),
            }
            for plan in plans
        ],
        "residual_audit": {"commands": list(RESIDUAL_SEARCH_COMMANDS)},
    }


def write_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_text_preserve_mode(path: Path, content: str, source_path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(content)
    mode = source_path.stat().st_mode & 0o777
    path.chmod(mode)


def prune_empty_directories(paths: list[Path]) -> None:
    seen: set[Path] = set()
    for path in sorted(paths, key=lambda item: len(item.parts), reverse=True):
        current = path
        while current != REPO_ROOT and current not in seen:
            seen.add(current)
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent


def execute_plan(plans: list[FileRewritePlan], rewritten_content: dict[str, str]) -> None:
    old_parent_dirs: list[Path] = []
    path_changed_plans = [plan for plan in plans if plan.path_changed]
    content_only_plans = [
        plan for plan in plans if not plan.path_changed and plan.content_changed
    ]

    with tempfile.TemporaryDirectory(prefix="project-hard-rename-") as temp_dir:
        temp_root = Path(temp_dir)
        staged_moves: list[tuple[Path, Path]] = []

        for index, plan in enumerate(path_changed_plans):
            source_abs = REPO_ROOT / plan.source_path
            staged_path = temp_root / f"{index:04d}"
            write_text_preserve_mode(
                staged_path,
                rewritten_content[plan.source_path],
                source_abs,
            )
            staged_moves.append((staged_path, REPO_ROOT / plan.dest_path))

        for plan in path_changed_plans:
            source_abs = REPO_ROOT / plan.source_path
            old_parent_dirs.append(source_abs.parent)
            source_abs.unlink()

        for staged_path, dest_abs in staged_moves:
            dest_abs.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staged_path, dest_abs)

    for plan in content_only_plans:
        source_abs = REPO_ROOT / plan.source_path
        write_text_preserve_mode(
            source_abs,
            rewritten_content[plan.source_path],
            source_abs,
        )

    prune_empty_directories(old_parent_dirs)


def print_summary(spec: RenameSpec, plans: list[FileRewritePlan], execute: bool) -> None:
    path_renames = sum(1 for plan in plans if plan.path_changed)
    content_rewrites = sum(1 for plan in plans if plan.content_changed)
    print(f"mode: {'execute' if execute else 'dry-run'}")
    print(f"repo root: {REPO_ROOT}")
    print(f"target root: {spec.root_lower} / {spec.root_upper}")
    print(f"target brand: {spec.brand_title} / {spec.brand_upper}")
    print(f"planned files: {len(plans)}")
    print(f"path renames: {path_renames}")
    print(f"content rewrites: {content_rewrites}")
    if plans:
        print("sample operations:")
        for plan in plans[:10]:
            marker = (
                "rename+rewrite"
                if plan.path_changed and plan.content_changed
                else ("rename" if plan.path_changed else "rewrite")
            )
            print(f"  - [{marker}] {plan.source_path} -> {plan.dest_path}")
    print("residual audit:")
    for command in RESIDUAL_SEARCH_COMMANDS:
        print(f"  - {command}")


def main() -> int:
    args = parse_args()
    if args.print_spec_template:
        print(json.dumps(spec_template(), indent=2, sort_keys=True))
        return 0

    assert args.spec is not None
    spec = load_spec(args.spec)
    plans, rewritten_content, tracked_files_scanned = build_plan(spec)
    payload = manifest_payload(spec, plans, tracked_files_scanned)

    if args.manifest is not None:
        write_manifest(args.manifest, payload)

    if args.execute:
        if not args.allow_dirty:
            ensure_clean_tracked_worktree()
        execute_plan(plans, rewritten_content)

    print_summary(spec, plans, execute=args.execute)
    if args.manifest is not None:
        print(f"manifest: {args.manifest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
