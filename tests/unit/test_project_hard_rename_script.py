from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

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


def make_spec() -> MODULE.RenameSpec:
    return MODULE.RenameSpec(
        root_lower="orbit",
        root_upper="ORBIT",
        brand_lower="orbit",
        brand_title="Orbit",
        brand_upper="ORBIT",
        repo_slug="ORBIT",
        dot_dir_name=".orbit",
        api_key_prefix="orb_",
    )


def test_load_spec_accepts_valid_future_name(tmp_path: Path) -> None:
    spec_path = tmp_path / "rename-spec.json"
    spec_path.write_text(json.dumps(MODULE.spec_template()), encoding="utf-8")

    spec = MODULE.load_spec(spec_path)

    assert spec.root_lower == "orbit"
    assert spec.brand_title == "Orbit"
    assert spec.dot_dir_name == ".orbit"
    assert spec.api_key_prefix == "orb_"


def test_load_spec_rejects_legacy_brand_marker(tmp_path: Path) -> None:
    spec_path = tmp_path / "rename-spec.json"
    spec_path.write_text(
        json.dumps(
            {
                "root_lower": "orbit",
                "root_upper": "ORBIT",
                "brand_lower": "nexus",
                "brand_title": "Orbit",
                "brand_upper": "ORBIT",
                "repo_slug": "ORBIT",
                "dot_dir_name": ".orbit",
                "api_key_prefix": "orb_",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(
        ValueError,
        match="brand_lower must differ|legacy 'nexus' marker",
    ):
        MODULE.load_spec(spec_path)


def test_plan_file_rewrite_covers_extended_namespace_surfaces() -> None:
    spec = make_spec()
    relative_path = Path("nexus3/skill/builtin/nexus_send.py")
    content = "\n".join(
        [
            "python -m nexus3",
            "NEXUS3_API_KEY",
            "NEXUS_DEV",
            "NEXUS_SERVER",
            "NEXUS_DIR_NAME",
            "NEXUS_MD_TEMPLATE",
            ".nexus3/logs",
            "nexus_send",
            "x-nexus-agent",
            "X-Nexus-Agent",
            "NEXUS.md",
            "NEXUS-DEFAULT.md",
            "import nexus3",
            "class NexusClient: pass",
            "class NexusSkill: pass",
            "class NexusError: pass",
            "def get_nexus_dir(): pass",
            "nexus-mcp-server",
            "nexus tools",
            "nexus_server",
            "prefix = 'nxk_'",
            "NEXUS3",
            "NEXUS",
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
    assert "ORBIT_DEV" in new_content
    assert "ORBIT_SERVER" in new_content
    assert "ORBIT_DIR_NAME" in new_content
    assert "ORBIT_MD_TEMPLATE" in new_content
    assert ".orbit/logs" in new_content
    assert "orbit_send" in new_content
    assert "x-orbit-agent" in new_content
    assert "X-Orbit-Agent" in new_content
    assert "ORBIT.md" in new_content
    assert "ORBIT-DEFAULT.md" in new_content
    assert "import orbit" in new_content
    assert "class OrbitClient: pass" in new_content
    assert "class OrbitSkill: pass" in new_content
    assert "class OrbitError: pass" in new_content
    assert "def get_orbit_dir(): pass" in new_content
    assert "orbit-mcp-server" in new_content
    assert "orbit tools" in new_content
    assert "orbit_server" in new_content
    assert "prefix = 'orb_'" in new_content


def test_build_plan_detects_destination_collision_with_static_tracked_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = make_spec()
    old_path = tmp_path / "nexus3" / "alpha.txt"
    new_path = tmp_path / "orbit" / "alpha.txt"
    old_path.parent.mkdir(parents=True)
    new_path.parent.mkdir(parents=True)
    old_path.write_text("nexus3\n", encoding="utf-8")
    new_path.write_text("occupied\n", encoding="utf-8")

    monkeypatch.setattr(MODULE, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(MODULE, "tracked_files", lambda: [old_path, new_path])

    with pytest.raises(RuntimeError, match="destination collision"):
        MODULE.build_plan(spec)


def test_build_plan_detects_destination_collision_with_untracked_path(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = make_spec()
    old_path = tmp_path / "nexus3" / "alpha.txt"
    untracked_dest = tmp_path / "orbit" / "alpha.txt"
    old_path.parent.mkdir(parents=True)
    untracked_dest.parent.mkdir(parents=True)
    old_path.write_text("nexus3\n", encoding="utf-8")
    untracked_dest.write_text("untracked occupant\n", encoding="utf-8")

    monkeypatch.setattr(MODULE, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(MODULE, "tracked_files", lambda: [old_path])

    with pytest.raises(RuntimeError, match="overwrite untracked path"):
        MODULE.build_plan(spec)


def test_build_plan_detects_destination_collision_with_broken_symlink(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = make_spec()
    old_path = tmp_path / "nexus3" / "alpha.txt"
    broken_link = tmp_path / "orbit" / "alpha.txt"
    old_path.parent.mkdir(parents=True)
    broken_link.parent.mkdir(parents=True)
    old_path.write_text("nexus3\n", encoding="utf-8")
    try:
        os.symlink(tmp_path / "missing-target.txt", broken_link)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    monkeypatch.setattr(MODULE, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(MODULE, "tracked_files", lambda: [old_path])

    with pytest.raises(RuntimeError, match="symlinked path"):
        MODULE.build_plan(spec)


def test_build_plan_detects_destination_collision_with_symlinked_parent(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = make_spec()
    old_path = tmp_path / "nexus3" / "alpha.txt"
    real_parent = tmp_path / "outside"
    symlinked_parent = tmp_path / "orbit"
    old_path.parent.mkdir(parents=True)
    real_parent.mkdir(parents=True)
    old_path.write_text("nexus3\n", encoding="utf-8")
    try:
        os.symlink(real_parent, symlinked_parent, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    monkeypatch.setattr(MODULE, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(MODULE, "tracked_files", lambda: [old_path])

    with pytest.raises(RuntimeError, match="symlinked path"):
        MODULE.build_plan(spec)


def test_build_plan_detects_destination_collision_with_untracked_parent_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = make_spec()
    old_path = tmp_path / "nexus3" / "alpha.txt"
    blocking_parent = tmp_path / "orbit"
    old_path.parent.mkdir(parents=True)
    old_path.write_text("nexus3\n", encoding="utf-8")
    blocking_parent.write_text("not a directory\n", encoding="utf-8")

    monkeypatch.setattr(MODULE, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(MODULE, "tracked_files", lambda: [old_path])

    with pytest.raises(RuntimeError, match="non-directory path"):
        MODULE.build_plan(spec)


def test_build_plan_detects_destination_collision_with_tracked_parent_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = make_spec()
    old_path = tmp_path / "nexus3" / "alpha.txt"
    blocking_parent = tmp_path / "orbit"
    old_path.parent.mkdir(parents=True)
    old_path.write_text("nexus3\n", encoding="utf-8")
    blocking_parent.write_text("tracked file\n", encoding="utf-8")

    monkeypatch.setattr(MODULE, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(MODULE, "tracked_files", lambda: [old_path, blocking_parent])

    with pytest.raises(RuntimeError, match="non-directory path"):
        MODULE.build_plan(spec)


def test_execute_plan_preserves_crlf_newlines(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    spec = make_spec()
    readme = tmp_path / "README.md"
    readme.write_bytes(b"python -m nexus3\r\nnexus tools\r\n")

    monkeypatch.setattr(MODULE, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(MODULE, "tracked_files", lambda: [readme])

    plans, rewritten_content, tracked_count = MODULE.build_plan(spec)
    MODULE.execute_plan(plans, rewritten_content)
    payload = MODULE.manifest_payload(spec, plans, tracked_count)

    assert readme.read_bytes() == b"python -m orbit\r\norbit tools\r\n"
    assert payload["summary"]["planned_files"] == 1
    assert payload["summary"]["content_rewrites"] == 1


def test_manifest_payload_counts_operations() -> None:
    spec = make_spec()
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
            applied_labels=("brand_lower",),
        ),
    ]

    payload = MODULE.manifest_payload(spec, plans, tracked_files_scanned=10)

    assert payload["target_spec"]["root_lower"] == "orbit"
    assert payload["target_spec"]["brand_title"] == "Orbit"
    assert payload["summary"]["tracked_files_scanned"] == 10
    assert payload["summary"]["planned_files"] == 2
    assert payload["summary"]["path_renames"] == 1
    assert payload["summary"]["content_rewrites"] == 2
