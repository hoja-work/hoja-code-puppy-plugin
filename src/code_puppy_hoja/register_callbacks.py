"""Code Puppy entry point (``[project.entry-points."code_puppy.plugins"] hoja``).

Importing this module only registers callbacks. Nothing starts until Code Puppy first needs the session: the Node
runtime spawns when the first agent is built, never at import.
"""

from __future__ import annotations

from code_puppy.callbacks import register_callback

from .adapter import PuppyAdapter, command_help
from .settings import load_settings, settings_category

adapter = PuppyAdapter(load_settings)

register_callback("register_settings", settings_category)
register_callback("load_prompt", adapter.load_prompt)
register_callback("register_tools", adapter.register_tools)
register_callback("register_agent_tools", adapter.agent_tools)
register_callback("user_prompt_submit", adapter.user_prompt_submit)
register_callback("pre_tool_call", adapter.pre_tool_call)
register_callback("post_tool_call", adapter.post_tool_call)
register_callback("transform_model_messages", adapter.transform_model_messages)
register_callback("agent_run_result", adapter.agent_run_result)
register_callback("custom_command", adapter.custom_command)
register_callback("custom_command_help", command_help)
register_callback("shutdown", adapter.shutdown)
