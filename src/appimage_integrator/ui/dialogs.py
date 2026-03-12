from __future__ import annotations

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gtk


def _resolve_parent(parent: Gtk.Widget | Gtk.Window | None) -> Gtk.Window | None:
    if parent is None:
        return None
    if isinstance(parent, Gtk.Window):
        return parent
    root = parent.get_root()
    return root if isinstance(root, Gtk.Window) else None


class CompatMessageDialog:
    def __init__(self, parent: Gtk.Widget | Gtk.Window | None, title: str, body: str) -> None:
        self._parent = _resolve_parent(parent)
        self._window = Gtk.Window(
            title=title,
            transient_for=self._parent,
            modal=True,
            resizable=False,
        )
        self._window.add_css_class("integrator-dialog")
        self._window.add_css_class("integrator-message-dialog")
        self._window.set_default_size(480, -1)
        self._window.set_size_request(360, -1)

        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(True)
        header.set_title_widget(Gtk.Label(label=title))
        self._window.set_titlebar(header)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        content.set_margin_top(20)
        content.set_margin_bottom(20)
        content.set_margin_start(20)
        content.set_margin_end(20)

        body_label = Gtk.Label(label=body)
        body_label.add_css_class("dialog-body")
        body_label.set_wrap(True)
        body_label.set_xalign(0)
        body_label.set_justify(Gtk.Justification.LEFT)
        body_label.set_selectable(True)
        content.append(body_label)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        actions.add_css_class("dialog-actions")
        actions.set_halign(Gtk.Align.END)
        content.append(actions)

        self._window.set_child(content)
        self._actions = actions
        self._responses: dict[str, Gtk.Button] = {}
        self._response_handlers: list[tuple[object, tuple[object, ...]]] = []
        self._default_response: str | None = None
        self._close_response: str | None = None
        self._response_emitted = False

        self._window.connect("close-request", self._on_close_request)

    def add_response(self, response_id: str, label: str) -> None:
        button = Gtk.Button(label=label)
        button.add_css_class("dialog-button")
        button.connect("clicked", lambda _button, rid=response_id: self._emit_response(rid))
        self._actions.append(button)
        self._responses[response_id] = button

    def set_default_response(self, response_id: str) -> None:
        self._default_response = response_id
        button = self._responses.get(response_id)
        if button is not None:
            button.set_receives_default(True)
            if hasattr(self._window, "set_default_widget"):
                self._window.set_default_widget(button)

    def set_close_response(self, response_id: str) -> None:
        self._close_response = response_id

    def set_response_appearance(self, response_id: str, appearance) -> None:
        button = self._responses.get(response_id)
        if button is None:
            return
        if appearance == Adw.ResponseAppearance.SUGGESTED:
            button.add_css_class("suggested-action")
            return
        if appearance == Adw.ResponseAppearance.DESTRUCTIVE:
            button.add_css_class("destructive-action")

    def connect(self, signal: str, callback, *args) -> None:
        if signal != "response":
            raise ValueError(f"Unsupported signal for CompatMessageDialog: {signal}")
        self._response_handlers.append((callback, args))

    def present(self) -> None:
        if self._default_response is not None:
            button = self._responses.get(self._default_response)
            if button is not None:
                button.grab_focus()
                if hasattr(self._window, "set_default_widget"):
                    self._window.set_default_widget(button)
        self._window.present()

    def _emit_response(self, response_id: str) -> None:
        if self._response_emitted:
            return
        self._response_emitted = True
        for callback, args in self._response_handlers:
            callback(self, response_id, *args)
        self._window.close()

    def _on_close_request(self, _window: Gtk.Window) -> bool:
        if not self._response_emitted and self._close_response is not None:
            self._emit_response(self._close_response)
        return False


class CompatFileChooserDialog:
    def __init__(
        self,
        parent: Gtk.Widget | Gtk.Window | None,
        *,
        title: str,
        accept_label: str,
    ) -> None:
        self._parent = _resolve_parent(parent)
        self._dialog = Gtk.FileChooserDialog(
            title=title,
            transient_for=self._parent,
            modal=True,
            action=Gtk.FileChooserAction.OPEN,
        )
        self._dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        self._dialog.add_button(accept_label, Gtk.ResponseType.ACCEPT)
        self._dialog.set_default_response(Gtk.ResponseType.ACCEPT)

        appimage_filter = Gtk.FileFilter()
        appimage_filter.set_name("AppImage files")
        appimage_filter.add_pattern("*.AppImage")
        appimage_filter.add_pattern("*.appimage")
        self._dialog.add_filter(appimage_filter)

        all_files_filter = Gtk.FileFilter()
        all_files_filter.set_name("All files")
        all_files_filter.add_pattern("*")
        self._dialog.add_filter(all_files_filter)

    def connect(self, signal: str, callback, *args) -> None:
        def _forward(_dialog, *signal_args):
            return callback(self, *signal_args, *args)

        self._dialog.connect(signal, _forward)

    def present(self) -> None:
        self._dialog.present()

    def get_file(self):
        return self._dialog.get_file()

    def destroy(self) -> None:
        self._dialog.destroy()
