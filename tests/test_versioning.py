from __future__ import annotations

from appimage_integrator.services.versioning import compare_versions


def test_compare_versions() -> None:
    assert compare_versions("2.0.0", "1.9.9") == 1
    assert compare_versions("1.0.0", "1.0.0") == 0
    assert compare_versions("1.0.0-beta", "1.0.0") == -1
    assert compare_versions(None, "1.0.0") == -1
    assert compare_versions("1.0.0", None) == 1
    assert compare_versions(None, None) == 0
