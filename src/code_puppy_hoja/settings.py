"""Settings: environment variables first, then ``hoja_*`` keys in ``puppy.cfg`` (``/set hoja_project Team``)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from pydantic_ai_hoja import HojaSettings

#: ``puppy.cfg`` key → (environment variable, description). Booleans map to the variable that turns a feature off.
CONFIG_KEYS: dict[str, tuple[str, str]] = {
    "hoja_api_url": ("HOJA_API_URL", "Hoja GraphQL endpoint, e.g. https://acme.hoja.work/graphql"),
    "hoja_mcp_url": ("HOJA_MCP_URL", "Hosted MCP endpoint (derived from the GraphQL host when unset)"),
    "hoja_token": ("HOJA_TOKEN", "Personal API token (or sign in with `hoja auth login`)"),
    "hoja_project": ("HOJA_PROJECT", "Default Hoja project for published tasks"),
    "hoja_enforcement": ("HOJA_TASK_ENFORCEMENT", "Task gate: block · advise · off"),
    "hoja_trace_upload": ("HOJA_TRACE_UPLOAD", "Trace upload: completion · session-end · manual · off"),
    "hoja_trace_detail": ("HOJA_TRACE_DETAIL", "Trace detail: full · metadata"),
    "hoja_mode": ("HOJA_PLUGIN_DISABLE_HOJA", "Publish coarse tasks to Hoja (true/false)"),
    "hoja_hosted_api": ("HOJA_DISABLE_HOSTED_API", "Expose the hosted Hoja API's tools (true/false)"),
}
_INVERTED = {"hoja_mode", "hoja_hosted_api"}
_FALSE = {"0", "false", "no", "off"}


def _config_value(key: str) -> str | None:
    try:
        from code_puppy.config import get_value
    except ImportError:  # running outside Code Puppy (tests, scripts)
        return None
    value = get_value(key)
    return str(value).strip() if value not in (None, "") else None


def default_data_dir() -> Path:
    try:
        from code_puppy.config import DATA_DIR

        return Path(DATA_DIR) / "hoja"
    except ImportError:
        return Path.home() / ".code_puppy" / "hoja"


def load_settings(env: dict[str, str] | None = None, **overrides: Any) -> HojaSettings:
    """``HojaSettings`` for this Code Puppy: an environment variable wins over the matching ``puppy.cfg`` key."""
    source = dict(os.environ if env is None else env)
    merged: dict[str, str] = {}
    for key, (variable, _) in CONFIG_KEYS.items():
        value = _config_value(key)
        if value is None:
            continue
        if key in _INVERTED:
            if value.lower() in _FALSE:
                merged[variable] = "1"
        else:
            merged[variable] = value
    merged.update(source)
    merged.setdefault("HOJA_DATA_DIR", str(default_data_dir()))
    return HojaSettings.from_env(merged, **overrides)


def settings_category() -> Any:
    """The ``Hoja`` section of Code Puppy's ``/set`` menu."""
    from code_puppy.command_line.set_menu_schema import Setting, SettingsCategory

    def choice(key: str, *values: str) -> Setting:
        return Setting(key, key, CONFIG_KEYS[key][1], "choice", valid_values=values, requires_restart=True)

    return SettingsCategory(
        name="Hoja",
        settings=(
            Setting("hoja_api_url", "hoja_api_url", CONFIG_KEYS["hoja_api_url"][1], "string", requires_restart=True),
            Setting("hoja_mcp_url", "hoja_mcp_url", CONFIG_KEYS["hoja_mcp_url"][1], "string", requires_restart=True),
            Setting(
                "hoja_token",
                "hoja_token",
                CONFIG_KEYS["hoja_token"][1],
                "string",
                sensitive=True,
                requires_restart=True,
            ),
            Setting("hoja_project", "hoja_project", CONFIG_KEYS["hoja_project"][1], "string", requires_restart=True),
            choice("hoja_enforcement", "block", "advise", "off"),
            choice("hoja_trace_upload", "completion", "session-end", "manual", "off"),
            choice("hoja_trace_detail", "full", "metadata"),
            Setting("hoja_mode", "hoja_mode", CONFIG_KEYS["hoja_mode"][1], "bool", requires_restart=True),
            Setting(
                "hoja_hosted_api", "hoja_hosted_api", CONFIG_KEYS["hoja_hosted_api"][1], "bool", requires_restart=True
            ),
        ),
    )
