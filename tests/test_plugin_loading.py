"""Code Puppy's own loader finds the plugin through its entry point."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PROBE = """
import json
from code_puppy import callbacks
from code_puppy.plugins import load_plugin_callbacks
load_plugin_callbacks()
phases = ["load_prompt", "register_tools", "pre_tool_call", "post_tool_call", "agent_run_result", "custom_command",
          "transform_model_messages", "user_prompt_submit", "register_settings", "shutdown"]
print(json.dumps({p: any(getattr(cb, "__module__", "").startswith("code_puppy_hoja")
                         or getattr(getattr(cb, "__self__", None), "__module__", "").startswith("code_puppy_hoja")
                         for cb in callbacks.get_callbacks(p)) for p in phases}))
"""


def test_entry_point_registers_every_callback(tmp_path: Path) -> None:
    env = {
        **os.environ,
        "HOME": str(tmp_path),
        "XDG_CONFIG_HOME": str(tmp_path / "cfg"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
    }
    done = subprocess.run(
        [sys.executable, "-c", PROBE], capture_output=True, text=True, env=env, cwd=tmp_path, timeout=120, check=False
    )
    assert done.returncode == 0, done.stderr[-2000:]
    registered = json.loads(done.stdout.strip().splitlines()[-1])
    assert all(registered.values()), registered


def test_import_starts_nothing(tmp_path: Path) -> None:
    probe = "import code_puppy_hoja.register_callbacks as r; print(r.adapter._session is None)"
    env = {**os.environ, "HOME": str(tmp_path)}
    done = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, env=env, timeout=60, check=False
    )
    assert done.stdout.strip() == "True", done.stderr[-2000:]
