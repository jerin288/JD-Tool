"""Bank-template browser for Phase 2."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

import customtkinter as ctk

from app.models.bank_template import BankTemplate
from app.views.theme import button_style, color


class TemplateManagerFrame(ctk.CTkFrame):
    """Browse dynamically loaded templates and apply one to the current PDF."""

    def __init__(
        self,
        master: tk.Misc,
        list_templates: Callable[[], list[BankTemplate]],
        on_use: Callable[[str], None],
    ) -> None:
        super().__init__(master, fg_color="transparent")
        self.list_templates = list_templates
        self.on_use = on_use
        self.templates: dict[str, BankTemplate] = {}
        ctk.CTkLabel(self, text="Bank Templates", font=ctk.CTkFont(size=29, weight="bold")).pack(anchor="w")
        ctk.CTkLabel(
            self,
            text=(
                "Templates are JSON files loaded from config/bank_templates. "
                "Saved mappings work without source-code changes."
            ),
            text_color=color("text_muted"),
        ).pack(anchor="w", pady=(5, 18))
        body = ctk.CTkFrame(self, fg_color=color("surface"), border_width=1, border_color=color("separator"))
        body.pack(fill="both", expand=True)
        left = ctk.CTkFrame(body, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True, padx=12, pady=12)
        self.tree = ttk.Treeview(left, columns=("bank", "source"), show="headings", selectmode="browse")
        self.tree.heading("bank", text="Bank")
        self.tree.heading("source", text="Template file")
        self.tree.column("bank", width=260)
        self.tree.column("source", width=260)
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._show_details)
        right = ctk.CTkFrame(
            body, width=390, fg_color=color("surface_secondary"), border_width=1, border_color=color("separator")
        )
        right.pack(side="right", fill="y", padx=(0, 12), pady=12)
        right.pack_propagate(False)
        self.title = ctk.CTkLabel(
            right, text="Select a template", font=ctk.CTkFont(size=18, weight="bold"), wraplength=350
        )
        self.title.pack(anchor="w", padx=18, pady=(18, 8))
        self.details = ctk.CTkTextbox(right, width=350, height=430)
        self.details.pack(fill="both", expand=True, padx=18, pady=8)
        self.details.configure(state="disabled")
        ctk.CTkButton(right, text="Use for Current PDF", command=self._use_selected, **button_style("primary")).pack(
            fill="x", padx=18, pady=(8, 18)
        )
        self.refresh()

    def refresh(self) -> None:
        templates = self.list_templates()
        self.templates = {item.template_id: item for item in templates}
        self.tree.delete(*self.tree.get_children())
        for item in templates:
            source = item.source_path.replace("\\", "/").rsplit("/", 1)[-1]
            self.tree.insert("", "end", iid=item.template_id, values=(item.bank_name, source))

    def _show_details(self, _event: tk.Event | None = None) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        template = self.templates[selected[0]]
        mapped = [
            name.replace("_", " ").title()
            for name in template.mapping.COLUMN_FIELDS
            if getattr(template.mapping, name) is not None
        ]
        text = (
            f"Detection keywords\n{', '.join(template.detection_keywords) or 'None'}\n\n"
            f"Saved columns\n{', '.join(mapped) or 'Automatic alias detection'}\n\n"
            f"Date format\n{template.mapping.date_format}\n\n"
            f"Multiline narration\n{'Enabled' if template.multiline_enabled else 'Disabled'}\n\n"
            f"Ignored phrases\n" + "\n".join(template.ignore_phrases or ["Default parser rules"])
        )
        self.title.configure(text=template.bank_name)
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")

    def _use_selected(self) -> None:
        selected = self.tree.selection()
        if selected:
            self.on_use(selected[0])
