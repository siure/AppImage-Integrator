from __future__ import annotations

APP_ID = "io.github.appimageintegrator"
APP_NAME = "AppImage Integrator"
APP_DATA_DIR_NAME = "appimage-integrator"
SCHEMA_VERSION = 1

PRESET_ARGUMENTS: dict[str, tuple[str, ...]] = {
    "none": (),
    "chromium_no_sandbox": ("--no-sandbox",),
    "prefer_wayland": ("--ozone-platform-hint=auto",),
    "disable_gpu": ("--disable-gpu",),
}

PRESET_LABELS: dict[str, str] = {
    "none": "None",
    "chromium_no_sandbox": "Chromium sandbox-friendly",
    "prefer_wayland": "Wayland hint",
    "disable_gpu": "Disable GPU",
}

STEPPER_STEPS = (
    "Verify AppImage",
    "Extract Metadata",
    "Prepare Install Location",
    "Resolve Icon",
    "Write Desktop Entry",
    "Finalize Registration",
)
