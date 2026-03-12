#!/usr/bin/env python3
"""Plan or execute a full tracked-files-only project hard rename."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
RESIDUAL_SEARCH_COMMAND = (
    r"rg -n '\bnexus\b|\bNEXUS\b|nexus-' "
    r"AGENTS.md CLAUDE.md README.md docs nexus3 tests pyproject.toml"
)


@dataclass(frozen=True)
class RenameSpec:
    root_lower: str
    root_upper: str
    repo_slug: str
    dot_dir_name: str
    prompt_stem: str
    tool_stem: str
    header_stem: str


@dataclass(frozen=True)
class ReplacementRule:
    label: str
    old: str
    new: str


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
    repo_slug="NEXUS3",
    dot_dir_name=".nexus3",
    prompt_stem="NEXUS",
    tool_stem="nexus",
    header_stem="nexus",
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
        "root_lower": "newcli",
        "root_upper": "NEWCLI",
        "repo_slug": "NEWCLI",
        "dot_dir_name": ".newcli",
        "prompt_stem": "NEWCLI",
        "tool_stem": "newcli",
        "header_stem": "newcli",
    }


def load_spec(path: Path) -> RenameSpec:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"rename spec must be a JSON object: {path}")
    try:
        spec = RenameSpec(
            root_lower=str(payload["root_lower"]),
            root_upper=str(payload["root_upper"]),
            repo_slug=str(payload["repo_slug"]),
            dot_dir_name=str(payload["dot_dir_name"]),
            prompt_stem=str(payload["prompt_stem"]),
            tool_stem=str(payload["tool_stem"]),
            header_stem=str(payload["header_stem"]),
        )
    except KeyError as exc:
        raise ValueError(f"rename spec missing key: {exc.args[0]}") from exc
    validate_spec(spec)
    return spec


def validate_spec(spec: RenameSpec) -> None:
    if spec.root_lower == CURRENT_SPEC.root_lower:
        raise ValueError("root_lower must differ from the current value")
    if spec.root_upper == CURRENT_SPEC.root_upper:
        raise ValueError("root_upper must differ from the current value")

    lower_name_pattern = re.compile(r"^[a-z][a-z0-9_]*$")
    upper_name_pattern = re.compile(r"^[A-Z][A-Z0-9_]*$")
    stem_pattern = re.compile(r"^[a-z][a-z0-9-]*$")
    repo_pattern = re.compile(r"^[A-Za-z0-9._-]+$")

    if lower_name_pattern.fullmatch(spec.root_lower) is None:
        raise ValueError(
            "root_lower must be a lowercase import/CLI-safe token like 'orbit'"
        )
    if upper_name_pattern.fullmatch(spec.root_upper) is None:
        raise ValueError(
            "root_upper must be an uppercase env/display-safe token like 'ORBIT'"
        )
    if upper_name_pattern.fullmatch(spec.prompt_stem) is None:
        raise ValueError(
            "prompt_stem must be an uppercase token like 'ORBIT'"
        )
    if stem_pattern.fullmatch(spec.tool_stem) is None:
        raise ValueError(
            "tool_stem must be a lowercase token like 'orbit'"
        )
    if stem_pattern.fullmatch(spec.header_stem) is None:
        raise ValueError(
            "header_stem must be a lowercase token like 'orbit'"
        )
    if repo_pattern.fullmatch(spec.repo_slug) is None:
        raise ValueError(
            "repo_slug must be a path-safe token like 'ORBIT' or 'orbit-cli'"
        )
    if (
        not spec.dot_dir_name.startswith(".")
        or "/" in spec.dot_dir_name
        or "\\" in spec.dot_dir_name
    ):
        raise ValueError("dot_dir_name must be a single dot-prefixed directory name")


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
    return [
        REPO_ROOT / rel
        for rel in result.stdout.split("\0")
        if rel
    ]


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
            new=f"{spec.prompt_stem}-DEFAULT.md",
        ),
        ReplacementRule(
            label="prompt_filename",
            old="NEXUS.md",
            new=f"{spec.prompt_stem}.md",
        ),
        ReplacementRule(
            label="rpc_header_capability",
            old="x-nexus-capability",
            new=f"x-{spec.header_stem}-capability",
        ),
        ReplacementRule(
            label="rpc_header_agent",
            old="x-nexus-agent",
            new=f"x-{spec.header_stem}-agent",
        ),
        ReplacementRule(
            label="tool_prefix",
            old="nexus_",
            new=f"{spec.tool_stem}_",
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


def build_path_rules(spec: RenameSpec) -> list[ReplacementRule]:
    return [
        ReplacementRule(
            label="prompt_default_filename",
            old="NEXUS-DEFAULT.md",
            new=f"{spec.prompt_stem}-DEFAULT.md",
        ),
        ReplacementRule(
            label="prompt_filename",
            old="NEXUS.md",
            new=f"{spec.prompt_stem}.md",
        ),
        ReplacementRule(
            label="tool_prefix",
            old="nexus_",
            new=f"{spec.tool_stem}_",
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
        if rule.old in updated:
            updated = updated.replace(rule.old, rule.new)
            labels.append(rule.label)
    return updated, tuple(labels)


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


def build_plan(spec: RenameSpec) -> tuple[list[FileRewritePlan], dict[str, str]]:
    path_rules = build_path_rules(spec)
    content_rules = build_content_rules(spec)
    plans: list[FileRewritePlan] = []
    rewritten_content: dict[str, str] = {}
    collisions: dict[str, str] = {}

    for source_path in tracked_files():
        relative_path = source_path.relative_to(REPO_ROOT)
        try:
            content = source_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise RuntimeError(
                f"tracked file is not valid UTF-8 text and needs manual handling: {relative_path}"
            ) from exc
        plan, new_content = plan_file_rewrite(
            relative_path, content, path_rules, content_rules
        )
        if plan is None:
            continue
        previous_source = collisions.get(plan.dest_path)
        if previous_source is not None and previous_source != plan.source_path:
            raise RuntimeError(
                "path collision: "
                f"{previous_source} and {plan.source_path} both map to "
                f"{plan.dest_path}"
            )
        collisions[plan.dest_path] = plan.source_path
        plans.append(plan)
        rewritten_content[plan.source_path] = new_content

    plans.sort(key=lambda item: item.source_path)
    return plans, rewritten_content


def manifest_payload(spec: RenameSpec, plans: list[FileRewritePlan]) -> dict[str, Any]:
    return {
        "repo_root": str(REPO_ROOT),
        "current_spec": asdict(CURRENT_SPEC),
        "target_spec": asdict(spec),
        "summary": {
            "tracked_files_scanned": len(tracked_files()),
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
        "residual_audit": {
            "commands": [
                RESIDUAL_SEARCH_COMMAND,
                r"rg -n 'NEXUS3|nexus3|\.nexus3|nexus_|x-nexus-|NEXUS\.md|NEXUS-DEFAULT\.md' .",
            ]
        },
    }


def write_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_text_preserve_mode(path: Path, content: str, source_path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
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

    for plan in plans:
        source_abs = REPO_ROOT / plan.source_path
        dest_abs = REPO_ROOT / plan.dest_path
        content = rewritten_content[plan.source_path]
        if plan.path_changed:
            write_text_preserve_mode(dest_abs, content, source_abs)
        elif plan.content_changed:
            write_text_preserve_mode(source_abs, content, source_abs)

    for plan in plans:
        if not plan.path_changed:
            continue
        source_abs = REPO_ROOT / plan.source_path
        old_parent_dirs.append(source_abs.parent)
        source_abs.unlink()

    prune_empty_directories(old_parent_dirs)


def print_summary(spec: RenameSpec, plans: list[FileRewritePlan], execute: bool) -> None:
    path_renames = sum(1 for plan in plans if plan.path_changed)
    content_rewrites = sum(1 for plan in plans if plan.content_changed)
    print(f"mode: {'execute' if execute else 'dry-run'}")
    print(f"repo root: {REPO_ROOT}")
    print(f"target root: {spec.root_lower} / {spec.root_upper}")
    print(f"planned files: {len(plans)}")
    print(f"path renames: {path_renames}")
    print(f"content rewrites: {content_rewrites}")
    if plans:
        print("sample operations:")
        for plan in plans[:10]:
            marker = "rename+rewrite" if plan.path_changed and plan.content_changed else (
                "rename" if plan.path_changed else "rewrite"
            )
            print(f"  - [{marker}] {plan.source_path} -> {plan.dest_path}")
    print("residual audit:")
    print(f"  - {RESIDUAL_SEARCH_COMMAND}")


def main() -> int:
    args = parse_args()
    if args.print_spec_template:
        print(json.dumps(spec_template(), indent=2, sort_keys=True))
        return 0

    assert args.spec is not None
    spec = load_spec(args.spec)
    plans, rewritten_content = build_plan(spec)
    payload = manifest_payload(spec, plans)

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
