from __future__ import annotations

import hashlib
import re

from appimage_integrator.models import AppImageInspection, IdentityResolution


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "appimage"


class IdResolver:
    def resolve(self, inspection: AppImageInspection) -> IdentityResolution:
        if inspection.appstream_id:
            basis = inspection.appstream_id.strip()
            slug_source = basis
        elif inspection.embedded_desktop_filename:
            basis = inspection.embedded_desktop_filename.rsplit(".", 1)[0]
            slug_source = basis
        else:
            name = inspection.detected_name or "appimage"
            icon = inspection.desktop_entry.icon_key if inspection.desktop_entry else ""
            startup = inspection.startup_wm_class or ""
            basis = "|".join((name.strip(), startup.strip(), icon.strip()))
            slug_source = name
        digest = hashlib.sha256(basis.encode("utf-8")).hexdigest()
        return IdentityResolution(
            internal_id=f"{_slugify(slug_source)}-{digest[:8]}",
            identity_fingerprint=digest,
            basis=basis,
        )
