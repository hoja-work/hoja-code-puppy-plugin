"""End to end through Code Puppy's patched tool path (pre_tool_call / post_tool_call) and the real runtime."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from code_puppy import callbacks
from code_puppy.pydantic_patches import patch_tool_call_callbacks
from pydantic_ai import Agent
from pydantic_ai.messages import (
    ModelMessage,
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.models.function import AgentInfo, FunctionModel

from code_puppy_hoja.adapter import PuppyAdapter

from .conftest import requires_node

pytestmark = requires_node

PHASES = ("pre_tool_call", "post_tool_call")


@pytest.fixture
def wired(adapter: PuppyAdapter) -> Iterator[PuppyAdapter]:
    assert patch_tool_call_callbacks()
    saved = {p: list(callbacks.get_callbacks(p)) for p in PHASES}
    for phase in PHASES:
        callbacks.clear_callbacks(phase)
    callbacks.register_callback("pre_tool_call", adapter.pre_tool_call)
    callbacks.register_callback("post_tool_call", adapter.post_tool_call)
    yield adapter
    for phase in PHASES:
        callbacks.clear_callbacks(phase)
        for cb in saved[phase]:
            callbacks.register_callback(phase, cb)


def puppy_agent(
    adapter: PuppyAdapter, steps: list[ModelResponse], seen: list[str], workspace: Path
) -> Agent[None, str]:
    def respond(messages: list[ModelMessage], info: AgentInfo) -> ModelResponse:
        last = messages[-1]
        if isinstance(last, ModelRequest):
            seen.extend(f"{p.tool_name}: {p.content}" for p in last.parts if isinstance(p, ToolReturnPart))
        return steps.pop(0) if steps else ModelResponse(parts=[TextPart("Done.")])

    agent: Agent[None, str] = Agent(FunctionModel(respond))

    @agent.tool_plain
    def shell(command: str) -> str:
        """Code Puppy's shell tool, reduced."""
        return (
            subprocess.run(command, shell=True, cwd=workspace, capture_output=True, text=True, check=False).stdout
            or "(ok)"
        )

    for registration in adapter.register_tools():  # exactly what Code Puppy's tool registry does
        registration["register_func"](agent)
    return agent


def call(tool: str, args: dict[str, Any], call_id: str) -> ModelResponse:
    return ModelResponse(parts=[ToolCallPart(tool, args, tool_call_id=call_id)])


def task(op: dict[str, Any], call_id: str) -> ModelResponse:
    return call("TaskManage", {"operations": [op]}, call_id)


def test_gate_through_code_puppy_hooks(wired: PuppyAdapter, workspace: Path) -> None:
    seen: list[str] = []
    steps = [
        call("shell", {"command": "touch proof.txt"}, "c1"),
        task(
            {
                "key": "t",
                "op": "create",
                "subject": "Create proof.txt",
                "status": "in_progress",
                "active": True,
                "questions": [{"id": "f", "text": "Does proof.txt exist?"}],
            },
            "c2",
        ),
        call("shell", {"command": "touch proof.txt"}, "c3"),
        task(
            {
                "key": "d",
                "op": "update",
                "taskId": "1",
                "status": "completed",
                "answers": [{"question": "f", "answer": "yes", "evidence": "tool:Bash#2"}],
            },
            "c4",
        ),
    ]
    puppy_agent(wired, steps, seen, workspace).run_sync("Create proof.txt")

    assert seen[0].startswith("shell: ERROR: 🚫 Hook blocked this tool call")
    assert "TASK ENFORCEMENT" in seen[0]
    assert seen[2].endswith("(ok)")
    assert (workspace / "proof.txt").exists()
    assert json.loads(seen[3].removeprefix("TaskManage: "))["status"] == "succeeded"
    assert "✓ #1 Create proof.txt [completed]" in (wired.custom_command("/hoja", "hoja") or "")


def test_invented_evidence_is_rejected(wired: PuppyAdapter, workspace: Path) -> None:
    seen: list[str] = []
    steps = [
        task(
            {
                "key": "t",
                "op": "create",
                "subject": "Ship it",
                "status": "in_progress",
                "active": True,
                "questions": [{"id": "f", "text": "Shipped?"}],
            },
            "c1",
        ),
        task(
            {
                "key": "d",
                "op": "update",
                "taskId": "1",
                "status": "completed",
                "answers": [{"question": "f", "answer": "yes", "evidence": "tool:Bash#9"}],
            },
            "c2",
        ),
    ]
    puppy_agent(wired, steps, seen, workspace).run_sync("Ship it")
    assert json.loads(seen[-1].removeprefix("TaskManage: "))["status"] != "succeeded"


async def test_stop_after_a_block_requests_a_retry(adapter: PuppyAdapter) -> None:
    await adapter.user_prompt_submit("Create proof.txt")
    blocked = await adapter.pre_tool_call("shell", {"command": "touch proof.txt"})
    assert blocked["blocked"] is True

    class Result:
        output = "I was blocked."

    retry = await adapter.agent_run_result(Result(), "code-puppy", "test")
    assert retry is not None
    assert retry["retry"] is True
    assert "AUTO-CONTINUE" in retry["prompt"]


async def test_reminders_ride_on_the_next_request_only(adapter: PuppyAdapter) -> None:
    adapter._pending.append("<system-reminder>hello</system-reminder>")
    original = ModelRequest(parts=[UserPromptPart(content="hi")])
    outbound: list[Any] = [original]
    await adapter.transform_model_messages("code-puppy", outbound)
    assert outbound[0] is not original
    assert [type(p).__name__ for p in outbound[0].parts] == ["UserPromptPart", "UserPromptPart"]
    assert len(original.parts) == 1
    assert adapter._pending == []


def test_reads_pass_without_a_task(wired: PuppyAdapter, workspace: Path) -> None:
    seen: list[str] = []
    puppy_agent(wired, [call("shell", {"command": "ls"}, "c1")], seen, workspace).run_sync("What is here?")
    assert seen == ["shell: (ok)"]


def test_missing_node_fails_open(local_settings: Any, workspace: Path) -> None:
    puppy = PuppyAdapter(lambda: local_settings.replace(node="definitely-not-node"), cwd=workspace)
    assert puppy.register_tools() == []
    assert puppy.load_prompt() is None
    assert not puppy.available
    assert "Node.js" in (puppy.custom_command("/hoja", "hoja") or "")
