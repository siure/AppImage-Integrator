from __future__ import annotations

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk

from appimage_integrator.models import ManagedAppRecord, UpdateCandidate
from appimage_integrator.ui.dialogs import _resolve_parent


class UpdateSourceDialog:
    def __init__(
        self,
        parent: Gtk.Widget | Gtk.Window | None,
        record: ManagedAppRecord,
        candidates: list[UpdateCandidate],
    ) -> None:
        self._parent = _resolve_parent(parent)
        self._window = Gtk.Window(
            title="Choose AppImage Update",
            transient_for=self._parent,
            modal=True,
            resizable=True,
        )
        self._window.add_css_class("integrator-dialog")
        self._window.add_css_class("update-source-dialog")
        self._window.set_default_size(640, 420)
        self._window.set_size_request(420, 320)

        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)
        header.set_title_widget(Gtk.Label(label="Choose AppImage Update"))
        self._window.set_titlebar(header)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.set_margin_top(20)
        content.set_margin_bottom(20)
        content.set_margin_start(20)
        content.set_margin_end(20)

        intro = Gtk.Label(
            label=(
                f"AppImage Integrator found {len(candidates)} matching AppImages for {record.display_name}.\n\n"
                "Select one to continue, or browse for a different file."
            )
        )
        intro.add_css_class("dialog-body")
        intro.set_wrap(True)
        intro.set_xalign(0)
        intro.set_justify(Gtk.Justification.LEFT)
        content.append(intro)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_hexpand(True)
        scrolled.set_vexpand(True)
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)

        list_box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        list_box.add_css_class("update-source-list")
        list_box.connect("row-selected", self._on_row_selected)
        self.list_box = list_box
        scrolled.set_child(list_box)
        content.append(scrolled)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        actions.add_css_class("dialog-actions")
        actions.set_halign(Gtk.Align.END)
        content.append(actions)

        self._window.set_child(content)
        self._responses: dict[str, Gtk.Button] = {}
        self._response_handlers: list[tuple[object, tuple[object, ...]]] = []
        self._close_response = "cancel"
        self._response_emitted = False
        self._window.connect("close-request", self._on_close_request)

        self._add_response(actions, "cancel", "Cancel")
        self._add_response(actions, "browse", "Browse…")
        use_button = self._add_response(actions, "use", "Use Selected")
        use_button.add_css_class("suggested-action")
        use_button.set_sensitive(False)
        self.use_button = use_button

        for candidate in candidates:
            list_box.append(self._build_row(candidate))

        first_row = list_box.get_row_at_index(0)
        if first_row is not None:
            list_box.select_row(first_row)
        self._sync_row_selection_classes()

    def _add_response(self, container: Gtk.Box, response_id: str, label: str) -> Gtk.Button:
        button = Gtk.Button(label=label)
        button.add_css_class("dialog-button")
        button.connect("clicked", lambda _button, rid=response_id: self._emit_response(rid))
        container.append(button)
        self._responses[response_id] = button
        return button

    def _build_row(self, candidate: UpdateCandidate) -> Gtk.ListBoxRow:
        row = Gtk.ListBoxRow()
        row.add_css_class("update-source-row")
        action_row = Adw.ActionRow()
        if hasattr(action_row, "set_use_markup"):
            action_row.set_use_markup(False)
        action_row.set_title(candidate.path.name)
        action_row.set_subtitle(
            "\n".join(
                [
                    f"Version: {candidate.detected_version or 'unknown'}",
                    f"Match: {'identity-based' if candidate.match_kind == 'identity' else 'filename fallback'}",
                    f"Location: {candidate.path.parent}",
                ]
            )
        )
        action_row.set_activatable(True)

        badges = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        badges.set_valign(Gtk.Align.CENTER)
        if not candidate.is_executable:
            badges.append(self._build_badge("Not executable", "warning"))
        if candidate.detected_version is None:
            badges.append(self._build_badge("Version unknown", "warning"))
        action_row.add_suffix(badges)

        row.set_child(action_row)
        row._candidate = candidate
        return row

    def _build_badge(self, text: str, css_class: str) -> Gtk.Label:
        badge = Gtk.Label(label=text)
        badge.add_css_class("status-badge")
        badge.add_css_class(css_class)
        return badge

    def connect(self, signal: str, callback, *args) -> None:
        if signal != "response":
            raise ValueError(f"Unsupported signal for UpdateSourceDialog: {signal}")
        self._response_handlers.append((callback, args))

    def present(self) -> None:
        self._window.present()

    def get_selected_candidate(self) -> UpdateCandidate | None:
        row = self.list_box.get_selected_row()
        return getattr(row, "_candidate", None) if row is not None else None

    def _on_row_selected(self, _list_box: Gtk.ListBox, row: Gtk.ListBoxRow | None) -> None:
        self.use_button.set_sensitive(row is not None)
        self._sync_row_selection_classes()

    def _sync_row_selection_classes(self) -> None:
        current = self.list_box.get_first_child()
        selected = self.list_box.get_selected_row()
        while current is not None:
            if current is selected:
                current.add_css_class("selected")
            else:
                current.remove_css_class("selected")
            current = current.get_next_sibling()

    def _emit_response(self, response_id: str) -> None:
        if self._response_emitted:
            return
        self._response_emitted = True
        selected = self.get_selected_candidate()
        for callback, args in self._response_handlers:
            callback(self, response_id, selected, *args)
        self._window.close()

    def _on_close_request(self, _window: Gtk.Window) -> bool:
        if not self._response_emitted and self._close_response is not None:
            self._emit_response(self._close_response)
        return False
