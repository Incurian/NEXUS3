from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

SCRIPT_PATH = (
    Path(__file__).resolve().parents[2]
    / "scripts"
    / "maintenance"
    / "project_hard_rename.py"
)
SPEC = importlib.util.spec_from_file_location("project_hard_rename", SCRIPT_PATH)
assert SPEC is not None
assert SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_load_spec_accepts_valid_future_name(tmp_path: Path) -> None:
    spec_path = tmp_path / "rename-spec.json"
    spec_path.write_text(
        json.dumps(
            {
                "root_lower": "orbit",
                "root_upper": "ORBIT",
                "repo_slug": "ORBIT",
                "dot_dir_name": ".orbit",
                "prompt_stem": "ORBIT",
                "tool_stem": "orbit",
                "header_stem": "orbit",
            }
        ),
        encoding="utf-8",
    )

    spec = MODULE.load_spec(spec_path)

    assert spec.root_lower == "orbit"
    assert spec.dot_dir_name == ".orbit"


def test_load_spec_rejects_current_name(tmp_path: Path) -> None:
    spec_path = tmp_path / "rename-spec.json"
    spec_path.write_text(
        json.dumps(
            {
                "root_lower": "nexus3",
                "root_upper": "ORBIT",
                "repo_slug": "ORBIT",
                "dot_dir_name": ".orbit",
                "prompt_stem": "ORBIT",
                "tool_stem": "orbit",
                "header_stem": "orbit",
            }
        ),
        encoding="utf-8",
    )

    try:
        MODULE.load_spec(spec_path)
    except ValueError as exc:
        assert "root_lower must differ" in str(exc)
    else:
        raise AssertionError("expected ValueError for unchanged root_lower")


def test_plan_file_rewrite_covers_structured_surfaces() -> None:
    spec = MODULE.RenameSpec(
        root_lower="orbit",
        root_upper="ORBIT",
        repo_slug="ORBIT",
        dot_dir_name=".orbit",
        prompt_stem="ORBIT",
        tool_stem="orbit",
        header_stem="orbit",
    )
    relative_path = Path("nexus3/skill/builtin/nexus_send.py")
    content = "\n".join(
        [
            "python -m nexus3",
            "NEXUS3_API_KEY",
            ".nexus3/logs",
            "nexus_send",
            "x-nexus-agent",
            "NEXUS.md",
            "NEXUS-DEFAULT.md",
            "import nexus3",
            "NEXUS3",
        ]
    )

    plan, new_content = MODULE.plan_file_rewrite(
        relative_path,
        content,
        MODULE.build_path_rules(spec),
        MODULE.build_content_rules(spec),
    )

    assert plan is not None
    assert plan.dest_path == "orbit/skill/builtin/orbit_send.py"
    assert plan.path_changed is True
    assert plan.content_changed is True
    assert "python -m orbit" in new_content
    assert "ORBIT_API_KEY" in new_content
    assert ".orbit/logs" in new_content
    assert "orbit_send" in new_content
    assert "x-orbit-agent" in new_content
    assert "ORBIT.md" in new_content
    assert "ORBIT-DEFAULT.md" in new_content
    assert "import orbit" in new_content


def test_manifest_payload_counts_operations() -> None:
    spec = MODULE.RenameSpec(
        root_lower="orbit",
        root_upper="ORBIT",
        repo_slug="ORBIT",
        dot_dir_name=".orbit",
        prompt_stem="ORBIT",
        tool_stem="orbit",
        header_stem="orbit",
    )
    plans = [
        MODULE.FileRewritePlan(
            source_path="nexus3/__init__.py",
            dest_path="orbit/__init__.py",
            path_changed=True,
            content_changed=True,
            applied_labels=("root_lower",),
        ),
        MODULE.FileRewritePlan(
            source_path="README.md",
            dest_path="README.md",
            path_changed=False,
            content_changed=True,
            applied_labels=("root_upper",),
        ),
    ]

    payload = MODULE.manifest_payload(spec, plans)

    assert payload["target_spec"]["root_lower"] == "orbit"
    assert payload["summary"]["planned_files"] == 2
    assert payload["summary"]["path_renames"] == 1
    assert payload["summary"]["content_rewrites"] == 2
