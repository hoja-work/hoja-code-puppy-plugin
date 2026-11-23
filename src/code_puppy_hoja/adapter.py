"""``PuppyAdapter``: Code Puppy's callbacks → a :class:`~pydantic_ai_hoja.HojaSession`.

==========================  ==========================  ================================================
Code Puppy callback         Runtime hook                Effect
==========================  ==========================  ================================================
``load_prompt``             ``session-start.mjs``       TaskManage workflow and Hoja-mode rules
``register_tools``          ``tools/list``              TaskManage, ``hoja_*`` tools on every agent
``user_prompt_submit``      ``UserPromptSubmit``        context appended to the prompt
``pre_tool_call``           ``PreToolUse``              ``{"blocked": True, "reason"}`` or context
``post_tool_call``          ``PostToolUse[Failure]``    result recorded; batch end detected
``transform_model_messages`` ``PostToolBatch``          the turn's reminders added to the next request
``agent_run_result``        ``Stop``                    ``{"retry": True, "prompt"}`` to continue
``custom_command``          ``UserPromptExpansion``     ``/hoja tasks`` and friends, no model turn
``shutdown``                ``SessionEnd``              journal and trace flushed
==========================  ==========================  ================================================

Every decision is the runtime's. Every callback fails open: an adapter error is logged and the tool runs, because a
broken plugin must never wedge the user's agent. (The runtime's own decisions are not "errors" and always apply.)
"""

from __future__ import annotations

import logging
import threading
import uuid
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

from pydantic_ai.messages import ModelRequest, UserPromptPart
from pydantic_ai_hoja import HojaRuntimeError, HojaSession, HojaSettings, ToolErrorText, hoja_tool
from pydantic_ai_hoja.runtime import COMMANDS, ToolSpec

logger = logging.getLogger("code_puppy_hoja")

#: Commands the runtime registers, as ``/hoja <command>``. Anything else after ``/hoja`` is Hoja mode's own argument.
_RUNTIME_COMMANDS = {c for c in COMMANDS if c != "hoja"}


