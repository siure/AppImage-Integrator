from __future__ import annotations

from pathlib import Path

from appimage_integrator.config import APP_ID


PACKAGE_ROOT = Path(__file__).resolve().parent
UI_ROOT = PACKAGE_ROOT / "ui"
ICON_THEME_ROOT = UI_ROOT / "assets"
APP_ICON_PATH = ICON_THEME_ROOT / "hicolor" / "512x512" / "apps" / f"{APP_ID}.png"
APP_BRAND_LOGO_PATH = PACKAGE_ROOT / "assets" / "branding" / "app-brand.png"
APP_DESKTOP_ENTRY_PATH = PACKAGE_ROOT / "assets" / "desktop" / f"{APP_ID}.desktop"
