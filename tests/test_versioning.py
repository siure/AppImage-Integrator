from __future__ import annotations

from appimage_integrator.services.versioning import compare_update_versions, compare_versions


def test_compare_versions() -> None:
    assert compare_versions("2.0.0", "1.9.9") == 1
    assert compare_versions("v2.0.0", "2.0.0") == 0
    assert compare_versions("1.0.0", "1.0.0") == 0
    assert compare_versions("1.0.0-beta", "1.0.0") == -1
    assert compare_versions(None, "1.0.0") == -1
    assert compare_versions("1.0.0", None) == 1
    assert compare_versions(None, None) == 0


def test_compare_update_versions_keeps_stable_and_nightly_channels_separate() -> None:
    assert compare_update_versions("v0.0.22-nightly.20260506.201", "v0.0.22-nightly.20260505.201") == 1
    assert compare_update_versions("v0.0.22-nightly.20260505.201", "v0.0.22") is None
    assert compare_update_versions("v0.0.23-nightly.20260506.201", "v0.0.22") is None
    assert compare_update_versions("v0.0.23", "v0.0.22") == 1
