from __future__ import annotations

from typing import Any

import pytest

from code_puppy_hoja import settings as settings_module
from code_puppy_hoja.adapter import PuppyAdapter, command_help

from .conftest import requires_node


class Recorder(PuppyAdapter):
    def __init__(self) -> None:
        super().__init__(lambda: None)  # type: ignore[arg-type, return-value]
        self.calls: list[tuple[str, str]] = []

    @property
    def session(self) -> Any:
        recorder = self

        class Session:
            def command(self, name: str, args: str) -> str:
                recorder.calls.append((name, args))
                return "ok"

        return Session()


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("/hoja", ("tasks", "")),
        ("/tasks", ("tasks", "")),
        ("/hoja tasks", ("tasks", "")),
        ("/hoja:tasks", ("tasks", "")),
        ("/hoja on", ("hoja", "on")),
        ("/hoja status", ("hoja", "status")),
        ("/hoja:hoja off", ("hoja", "off")),
        ("/hoja trace upload HOJA-12", ("trace", "upload HOJA-12")),
        ("/hoja setup", ("setup", "")),
    ],
)
def test_command_routing(typed: str, expected: tuple[str, str]) -> None:
    r = Recorder()
    assert r.custom_command(typed, typed.lstrip("/").split()[0]) == "ok"
    assert r.calls == [expected]


def test_other_commands_are_not_ours() -> None:
    r = Recorder()
    assert r.custom_command("/model gpt", "model") is None
    assert r.calls == []


def test_help_lists_hoja() -> None:
    assert command_help()[0][0] == "hoja"


def test_environment_wins_over_puppy_cfg(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    cfg = {"hoja_project": "From Cfg", "hoja_enforcement": "advise", "hoja_mode": "false", "hoja_token": "cfg-token"}
    monkeypatch.setattr(settings_module, "_config_value", cfg.get)
    s = settings_module.load_settings({"HOJA_PROJECT": "From Env", "HOJA_DATA_DIR": str(tmp_path)})
    assert s.project == "From Env"
    assert s.enforcement == "advise"
    assert s.token == "cfg-token"
    assert not s.hoja_mode
    assert s.hosted_api


@requires_node
def test_runtime_commands(adapter: PuppyAdapter) -> None:
    assert "Tasks" in (adapter.custom_command("/hoja", "hoja") or "")
    assert "Hoja" in (adapter.custom_command("/hoja setup", "hoja") or "")
