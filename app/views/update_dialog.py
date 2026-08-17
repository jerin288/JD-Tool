"""Non-blocking release notes dialog for optional application updates."""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

import customtkinter as ctk

from app.models.update import UpdateRelease
from app.views.theme import button_style, color


class UpdateDialog(ctk.CTkToplevel):
    def __init__(
        self,
        master: tk.Misc,
        release: UpdateRelease,
        on_download: Callable[[], None],
        on_view_release: Callable[[], None],
    ) -> None:
        super().__init__(master)
        self.title(f"JD Tool v{release.version} is available")
        self.geometry("620x470")
        self.minsize(520, 390)
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        ctk.CTkLabel(
            self,
            text=f"JD Tool v{release.version} is ready to download",
            font=ctk.CTkFont(size=19, weight="bold"),
            anchor="w",
        ).pack(fill="x", padx=20, pady=(20, 6))
        ctk.CTkLabel(
            self,
            text="The update is optional. It will be verified, installed, and then JD Tool will restart.",
            wraplength=570,
            justify="left",
            anchor="w",
            text_color=color("text_secondary"),
        ).pack(fill="x", padx=20, pady=(0, 12))
        ctk.CTkLabel(self, text="Release notes", font=ctk.CTkFont(weight="bold"), anchor="w").pack(
            fill="x", padx=20, pady=(0, 4)
        )
        notes = ctk.CTkTextbox(self, wrap="word")
        notes.pack(fill="both", expand=True, padx=20)
        notes.insert("1.0", release.notes.strip() or "No release notes were provided.")
        notes.configure(state="disabled")

        actions = ctk.CTkFrame(self, fg_color="transparent")
        actions.pack(fill="x", padx=20, pady=18)
        ctk.CTkButton(
            actions,
            text="Download and Restart",
            width=165,
            command=lambda: self._download(on_download),
            **button_style("primary"),
        ).pack(side="right")
        ctk.CTkButton(
            actions,
            text="Later",
            width=85,
            command=self.destroy,
            **button_style("secondary"),
        ).pack(side="right", padx=8)
        ctk.CTkButton(
            actions,
            text="View Release",
            width=110,
            command=on_view_release,
            **button_style("secondary"),
        ).pack(side="left")

        self.after(20, self._center)
        self.grab_set()

    def _download(self, callback: Callable[[], None]) -> None:
        self.grab_release()
        self.destroy()
        callback()

    def _center(self) -> None:
        self.update_idletasks()
        master = self.master
        x = master.winfo_rootx() + max(0, (master.winfo_width() - self.winfo_width()) // 2)
        y = master.winfo_rooty() + max(0, (master.winfo_height() - self.winfo_height()) // 2)
        self.geometry(f"+{x}+{y}")
