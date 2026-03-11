from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("GdkPixbuf", "2.0")
from gi.repository import GdkPixbuf

from appimage_integrator.services.icon_resolver import IconResolver


def _write_png(path: Path, width: int, height: int) -> None:
    pixbuf = GdkPixbuf.Pixbuf.new(GdkPixbuf.Colorspace.RGB, True, 8, width, height)
    pixbuf.fill(0x336699FF)
    pixbuf.savev(str(path), "png", [], [])


def test_icon_resolver_prefers_svg_then_largest_png(test_paths) -> None:
    extracted = test_paths.cache_extract_dir / "fixture"
    extracted.mkdir(parents=True)
    (extracted / "demo.svg").write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")
    _write_png(extracted / "small.png", 16, 16)
    _write_png(extracted / "large.png", 128, 128)

    resolver = IconResolver(test_paths)
    candidates = resolver.collect_candidates(extracted, None)
    assert candidates[0].relpath == "demo.svg"
    assert any(candidate.relpath == "large.png" for candidate in candidates)


def test_icon_resolver_prefers_desktop_icon_key_over_large_generic_images(test_paths) -> None:
    extracted = test_paths.cache_extract_dir / "fixture-key"
    extracted.mkdir(parents=True)
    icon_dir = extracted / "usr" / "share" / "icons" / "hicolor" / "256x256" / "apps"
    icon_dir.mkdir(parents=True)
    _write_png(icon_dir / "demo.png", 256, 256)
    marketing_dir = extracted / "marketing"
    marketing_dir.mkdir()
    _write_png(marketing_dir / "hero.png", 1920, 1080)

    resolver = IconResolver(test_paths)
    candidates = resolver.collect_candidates(extracted, "demo")

    assert candidates[0].relpath == "usr/share/icons/hicolor/256x256/apps/demo.png"


def test_icon_resolver_installs_icon(test_paths) -> None:
    extracted = test_paths.cache_extract_dir / "fixture"
    extracted.mkdir(parents=True)
    svg_path = extracted / "demo.svg"
    svg_path.write_text("<svg xmlns='http://www.w3.org/2000/svg'></svg>", encoding="utf-8")
    resolver = IconResolver(test_paths)
    candidate = resolver.collect_candidates(extracted, None)[0]
    icon_value, managed_path, managed = resolver.install_icon("demo-1234", candidate)
    assert managed
    assert managed_path is not None
    assert Path(icon_value).exists()