class PuppyAdapter:
    """One per Code Puppy process. The session (and the Node runtime) starts on first use."""

    def __init__(self, settings_factory: Callable[[], HojaSettings], cwd: Path | None = None) -> None:
        self._settings_factory = settings_factory
        self._cwd = cwd
        self._session: HojaSession | None = None
        self._lock = threading.Lock()
        self._calls: dict[int, str] = {}  # id(tool_args) → call id; Code Puppy hands both hooks the same dict
        self._inflight: set[str] = set()
        self._tools_ran = False
        self._pending: list[str] = []
        self._disabled_reason: str | None = None

    # -- session -----------------------------------------------------------------------------------------------------

    @property
    def session(self) -> HojaSession:
        with self._lock:
            if self._session is None:
                self._session = HojaSession(settings=self._settings_factory(), cwd=self._cwd or Path.cwd())
            return self._session

    @property
    def available(self) -> bool:
        """False once the runtime failed to start (no Node.js); the plugin then stays out of the way."""
        return self._disabled_reason is None

    def _fail_open(self, where: str, error: Exception) -> None:
        if isinstance(error, HojaRuntimeError) and self._disabled_reason is None:
            self._disabled_reason = str(error)
            _warn(f"Hoja is disabled for this session: {error}")
        else:
            logger.warning("hoja %s failed: %s", where, error, exc_info=logger.isEnabledFor(logging.DEBUG))

    def shutdown(self) -> None:
        if self._session is not None:
            self._session.close()

    # -- prompt and tools --------------------------------------------------------------------------------------------

    def load_prompt(self) -> str | None:
        if not self.available:
            return None
        try:
            return self.session.session_context() or None
        except Exception as error:
            self._fail_open("load_prompt", error)
            return None

    def tool_specs(self) -> list[ToolSpec]:
        if not self.available:
            return []
        try:
            return self.session.tools()
        except Exception as error:
            self._fail_open("register_tools", error)
            return []

    def register_tools(self) -> list[dict[str, Any]]:
        return [{"name": spec.name, "register_func": self._registrar(spec)} for spec in self.tool_specs()]

    def agent_tools(self, agent_name: str | None = None) -> list[str]:
        return [spec.name for spec in self.tool_specs()]

    def _registrar(self, spec: ToolSpec) -> Callable[[Any], None]:
        def register(agent: Any) -> None:
            # A dynamic JSON schema needs Tool.from_schema; pydantic-ai has no public add-tool for an Agent, so the
            # tool goes into its function toolset, which is what @agent.tool does too.
            toolset = getattr(agent, "_function_toolset", None)
            if toolset is None or spec.name in getattr(toolset, "tools", {}):
                return
            toolset.add_tool(hoja_tool(self.session, spec))

        register.__name__ = f"register_{spec.name}"
        return register

    # -- the turn ----------------------------------------------------------------------------------------------------

    async def user_prompt_submit(self, prompt: str, session_id: str | None = None) -> str | None:
        if not self.available:
            return None
        try:
            self._tools_ran = False
            decision = await self.session.user_prompt(prompt)
        except Exception as error:
            self._fail_open("user_prompt_submit", error)
            return None
        if decision.command_output is not None:  # `hoja:tasks` typed without the slash
            _info(decision.command_output)
            return "(The user ran a local Hoja command and saw its output. Acknowledge in one short sentence.)"
        return f"{prompt}\n\n{decision.context}" if decision.context else None

    async def pre_tool_call(self, tool_name: str, tool_args: dict[str, Any], context: Any = None) -> Any:
        if not self.available:
            return None
        call_id = f"puppy_{uuid.uuid4().hex[:16]}"
        try:
            decision = await self.session.pre_tool(tool_name, tool_args, call_id=call_id)
        except Exception as error:
            self._fail_open("pre_tool_call", error)
            return None
        self._tools_ran = True
        if decision.blocked:
            return {"blocked": True, "reason": decision.reason}
        self._calls[id(tool_args)] = call_id
        self._inflight.add(call_id)
        notes = [*self._pending, decision.context]
        self._pending.clear()
        message = "\n\n".join(n for n in notes if n)
        return {"context_message": message} if message else None

    async def post_tool_call(
        self, tool_name: str, tool_args: dict[str, Any], result: Any, duration_ms: float = 0.0, context: Any = None
    ) -> None:
        call_id = self._calls.pop(id(tool_args), None)
        if call_id is None or not self.available:
            return
        self._inflight.discard(call_id)
        failed = isinstance(result, ToolErrorText) or (isinstance(result, dict) and set(result) == {"error"})
        try:
            note = await self.session.post_tool(
                call_id, result.get("error") if failed and isinstance(result, dict) else result, failed=failed
            )
        except Exception as error:
            self._fail_open("post_tool_call", error)
            return
        if note:
            self._pending.append(note)

    async def transform_model_messages(self, agent_name: str | None, messages: list[Any]) -> None:
        """Before each model request: close the finished tool batch and deliver queued reminders.

        Code Puppy has no tool-batch event, so a batch ends at the first model request after tools ran with none still
        in flight. The reminders go into this outbound request only; history is left untouched.
        """
        if not self.available:
            return
        try:
            if self._tools_ran and not self._inflight:
                self._tools_ran = False
                if note := await self.session.tool_batch_end():
                    self._pending.append(note)
        except Exception as error:
            self._fail_open("transform_model_messages", error)
        if not self._pending or not messages or not isinstance(messages[-1], ModelRequest):
            return
        text = "\n\n".join(self._pending)
        self._pending.clear()
        last = messages[-1]
        messages[-1] = replace(last, parts=[*last.parts, UserPromptPart(content=text)])

    async def agent_run_result(self, result: Any, agent_name: str, model_name: str) -> dict[str, Any] | None:
        if not self.available:
            return None
        text = str(getattr(result, "output", "") or "")
        try:
            self.session.model_response(text=text, model=model_name)
            decision = await self.session.stop(text)
        except Exception as error:
            self._fail_open("agent_run_result", error)
            return None
        if decision.notice:
            _warn(decision.notice)
        if decision.continue_with:
            return {"retry": True, "prompt": decision.continue_with, "delay": 0}
        return None

    # -- commands ----------------------------------------------------------------------------------------------------

    def custom_command(self, command: str, name: str) -> str | None:
        """``/hoja``, ``/hoja tasks``, ``/hoja on``, ``/hoja trace upload HOJA-1``, ``/hoja setup``, ``/hoja:tasks``."""
        head, _, rest = command.strip().lstrip("/").partition(" ")
        if head.lower() not in {"hoja", "tasks"} and not head.lower().startswith("hoja:"):
            return None
        sub = head.split(":", 1)[1] if ":" in head else ""
        words = rest.split()
        if not sub:
            sub = "tasks" if head.lower() == "tasks" or not words else words.pop(0)
        sub = sub.lower()
        if sub not in _RUNTIME_COMMANDS and sub != "hoja":
            words.insert(0, sub)  # `/hoja on` → Hoja mode's own command
            sub = "hoja"
        if not self.available:
            return f"Hoja is unavailable: {self._disabled_reason}"
        try:
            return self.session.command(sub, " ".join(words))
        except Exception as error:
            return f"/hoja {sub} failed: {error}"


def command_help() -> list[tuple[str, str]]:
    return [
        ("hoja", "Hoja task board (also: /tasks)"),
        ("hoja on|off|status", "Turn publication to Hoja on or off for this session"),
        ("hoja trace [upload ISSUE|path]", "This session's trace: summary, attach to an issue, or file path"),
        ("hoja setup", "Check credentials, endpoints, project and the task gate"),
    ]


def _info(text: str) -> None:
    try:
        from code_puppy.messaging import emit_info

        emit_info(text)
    except ImportError:
        logger.info("%s", text)


def _warn(text: str) -> None:
    try:
        from code_puppy.messaging import emit_warning

        emit_warning(text)
    except ImportError:
        logger.warning("%s", text)
