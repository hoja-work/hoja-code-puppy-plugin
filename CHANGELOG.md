# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-11-23

### Added

- Code Puppy plugin, loaded through the `code_puppy.plugins` entry point: TaskManage and the Hoja tools on every agent,
  session instructions via `load_prompt`, the task gate on `pre_tool_call`, results via `post_tool_call`, the turn's
  reminders on the next model request via `transform_model_messages`, and gate auto-continue via `agent_run_result`.
- `/hoja` (task board), `/hoja on|off|status`, `/hoja trace [upload ISSUE|path]`, `/hoja setup`, `/tasks`.
- A `Hoja` section in `/set`; `puppy.cfg` keys `hoja_*`, overridden by `HOJA_*` environment variables.
- Fails open: without Node.js the plugin disables itself with one warning and Code Puppy runs as before.
- Built on `pydantic-ai-hoja` 0.1.0 (runtime bundle `hoja-work/hoja-claude-plugin@fea6d15`). Tested with Code Puppy
  0.0.971 (pydantic-ai-slim 2.64).
