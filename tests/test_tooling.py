from __future__ import annotations

import logging
import sys

from appimage_integrator.services import tooling as tooling_module
from appimage_integrator.services.tooling import Tooling


def test_tooling_times_out_commands() -> None:
    tooling = Tooling(logging.getLogger("tests.tooling"))

    result = tooling.run(
        [sys.executable, "-c", "import time; time.sleep(1)"],
        timeout=0.01,
    )

    assert result.returncode == 124
    assert "timed out" in result.stderr


def test_tooling_truncates_captured_output(monkeypatch) -> None:
    monkeypatch.setattr(tooling_module, "MAX_CAPTURED_OUTPUT_BYTES", 8)
    tooling = Tooling(logging.getLogger("tests.tooling"))

    result = tooling.run([sys.executable, "-c", "print('x' * 20)"])

    assert result.stdout.startswith("xxxxxxxx")
    assert "[truncated" in result.stdout
