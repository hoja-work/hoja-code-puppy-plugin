"""Fixtures. Code Puppy runs against a throwaway HOME; no test reaches a model provider or a Hoja workspace."""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic_ai import models
from pydantic_ai_hoja import HojaSettings

from code_puppy_hoja.adapter import PuppyAdapter

models.ALLOW_MODEL_REQUESTS = False
os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

requires_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js 22+ is not installed")


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture
def local_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> HojaSettings:
    for name in list(os.environ):
        if name.startswith(("HOJA_", "LINEAR_")):
            monkeypatch.delenv(name)
    path = os.pathsep.join(p for p in os.environ["PATH"].split(os.pathsep) if not (Path(p) / "hoja").exists())
    monkeypatch.setenv("PATH", path)
    return HojaSettings.from_env(data_dir=tmp_path / "data", hoja_mode=False, hosted_api=False)


@pytest.fixture
def adapter(local_settings: HojaSettings, workspace: Path) -> Iterator[PuppyAdapter]:
    puppy = PuppyAdapter(lambda: local_settings, cwd=workspace)
    yield puppy
    puppy.shutdown()
