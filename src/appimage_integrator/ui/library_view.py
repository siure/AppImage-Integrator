from __future__ import annotations

import gi

gi.require_version("Adw", "1")
gi.require_version("Gtk", "4.0")
from gi.repository import Adw, Gio, Gtk

from appimage_integrator.models import ManagedAppRecord


class LibraryView(Gtk.Box):
    """Gtk.Stack with empty/list states, clamped search + boxed-list of AdwActionRows."""

    def __init__(self, on_launch, on_update, on_show_details, on_repair, on_uninstall) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self.set_hexpand(True)
        self.set_vexpand(True)
        self._on_launch = on_launch
        self._on_update = on_update
        self._on_show_details = on_show_details
        self._on_repair = on_repair
        self._on_uninstall = on_uninstall
        self._records: list[ManagedAppRecord] = []

        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.CROSSFADE)
        self.stack.set_transition_duration(200)
        self.append(self.stack)

        # --- Empty state ---
        empty_status = Adw.StatusPage()
        empty_status.set_icon_name("folder-symbolic")
        empty_status.set_title("No AppImages Yet")
        empty_status.set_description("Installed AppImages will appear here")
        self.stack.add_named(empty_status, "empty")

        # --- List state ---
        list_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        list_page.set_vexpand(True)

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)

        clamp = Adw.Clamp()
        clamp.set_maximum_size(600)
        clamp.set_margin_top(18)
        clamp.set_margin_bottom(18)
        clamp.set_margin_start(12)
        clamp.set_margin_end(12)
        scrolled.set_child(clamp)

        clamp_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        clamp.set_child(clamp_box)

        # Search
        self.search = Gtk.SearchEntry(placeholder_text="Search managed AppImages")
        self.search.connect("search-changed", self._filter_rows)
        clamp_box.append(self.search)

        # ListBox
        self.list_box = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.list_box.add_css_class("boxed-list")
        clamp_box.append(self.list_box)

        list_page.append(scrolled)
        self.stack.add_named(list_page, "list")

        self.stack.set_visible_child_name("empty")

    def set_records(self, records: list[ManagedAppRecord]) -> None:
        while child := self.list_box.get_first_child():
            self.list_box.remove(child)
        self._records = records
        if not records:
            self.stack.set_visible_child_name("empty")
            return
        for record in records:
            self.list_box.append(self._build_row(record))
        self._filter_rows()
        self.stack.set_visible_child_name("list")

    def _build_row(self, record: ManagedAppRecord) -> Gtk.ListBoxRow:
        row = Adw.ActionRow()
        row.set_use_markup(False)
        row.set_title(record.display_name)
        row.set_subtitle(self._subtitle_text(record))
        row.set_tooltip_text(self._tooltip_text(record))

        # Icon prefix
        if record.managed_icon_path:
            image = Gtk.Image.new_from_file(record.managed_icon_path)
        else:
            image = Gtk.Image.new_from_icon_name("application-x-executable")
        image.set_pixel_size(48)
        row.add_prefix(image)

        # Status badge suffix (if there are issues)
        if record.last_validation_status == "warning":
            badge = Gtk.Label(label="Warning")
            badge.add_css_class("status-badge")
            badge.add_css_class("warning")
            badge.set_valign(Gtk.Align.CENTER)
            row.add_suffix(badge)
        elif record.last_validation_status == "error":
            badge = Gtk.Label(label="Error")
            badge.add_css_class("status-badge")
            badge.add_css_class("error")
            badge.set_valign(Gtk.Align.CENTER)
            row.add_suffix(badge)

        # Launch button suffix
        launch_btn = Gtk.Button.new_from_icon_name("media-playback-start-symbolic")
        launch_btn.set_valign(Gtk.Align.CENTER)
        launch_btn.add_css_class("flat")
        launch_btn.set_tooltip_text("Launch")
        launch_btn.connect("clicked", lambda _btn, r=record: self._on_launch(r))
        row.add_suffix(launch_btn)

        # Overflow menu button suffix
        menu_btn = Gtk.MenuButton()
        menu_btn.set_icon_name("view-more-symbolic")
        menu_btn.set_valign(Gtk.Align.CENTER)
        menu_btn.add_css_class("flat")
        menu_btn.set_tooltip_text("More actions")

        # Build menu model
        menu = Gio.Menu()
        menu.append("Search for Update", f"row.update")
        menu.append("Details", f"row.details")
        menu.append("Repair Integration", f"row.repair")
        section = Gio.Menu()
        section.append("Uninstall", f"row.uninstall")
        menu.append_section(None, section)
        menu_btn.set_menu_model(menu)

        # Install action group on the row
        action_group = Gio.SimpleActionGroup()

        action_update = Gio.SimpleAction.new("update", None)
        action_update.connect("activate", lambda _a, _p, r=record: self._on_update(r))
        action_group.add_action(action_update)

        action_details = Gio.SimpleAction.new("details", None)
        action_details.connect("activate", lambda _a, _p, r=record: self._on_show_details(r))
        action_group.add_action(action_details)

        action_repair = Gio.SimpleAction.new("repair", None)
        action_repair.connect("activate", lambda _a, _p, r=record: self._on_repair(r))
        action_group.add_action(action_repair)

        action_uninstall = Gio.SimpleAction.new("uninstall", None)
        action_uninstall.connect("activate", lambda _a, _p, r=record: self._on_uninstall(r))
        action_group.add_action(action_uninstall)

        row.insert_action_group("row", action_group)

        row.add_suffix(menu_btn)

        # Stash reference for filtering
        row._record = record
        return row

    def _subtitle_text(self, record: ManagedAppRecord) -> str:
        version = record.version or "version unknown"
        if not record.last_validation_messages:
            return f"{version} · {record.last_validation_status}"
        first_message = self._truncate_text(record.last_validation_messages[0], 100)
        if len(record.last_validation_messages) == 1:
            return f"{version} · {first_message}"
        return f"{version} · {len(record.last_validation_messages)} issues — {first_message}"

    def _tooltip_text(self, record: ManagedAppRecord) -> str | None:
        if not record.last_validation_messages:
            return None
        return "\n".join(record.last_validation_messages)

    def _truncate_text(self, text: str, limit: int) -> str:
        normalized = " ".join(text.split())
        if len(normalized) <= limit:
            return normalized
        return normalized[: limit - 1].rstrip() + "…"

    def _filter_rows(self, *_args) -> None:
        query = self.search.get_text().strip().lower()
        row = self.list_box.get_first_child()
        while row:
            record = getattr(row, "_record", None)
            visible = not query or (
                record is not None
                and (
                    query in record.display_name.lower()
                    or (record.version or "").lower().find(query) >= 0
                )
            )
            row.set_visible(visible)
            row = row.get_next_sibling()
