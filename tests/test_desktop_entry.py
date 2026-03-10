from __future__ import annotations

from pathlib import Path

from appimage_integrator.models import AppImageInspection
from appimage_integrator.services.desktop_entry import DesktopEntryService, parse_desktop_entry


def test_parse_desktop_entry_extracts_exec_tokens() -> None:
    entry = parse_desktop_entry(
        "[Desktop Entry]\nType=Application\nName=Demo\nExec=AppRun --flag %U\nIcon=demo\n",
        "demo.desktop",
    )
    assert entry.exec_tokens == ["AppRun", "--flag", "%U"]
    assert entry.icon_key == "demo"
    assert entry.is_valid


def test_build_desktop_text_preserves_args_and_placeholders(tooling) -> None:
    service = DesktopEntryService(tooling)
    entry = parse_desktop_entry(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=Demo\n"
        "Comment=Test app\n"
        "Exec=AppRun --existing %U\n"
        "Icon=demo\n"
        "StartupWMClass=Demo\n",
        "demo.desktop",
    )
    inspection = AppImageInspection(
        source_path=Path("/tmp/source.AppImage"),
        is_appimage=True,
        appimage_type="type2",
        is_executable=True,
        detected_name="Demo",
        detected_comment="Test app",
        detected_version="1.0.0",
        appstream_id=None,
        embedded_desktop_filename="demo.desktop",
        desktop_entry=entry,
        chosen_icon_candidate=None,
        startup_wm_class="Demo",
        mime_types=[],
        categories=[],
        terminal=False,
        startup_notify=True,
        exec_placeholders=["%U"],
        warnings=[],
        errors=[],
        extracted_dir=None,
    )

    text, _, exec_template = service.build_desktop_text(
        inspection=inspection,
        appimage_path=Path("/home/test/Applications/demo.AppImage"),
        icon_value="/home/test/icon.svg",
        display_name="Demo",
        comment="Custom comment",
        extra_args=["--user-flag"],
        arg_preset_id="disable_gpu",
    )

    assert "Exec=/home/test/Applications/demo.AppImage --existing --disable-gpu --user-flag %U" in text
    assert "TryExec=/home/test/Applications/demo.AppImage" in text
    assert exec_template == "/home/test/Applications/demo.AppImage --existing --disable-gpu --user-flag %U"


def test_build_desktop_text_generates_fallback(tooling) -> None:
    service = DesktopEntryService(tooling)
    inspection = AppImageInspection(
        source_path=Path("/tmp/source.AppImage"),
        is_appimage=True,
        appimage_type="type2",
        is_executable=True,
        detected_name="Fallback App",
        detected_comment=None,
        detected_version=None,
        appstream_id=None,
        embedded_desktop_filename=None,
        desktop_entry=None,
        chosen_icon_candidate=None,
        startup_wm_class=None,
        mime_types=[],
        categories=[],
        terminal=None,
        startup_notify=None,
        exec_placeholders=[],
        warnings=[],
        errors=[],
        extracted_dir=None,
    )
    text, _, _ = service.build_desktop_text(
        inspection=inspection,
        appimage_path=Path("/home/test/Applications/fallback.AppImage"),
        icon_value="application-x-executable",
        display_name="Fallback App",
        comment=None,
        extra_args=[],
        arg_preset_id="none",
    )
    assert "[Desktop Entry]" in text
    assert "Name=Fallback App" in text
    assert "Terminal=false" in text
