"""Tests for the read-only process tools and kill_process."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from nexus3.core.permissions import PermissionLevel
from nexus3.core.process import WINDOWS_CREATIONFLAGS
from nexus3.core.process_tools import protected_termination_reason
from nexus3.skill.builtin.kill_process import KillProcessSkill, kill_process_factory
from nexus3.skill.builtin.processes import (
    GetProcessSkill,
    ListProcessesSkill,
    get_process_factory,
    list_processes_factory,
)
from nexus3.skill.services import ServiceContainer


def _make_services(
    *,
    allowed_paths: list[Path] | None = None,
    blocked_paths: list[Path] | None = None,
    cwd: Path | str | None = None,
    permission_level: PermissionLevel | None = None,
) -> ServiceContainer:
    services = ServiceContainer()
    if allowed_paths is not None:
        services.register_runtime_compat("allowed_paths", allowed_paths)
    if blocked_paths is not None:
        services.register("blocked_paths", blocked_paths)
    if cwd is not None:
        services.set_cwd(cwd)
    if permission_level is not None:
        services.register("permission_level", permission_level)
    return services


class _FakeProcess:
    def __init__(self, info: dict[str, object]) -> None:
        self.info = info


class TestListProcessesSkill:
    @pytest.fixture
    def skill(self) -> ListProcessesSkill:
        return ListProcessesSkill(_make_services())

    def test_parameters_do_not_expose_pid_filter(self, skill: ListProcessesSkill) -> None:
        assert "pid" not in skill.parameters["properties"]

    @pytest.mark.asyncio
    async def test_list_filters_and_paginates(
        self,
        skill: ListProcessesSkill,
        monkeypatch,
    ) -> None:
        fake_processes = [
            _FakeProcess(
                {
                    "pid": 11,
                    "ppid": 1,
                    "name": "python",
                    "status": "sleeping",
                    "username": "alice",
                    "create_time": 1700000000.0,
                    "cmdline": ["python", "-m", "http.server"],
                }
            ),
            _FakeProcess(
                {
                    "pid": 12,
                    "ppid": 1,
                    "name": "node",
                    "status": "running",
                    "username": "alice",
                    "create_time": 1700000001.0,
                    "cmdline": ["node", "dev-server.js"],
                }
            ),
            _FakeProcess(
                {
                    "pid": 25,
                    "ppid": 2,
                    "name": "python",
                    "status": "sleeping",
                    "username": "bob",
                    "create_time": 1700000002.0,
                    "cmdline": ["python", "-c", "print('marker')"],
                }
            ),
        ]
        monkeypatch.setattr(
            "nexus3.skill.builtin.processes.psutil.process_iter",
            lambda attrs=None: fake_processes,
        )
        monkeypatch.setattr(
            "nexus3.skill.builtin.processes.build_port_map",
            lambda required=False: {11: [8000], 25: [3000]},
        )

        result = await skill.execute(
            query="python",
            match="contains",
            user="alice",
            limit=1,
            offset=0,
        )

        assert not result.error
        payload = json.loads(result.output)
        assert payload["total"] == 1
        assert payload["count"] == 1
        assert payload["truncated"] is False
        assert payload["items"][0]["pid"] == 11
        assert payload["items"][0]["name"] == "python"

    @pytest.mark.asyncio
    async def test_list_port_filter_uses_port_map(
        self,
        skill: ListProcessesSkill,
        monkeypatch,
    ) -> None:
        fake_processes = [
            _FakeProcess(
                {
                    "pid": 40,
                    "ppid": 1,
                    "name": "server",
                    "status": "running",
                    "username": "alice",
                    "create_time": 1700000003.0,
                    "cmdline": ["server", "--port", "9000"],
                }
            ),
            _FakeProcess(
                {
                    "pid": 41,
                    "ppid": 1,
                    "name": "server",
                    "status": "sleeping",
                    "username": "alice",
                    "create_time": 1700000004.0,
                    "cmdline": ["server", "--port", "3000"],
                }
            ),
        ]
        monkeypatch.setattr(
            "nexus3.skill.builtin.processes.psutil.process_iter",
            lambda attrs=None: fake_processes,
        )
        monkeypatch.setattr(
            "nexus3.skill.builtin.processes.build_port_map",
            lambda required=False: {40: [9000], 41: [3000]},
        )

        result = await skill.execute(port=3000)

        assert not result.error
        payload = json.loads(result.output)
        assert [item["pid"] for item in payload["items"]] == [41]

    @pytest.mark.asyncio
    async def test_list_port_zero_is_treated_as_omitted(
        self,
        skill: ListProcessesSkill,
        monkeypatch,
    ) -> None:
        fake_processes = [
            _FakeProcess(
                {
                    "pid": 70,
                    "ppid": 1,
                    "name": "server",
                    "status": "running",
                    "username": "alice",
                    "create_time": 1700000010.0,
                    "cmdline": ["server"],
                }
            )
        ]
        monkeypatch.setattr(
            "nexus3.skill.builtin.processes.psutil.process_iter",
            lambda attrs=None: fake_processes,
        )

        def _unexpected_port_map(required: bool = False) -> dict[int, list[int]]:
            raise AssertionError("build_port_map should not be called for port=0")

        monkeypatch.setattr(
            "nexus3.skill.builtin.processes.build_port_map",
            _unexpected_port_map,
        )

        result = await skill.execute(port=0)

        assert not result.error
        payload = json.loads(result.output)
        assert [item["pid"] for item in payload["items"]] == [70]

    @pytest.mark.asyncio
    async def test_list_negative_port_is_rejected(self, skill: ListProcessesSkill) -> None:
        result = await skill.execute(port=-1)

        assert result.error is not None
        assert "port must be >= 0" in result.error

    def test_factory_creates_skill(self) -> None:
        skill = list_processes_factory(_make_services())
        assert isinstance(skill, ListProcessesSkill)


class TestGetProcessSkill:
    @pytest.fixture
    def skill(self) -> GetProcessSkill:
        return GetProcessSkill(_make_services())

    @pytest.mark.asyncio
    async def test_get_by_pid_returns_details(
        self,
        skill: GetProcessSkill,
        monkeypatch,
    ) -> None:
        monkeypatch.setattr(
            "nexus3.skill.builtin.processes.get_process_filter_view",
            lambda pid, include_ports=False, port_lookup_required=False: {
                "pid": pid,
                "name": "python",
                "username": "alice",
                "command": "python worker.py",
                "ports": [9000],
            },
        )
        monkeypatch.setattr(
            "nexus3.skill.builtin.processes.get_process_details",
            lambda pid, include_ports=True, port_lookup_required=False: {
                "pid": pid,
                "name": "python",
                "username": "alice",
                "command_preview": "python worker.py",
                "ports": [9000],
            },
        )

        result = await skill.execute(pid=1234)

        assert not result.error
        payload = json.loads(result.output)
        assert payload["process"]["pid"] == 1234
        assert payload["process"]["ports"] == [9000]

    @pytest.mark.asyncio
    async def test_get_by_pid_with_port_filter_requires_port_lookup(
        self,
        skill: GetProcessSkill,
        monkeypatch,
    ) -> None:
        def _fake_get_process_filter_view(
            pid: int,
            include_ports: bool = False,
            port_lookup_required: bool = False,
        ) -> dict[str, object]:
            assert pid == 1234
            assert include_ports is True
            assert port_lookup_required is True
            raise ValueError("Port-based process lookup is unavailable on this host.")

        monkeypatch.setattr(
            "nexus3.skill.builtin.processes.get_process_filter_view",
            _fake_get_process_filter_view,
        )

        result = await skill.execute(pid=1234, port=3000)

        assert result.error is not None
        assert "Port-based process lookup is unavailable" in result.error

    @pytest.mark.asyncio
    async def test_get_by_pid_query_uses_raw_command_for_matching(
        self,
        skill: GetProcessSkill,
        monkeypatch,
    ) -> None:
        monkeypatch.setattr(
            "nexus3.skill.builtin.processes.get_process_filter_view",
            lambda pid, include_ports=False, port_lookup_required=False: {
                "pid": pid,
                "name": "python",
                "username": "alice",
                "command": "python worker.py --token expected-secret",
                "ports": [],
            },
        )
        monkeypatch.setattr(
            "nexus3.skill.builtin.processes.get_process_details",
            lambda pid, include_ports=True, port_lookup_required=False: {
                "pid": pid,
                "name": "python",
                "username": "alice",
                "command_preview": "python worker.py --token [REDACTED]",
                "ports": [],
            },
        )

        result = await skill.execute(pid=1234, query="expected-secret")

        assert not result.error
        payload = json.loads(result.output)
        assert payload["process"]["pid"] == 1234

    @pytest.mark.asyncio
    async def test_get_port_zero_is_treated_as_omitted(
        self,
        skill: GetProcessSkill,
        monkeypatch,
    ) -> None:
        monkeypatch.setattr(
            "nexus3.skill.builtin.processes.get_process_filter_view",
            lambda pid, include_ports=False, port_lookup_required=False: {
                "pid": pid,
                "name": "python",
                "username": "alice",
                "command": "python worker.py",
                "ports": [],
            },
        )
        monkeypatch.setattr(
            "nexus3.skill.builtin.processes.get_process_details",
            lambda pid, include_ports=True, port_lookup_required=False: {
                "pid": pid,
                "name": "python",
                "username": "alice",
                "command_preview": "python worker.py",
                "ports": [],
            },
        )

        result = await skill.execute(pid=1234, port=0)

        assert not result.error
        payload = json.loads(result.output)
        assert payload["process"]["pid"] == 1234

    @pytest.mark.asyncio
    async def test_get_by_query_requires_unique_match(
        self,
        skill: GetProcessSkill,
        monkeypatch,
    ) -> None:
        fake_processes = [
            _FakeProcess(
                {
                    "pid": 50,
                    "ppid": 1,
                    "name": "python",
                    "status": "running",
                    "username": "alice",
                    "create_time": 1700000000.0,
                    "cmdline": ["python", "worker.py"],
                }
            ),
            _FakeProcess(
                {
                    "pid": 51,
                    "ppid": 1,
                    "name": "python",
                    "status": "sleeping",
                    "username": "alice",
                    "create_time": 1700000001.0,
                    "cmdline": ["python", "other.py"],
                }
            ),
        ]
        monkeypatch.setattr(
            "nexus3.skill.builtin.processes.psutil.process_iter",
            lambda attrs=None: fake_processes,
        )

        result = await skill.execute(query="python", match="contains")

        assert result.error is not None
        assert "Multiple processes matched" in result.error
        assert "50:python" in result.error

    @pytest.mark.asyncio
    async def test_invalid_regex_returns_error(self, skill: GetProcessSkill) -> None:
        result = await skill.execute(query="(", match="regex")
        assert result.error is not None
        assert "Invalid regex pattern" in result.error

    def test_factory_creates_skill(self) -> None:
        skill = get_process_factory(_make_services())
        assert isinstance(skill, GetProcessSkill)


class _FakePidProcess:
    def __init__(self, pid: int) -> None:
        self.pid = pid


def test_protected_termination_reason_blocks_tree_with_protected_descendant(monkeypatch) -> None:
    monkeypatch.setattr(
        "nexus3.core.process_tools.psutil.Process",
        lambda pid: _FakePidProcess(pid),
    )
    monkeypatch.setattr(
        "nexus3.core.process_tools._collect_termination_targets",
        lambda process, tree: [_FakePidProcess(3210), _FakePidProcess(9999)],
    )
    monkeypatch.setattr(
        "nexus3.core.process_tools.get_protected_pids",
        lambda: {9999},
    )

    reason = protected_termination_reason(3210, tree=True)

    assert reason is not None
    assert "9999" in reason
    assert "tree termination" in reason


class TestKillProcessSkill:
    @pytest.fixture
    def skill(self) -> KillProcessSkill:
        return KillProcessSkill(_make_services())

    @pytest.mark.asyncio
    async def test_kill_process_terminates_real_process(self, skill: KillProcessSkill) -> None:
        kwargs = {"creationflags": WINDOWS_CREATIONFLAGS} if sys.platform == "win32" else {
            "start_new_session": True
        }
        proc = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **kwargs,
        )

        try:
            result = await skill.execute(pid=proc.pid)
            assert not result.error

            payload = json.loads(result.output)
            assert payload["target"]["pid"] == proc.pid
            assert payload["result"]["success"] is True
            proc.wait(timeout=5)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)

    @pytest.mark.asyncio
    async def test_kill_process_protects_current_runtime(self, skill: KillProcessSkill) -> None:
        result = await skill.execute(pid=os.getpid())
        assert result.error is not None
        assert "protected PID" in result.error

    @pytest.mark.asyncio
    async def test_kill_process_blocks_protected_descendant_tree(
        self,
        skill: KillProcessSkill,
        monkeypatch,
    ) -> None:
        monkeypatch.setattr(
            "nexus3.skill.builtin.kill_process.protected_termination_reason",
            lambda pid, tree: (
                "Refusing to terminate PID 4321 because tree termination would include "
                "protected PID(s): 9999."
            ),
        )

        result = await skill.execute(pid=4321)

        assert result.error is not None
        assert "tree termination" in result.error
        assert "9999" in result.error

    def test_factory_creates_skill(self) -> None:
        skill = kill_process_factory(_make_services())
        assert isinstance(skill, KillProcessSkill)

    def test_registration(self) -> None:
        from nexus3.skill.builtin.registration import register_builtin_skills
        from nexus3.skill.registry import SkillRegistry

        registry = SkillRegistry(_make_services())
        register_builtin_skills(registry)

        assert registry.get("list_processes") is not None
        assert registry.get("get_process") is not None
        assert registry.get("kill_process") is not None
