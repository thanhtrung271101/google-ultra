#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""app.py — 1-Click Desktop GUI for Google AI Pro / Ultra (ultra0.py).

Automatically checks, downloads, and configures missing components on launch:
  - Python >= 3.9
  - frida==16.5.9 (required for Java bridge)
  - Android platform-tools (adb.exe) if missing
  - Auto-connects to emulator (MuMu / Nox / MEmu) via ADB and enables MuMu ROOT via MuMuManager
"""
from __future__ import annotations

import importlib.metadata
import os
import platform
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
import urllib.request
import webbrowser
import zipfile
if os.name == "nt":
    import winreg

BASE = Path(__file__).resolve().parent
REPORT_DIR = BASE / "ultra0-report"
PLATFORM_TOOLS_URL = "https://dl.google.com/android/repository/platform-tools-latest-windows.zip"
MUMU_DOWNLOAD_PAGE = "https://www.mumuplayer.com/"
EMULATOR_PORTS = ("16384", "7555", "16416", "21503", "62001")

ADB_CANDIDATES = [
    os.environ.get("ADB_PATH", ""),
    str(BASE / "platform-tools" / "adb.exe"),
    r"D:\MuMuPlayerGlobal\nx_device\12.0\shell\adb.exe",
    r"D:\MuMuPlayerGlobal\nx_main\adb.exe",
    r"C:\MuMuPlayerGlobal\nx_device\12.0\shell\adb.exe",
    r"C:\Program Files\Netease\MuMuPlayer-12.0\shell\adb.exe",
    r"C:\Program Files\Netease\MuMuPlayer\nx_main\adb.exe",
    r"C:\Program Files\Netease\MuMuPlayer\nx_device\12.0\shell\adb.exe",
    r"C:\Program Files\Netease\MuMuPlayer\nx_device\15.0\shell\adb.exe",
    r"C:\Program Files\Netease\MuMuPlayerGlobal-12.0\shell\adb.exe",
    r"C:\Program Files\Netease\MuMu\emulator\nemu\vmonitor\bin\adb_server.exe",
    r"C:\Program Files\Netease\MuMu\nx_main\adb.exe",
    r"C:\Program Files (x86)\Netease\MuMuPlayer-12.0\shell\adb.exe",
    r"D:\Program Files\Netease\MuMu\nx_main\adb.exe",
    r"D:\Program Files\Netease\MuMu\nx_device\12.0\shell\adb.exe",
    os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe"),
    os.path.expandvars(r"%USERPROFILE%\AppData\Local\Android\Sdk\platform-tools\adb.exe"),
]

# Modern Dark Mode color palette
BG_ROOT = "#0f172a"
BG_CARD = "#1e293b"
BG_INPUT = "#0b1220"
BG_HOVER = "#334155"
FG_TEXT = "#f1f5f9"
FG_MUTED = "#94a3b8"
ACCENT = "#38bdf8"
SUCCESS = "#22c55e"
WARNING = "#f59e0b"
DANGER = "#ef4444"
BORDER = "#334155"


def find_existing_adb() -> str | None:
    for c in ADB_CANDIDATES:
        if c and Path(c).exists():
            return c
    return shutil.which("adb")


def get_frida_version() -> str | None:
    try:
        return importlib.metadata.version("frida")
    except importlib.metadata.PackageNotFoundError:
        return None


def find_mumu_exe() -> str | None:
    rel_paths = [
        r"MuMuPlayerGlobal\nx_main\MuMuNxMain.exe",
        r"MuMuPlayerGlobal\nx_device\12.0\shell\MuMuPlayer.exe",
        r"Program Files\Netease\MuMuPlayer-12.0\shell\MuMuPlayer.exe",
        r"Program Files\Netease\MuMuPlayerGlobal-12.0\shell\MuMuPlayer.exe",
        r"Program Files\Netease\MuMu\nx_main\MuMuNxMain.exe",
        r"Program Files\Netease\MuMu\nx_main\MuMuPlayer.exe",
        r"Program Files\Netease\MuMuPlayer\nx_main\MuMuPlayer.exe",
        r"Program Files (x86)\Netease\MuMuPlayer-12.0\shell\MuMuPlayer.exe",
    ]
    for drive in ("C:\\", "D:\\", "E:\\"):
        for rel in rel_paths:
            p = Path(drive) / rel
            if p.exists():
                return str(p)
    if os.name == "nt":
        roots = [
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
            (winreg.HKEY_CURRENT_USER, r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
        ]
        for hkey, sub in roots:
            try:
                with winreg.OpenKey(hkey, sub) as k:
                    for i in range(winreg.QueryInfoKey(k)[0]):
                        try:
                            name = winreg.EnumKey(k, i)
                            with winreg.OpenKey(k, name) as sk:
                                disp = winreg.QueryValueEx(sk, "DisplayName")[0]
                                if "mumu" in str(disp).lower():
                                    for val_name in ("DisplayIcon", "InstallLocation"):
                                        try:
                                            val = str(winreg.QueryValueEx(sk, val_name)[0]).strip('"').split(",")[0]
                                            p = Path(val)
                                            if p.is_file() and p.suffix.lower() == ".exe":
                                                return str(p)
                                            if p.is_dir():
                                                for exe in ("MuMuPlayer.exe", "MuMuNxMain.exe", "shell\\MuMuPlayer.exe", "nx_main\\MuMuNxMain.exe"):
                                                    cand = p / exe
                                                    if cand.exists():
                                                        return str(cand)
                                        except OSError:
                                            pass
                        except OSError:
                            pass
            except OSError:
                pass
    return None


def is_mumu_running() -> bool:
    if os.name != "nt":
        return False
    try:
        out = subprocess.run(
            ["tasklist"], capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        ).stdout.lower()
        return any(x in out for x in ("mumuplayer.exe", "mumunxmain.exe", "mumuvmmheadless.exe", "nemuplayer.exe"))
    except Exception:
        return False


def find_mumu_manager(mumu_exe: str) -> str | None:
    p = Path(mumu_exe)
    for cand in (p.parent / "MuMuManager.exe", p.parent.parent / "nx_main" / "MuMuManager.exe", p.parent.parent / "shell" / "MuMuManager.exe"):
        if cand.exists():
            return str(cand)
    return None


class UltraDesktopApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Google AI Pro / Ultra — 1-Click Desktop")
        self.geometry("1080x780")
        self.minsize(940, 680)
        self.configure(bg=BG_ROOT)

        self.adb_path: str | None = None
        self.active_proc: subprocess.Popen | None = None
        self.is_busy = False
        self.log_queue: queue.Queue[tuple[str, str]] = queue.Queue()

        self._configure_styles()
        self._build_ui()

        self.after(100, self._poll_queue)
        self.after(200, self.start_auto_setup)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _configure_styles(self) -> None:
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(".", background=BG_CARD, foreground=FG_TEXT, font=("Segoe UI", 9))
        style.configure("TFrame", background=BG_ROOT)
        style.configure("Card.TFrame", background=BG_CARD)
        style.configure("TLabel", background=BG_CARD, foreground=FG_TEXT, font=("Segoe UI", 9))
        style.configure("Muted.TLabel", background=BG_CARD, foreground=FG_MUTED, font=("Segoe UI", 8))
        style.configure("Header.TLabel", background=BG_ROOT, foreground=FG_TEXT, font=("Segoe UI", 14, "bold"))
        style.configure("SubHeader.TLabel", background=BG_ROOT, foreground=FG_MUTED, font=("Segoe UI", 9))
        style.configure("CardTitle.TLabel", background=BG_CARD, foreground=ACCENT, font=("Segoe UI", 10, "bold"))
        style.configure("TNotebook", background=BG_ROOT, borderwidth=0)
        style.configure("TNotebook.Tab", background=BG_CARD, foreground=FG_MUTED, padding=(14, 7), font=("Segoe UI", 9, "bold"))
        style.map("TNotebook.Tab", background=[("selected", BG_HOVER)], foreground=[("selected", FG_TEXT)])
        style.configure("TCheckbutton", background=BG_CARD, foreground=FG_TEXT)
        style.map("TCheckbutton", background=[("active", BG_CARD)])
        style.configure("TRadiobutton", background=BG_CARD, foreground=FG_TEXT)
        style.map("TRadiobutton", background=[("active", BG_CARD)])
        style.configure("TCombobox", fieldbackground=BG_INPUT, background=BG_HOVER, foreground=FG_TEXT, arrowcolor=FG_TEXT)
        style.configure("Horizontal.TProgressbar", troughcolor=BG_INPUT, background=ACCENT, borderwidth=0, thickness=6)

    def _make_btn(self, parent, text: str, command, bg: str = BG_HOVER, fg: str = FG_TEXT, width: int | None = None):
        btn = tk.Button(
            parent,
            text=text,
            command=command,
            bg=bg,
            fg=fg,
            activebackground=ACCENT,
            activeforeground="#0f172a",
            relief="flat",
            bd=0,
            padx=12,
            pady=7,
            cursor="hand2",
            font=("Segoe UI", 9, "bold"),
        )
        if width:
            btn.configure(width=width)
        return btn

    def _build_ui(self) -> None:
        header = tk.Frame(self, bg=BG_ROOT, padx=16, pady=12)
        header.pack(fill="x")

        title_box = tk.Frame(header, bg=BG_ROOT)
        title_box.pack(side="left", fill="x", expand=True)
        ttk.Label(title_box, text="Google AI Pro / Ultra — 1-Click Desktop", style="Header.TLabel").pack(anchor="w")
        ttk.Label(
            title_box,
            text="Auto-checks environment (Frida 16.5.9, ADB, MuMu ROOT) + Full Auto-Checkout & Subscription Stacking (up to 30 months)",
            style="SubHeader.TLabel",
        ).pack(anchor="w")

        self.lbl_global_status = tk.Label(
            header,
            text="⏳ Initializing...",
            bg=BG_CARD,
            fg=WARNING,
            padx=12,
            pady=6,
            font=("Segoe UI", 9, "bold"),
        )
        self.lbl_global_status.pack(side="right")

        env_card = tk.Frame(self, bg=BG_CARD, padx=14, pady=10, highlightbackground=BORDER, highlightthickness=1)
        env_card.pack(fill="x", padx=16, pady=(0, 10))

        badges_row = tk.Frame(env_card, bg=BG_CARD)
        badges_row.pack(fill="x")

        self.badge_python = self._create_badge(badges_row, "Python", "Checking...")
        self.badge_frida = self._create_badge(badges_row, "Frida 16.5.9", "Checking...")
        self.badge_adb = self._create_badge(badges_row, "ADB", "Checking...")
        self.badge_mumu = self._create_badge(badges_row, "MuMu Player", "Checking...")
        self.badge_device = self._create_badge(badges_row, "Device", "Not scanned")

        controls_row = tk.Frame(env_card, bg=BG_CARD, pady=8)
        controls_row.pack(fill="x")

        ttk.Label(controls_row, text="Device (--serial):", style="TLabel").pack(side="left", padx=(0, 6))
        self.var_serial = tk.StringVar(value="")
        self.cmb_devices = ttk.Combobox(controls_row, textvariable=self.var_serial, width=22, state="readonly")
        self.cmb_devices.pack(side="left", padx=(0, 8))

        self.btn_refresh_dev = self._make_btn(controls_row, "🔄 Scan Devices", self.refresh_devices_async)
        self.btn_refresh_dev.pack(side="left", padx=4)

        self.btn_mumu = self._make_btn(controls_row, "🌐 Open / Install MuMu", self.launch_or_install_mumu_async, bg="#7c3aed")
        self.btn_mumu.pack(side="left", padx=4)

        self.btn_setup_env = self._make_btn(controls_row, "⚙ Auto-Setup Environment", self.start_auto_setup, bg="#0284c7")
        self.btn_setup_env.pack(side="left", padx=4)

        self.btn_deep_check = self._make_btn(controls_row, "✅ Deep Check (--check)", self.run_deep_check, bg="#15803d")
        self.btn_deep_check.pack(side="left", padx=4)

        self.progress = ttk.Progressbar(env_card, mode="determinate", maximum=100, value=0)
        self.progress.pack(fill="x", pady=(4, 0))

        nb = ttk.Notebook(self)
        nb.pack(fill="x", padx=16, pady=(0, 10))

        tab_presets = tk.Frame(nb, bg=BG_ROOT, pady=6)
        tab_custom = tk.Frame(nb, bg=BG_CARD, padx=14, pady=12)
        nb.add(tab_presets, text="  ⚡ 1-Click Quick Actions  ")
        nb.add(tab_custom, text="  🛠 Custom / Batch Mode  ")

        self._build_presets_tab(tab_presets)
        self._build_custom_tab(tab_custom)

        log_card = tk.Frame(self, bg=BG_CARD, padx=12, pady=10, highlightbackground=BORDER, highlightthickness=1)
        log_card.pack(fill="both", expand=True, padx=16, pady=(0, 14))

        log_bar = tk.Frame(log_card, bg=BG_CARD)
        log_bar.pack(fill="x", pady=(0, 6))
        ttk.Label(log_bar, text="Live Console Output", style="CardTitle.TLabel").pack(side="left")

        self.btn_open_report = self._make_btn(log_bar, "📂 Open Reports", self.open_reports_dir)
        self.btn_open_report.pack(side="right", padx=4)

        self.btn_clear_log = self._make_btn(log_bar, "🗑 Clear Log", self.clear_log)
        self.btn_clear_log.pack(side="right", padx=4)

        self.btn_continue = self._make_btn(
            log_bar, "▶ Done, Continue (Enter)", self.send_continue, bg=WARNING, fg="#0f172a"
        )
        self.btn_continue.pack(side="right", padx=4)
        self.btn_continue.configure(state="disabled")

        self.btn_stop = self._make_btn(log_bar, "⏹ Stop", self.stop_running_process, bg=DANGER)
        self.btn_stop.pack(side="right", padx=4)
        self.btn_stop.configure(state="disabled")

        txt_wrap = tk.Frame(log_card, bg=BG_INPUT)
        txt_wrap.pack(fill="both", expand=True)

        self.txt_log = tk.Text(
            txt_wrap,
            bg=BG_INPUT,
            fg=FG_TEXT,
            insertbackground=FG_TEXT,
            font=("Consolas", 9),
            relief="flat",
            wrap="word",
            state="disabled",
            padx=8,
            pady=8,
        )
        scroll = ttk.Scrollbar(txt_wrap, orient="vertical", command=self.txt_log.yview)
        self.txt_log.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        self.txt_log.pack(side="left", fill="both", expand=True)

        self.txt_log.tag_configure("ok", foreground=SUCCESS)
        self.txt_log.tag_configure("warn", foreground=WARNING)
        self.txt_log.tag_configure("err", foreground=DANGER)
        self.txt_log.tag_configure("info", foreground=ACCENT)
        self.txt_log.tag_configure("muted", foreground=FG_MUTED)

    def _create_badge(self, parent, title: str, initial: str) -> tk.Label:
        box = tk.Frame(parent, bg=BG_INPUT, padx=10, pady=6, highlightbackground=BORDER, highlightthickness=1)
        box.pack(side="left", fill="x", expand=True, padx=4)
        tk.Label(box, text=title, bg=BG_INPUT, fg=FG_MUTED, font=("Segoe UI", 8)).pack(anchor="w")
        lbl = tk.Label(box, text=initial, bg=BG_INPUT, fg=WARNING, font=("Segoe UI", 9, "bold"))
        lbl.pack(anchor="w")
        return lbl

    def _set_badge(self, lbl: tk.Label, text: str, color: str) -> None:
        lbl.configure(text=text, fg=color)

    def _build_presets_tab(self, parent) -> None:
        pw_bar = tk.Frame(parent, bg=BG_CARD, padx=12, pady=8, highlightbackground=BORDER, highlightthickness=1)
        pw_bar.pack(fill="x", pady=(0, 8))
        ttk.Label(pw_bar, text="Account Password (optional, auto-fills Play Store checkout verification):", style="TLabel").pack(side="left", padx=(0, 8))
        self.var_quick_pw = tk.StringVar(value="")
        tk.Entry(pw_bar, textvariable=self.var_quick_pw, show="*", bg=BG_INPUT, fg=FG_TEXT, insertbackground=FG_TEXT, relief="flat", width=28).pack(side="left", ipady=4)

        cols = tk.Frame(parent, bg=BG_ROOT)
        cols.pack(fill="x")

        col_pro = tk.Frame(cols, bg=BG_CARD, padx=12, pady=10, highlightbackground=BORDER, highlightthickness=1)
        col_pro.pack(side="left", fill="both", expand=True, padx=(0, 6))

        ttk.Label(col_pro, text="Google AI Pro (5TB) — Free Trial & Stacking (up to 30 Months)", style="CardTitle.TLabel").pack(anchor="w", pady=(0, 6))
        ttk.Label(
            col_pro,
            text="Uses current device account. Auto-taps Subscribe 2x, enters password, and stacks remaining trial days.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(0, 8))

        grid_pro = tk.Frame(col_pro, bg=BG_CARD)
        grid_pro.pack(fill="x")

        pro_buttons = [
            ("1. Scan All Ultra & Pro Offers (No Purchase)", "#334155", ["--test-plans"]),
            ("2. Pro 12-Month Free (Step 1 / Auto Fallback)", "#0284c7", ["--no-add", "--force", "--plan", "pro"]),
            ("3. Stack +6 Months (Step 2 -> 18m)", "#0369a1", ["--no-add", "--force", "--stack", "--plan", "pro6"]),
            ("4. Stack +6 Months (Step 3 -> 24m)", "#0369a1", ["--no-add", "--force", "--stack", "--plan", "pro6b"]),
            ("5. Stack +6 Months Backup (Step 4 -> 30m)", "#1d4ed8", ["--no-add", "--force", "--stack", "--plan", "pro6c"]),
            ("6. Pro 3-Month Standalone (eft-3mo)", "#475569", ["--no-add", "--force", "--plan", "pro3"]),
        ]
        for idx, (label, color, args) in enumerate(pro_buttons):
            r, col_idx = divmod(idx, 2)
            b = self._make_btn(grid_pro, label, lambda a=args, t=label: self._run_quick_preset(a, t), bg=color)
            b.grid(row=r, column=col_idx, sticky="ew", padx=4, pady=4)
        grid_pro.columnconfigure(0, weight=1)
        grid_pro.columnconfigure(1, weight=1)

        col_ultra = tk.Frame(cols, bg=BG_CARD, padx=12, pady=10, highlightbackground=BORDER, highlightthickness=1)
        col_ultra.pack(side="left", fill="both", expand=True, padx=(6, 0))

        ttk.Label(col_ultra, text="Google AI Ultra (20TB / 30TB Promo) & SKU Query", style="CardTitle.TLabel").pack(anchor="w", pady=(0, 6))
        ttk.Label(
            col_ultra,
            text="Promotional Ultra plans are paid intro offers ($24.99 / $19.99). Script opens the billing sheet for review.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(0, 8))

        self._make_btn(
            col_ultra,
            "Ultra 20TB — 3 Months @ $24.99/mo (75% Off Promo)",
            lambda: self._run_quick_preset(
                ["--no-add", "--force", "--allow-paid", "--sku", "g1.20tb.3months_ip_75p.acq"],
                "Ultra 20TB 3-Month $24.99 Promo",
            ),
            bg="#7c3aed",
        ).pack(fill="x", pady=4)

        self._make_btn(
            col_ultra,
            "Ultra 30TB — 3 Months @ $19.99/mo (90% Off Promo)",
            lambda: self._run_quick_preset(
                ["--no-add", "--force", "--allow-paid", "--sku", "g1.ai.ultra.3months_ip_90p.acq"],
                "Ultra 30TB 3-Month $19.99 Promo",
            ),
            bg="#6d28d9",
        ).pack(fill="x", pady=4)

        sku_row = tk.Frame(col_ultra, bg=BG_CARD, pady=6)
        sku_row.pack(fill="x")
        ttk.Label(sku_row, text="Query SKU:", style="TLabel").pack(side="left", padx=(0, 6))
        self.var_query_sku = tk.StringVar(value="g1.2tb.ai.subs_variant")
        ent_sku = tk.Entry(sku_row, textvariable=self.var_query_sku, bg=BG_INPUT, fg=FG_TEXT, insertbackground=FG_TEXT, relief="flat")
        ent_sku.pack(side="left", fill="x", expand=True, ipady=5, padx=(0, 6))
        self._make_btn(sku_row, "🔍 Query SKU", self.run_query_sku, bg="#0f766e").pack(side="left")

    def _run_quick_preset(self, base_args: list[str], title: str) -> None:
        if "--test-plans" in base_args:
            self.run_ultra(base_args, title)
            return
        pw = self.var_quick_pw.get().strip()
        acc = f"current@device:{pw}:" if pw else "current@device"
        self.run_ultra(["--account", acc] + base_args, title)

    def _build_custom_tab(self, parent) -> None:
        self.var_acc_mode = tk.StringVar(value="current")

        mode_row = tk.Frame(parent, bg=BG_CARD)
        mode_row.pack(fill="x", pady=(0, 8))
        ttk.Radiobutton(mode_row, text="Current Device Account (current@device)", variable=self.var_acc_mode, value="current").pack(side="left", padx=(0, 14))
        ttk.Radiobutton(mode_row, text="Single Account", variable=self.var_acc_mode, value="single").pack(side="left", padx=(0, 14))
        ttk.Radiobutton(mode_row, text="Accounts File (.txt)", variable=self.var_acc_mode, value="file").pack(side="left")

        inputs = tk.Frame(parent, bg=BG_CARD)
        inputs.pack(fill="x", pady=(0, 8))

        ttk.Label(inputs, text="Email:").grid(row=0, column=0, sticky="w", padx=4, pady=3)
        self.var_email = tk.StringVar()
        tk.Entry(inputs, textvariable=self.var_email, bg=BG_INPUT, fg=FG_TEXT, insertbackground=FG_TEXT, relief="flat", width=28).grid(row=0, column=1, sticky="ew", padx=4, pady=3, ipady=4)

        ttk.Label(inputs, text="Password:").grid(row=0, column=2, sticky="w", padx=4, pady=3)
        self.var_pw = tk.StringVar()
        tk.Entry(inputs, textvariable=self.var_pw, show="*", bg=BG_INPUT, fg=FG_TEXT, insertbackground=FG_TEXT, relief="flat", width=20).grid(row=0, column=3, sticky="ew", padx=4, pady=3, ipady=4)

        ttk.Label(inputs, text="2FA Secret (optional):").grid(row=0, column=4, sticky="w", padx=4, pady=3)
        self.var_totp = tk.StringVar()
        tk.Entry(inputs, textvariable=self.var_totp, bg=BG_INPUT, fg=FG_TEXT, insertbackground=FG_TEXT, relief="flat", width=18).grid(row=0, column=5, sticky="ew", padx=4, pady=3, ipady=4)

        ttk.Label(inputs, text="Accounts File:").grid(row=1, column=0, sticky="w", padx=4, pady=3)
        self.var_acc_file = tk.StringVar()
        tk.Entry(inputs, textvariable=self.var_acc_file, bg=BG_INPUT, fg=FG_TEXT, insertbackground=FG_TEXT, relief="flat").grid(row=1, column=1, columnspan=4, sticky="ew", padx=4, pady=3, ipady=4)
        self._make_btn(inputs, "Browse...", self.browse_accounts_file).grid(row=1, column=5, sticky="ew", padx=4, pady=3)
        inputs.columnconfigure(1, weight=1)

        opts = tk.Frame(parent, bg=BG_CARD)
        opts.pack(fill="x", pady=(4, 8))

        ttk.Label(opts, text="Plan:").pack(side="left", padx=(0, 6))
        self.var_plan = tk.StringVar(value="auto")
        ttk.Combobox(
            opts,
            textvariable=self.var_plan,
            values=["auto", "pro", "pro12", "pro6", "pro6b", "pro6c", "pro3", "5x", "20x", "ultra", "all"],
            width=10,
            state="readonly",
        ).pack(side="left", padx=(0, 14))

        ttk.Label(opts, text="SKU (optional):").pack(side="left", padx=(0, 6))
        self.var_custom_sku = tk.StringVar()
        tk.Entry(opts, textvariable=self.var_custom_sku, bg=BG_INPUT, fg=FG_TEXT, insertbackground=FG_TEXT, relief="flat", width=26).pack(side="left", padx=(0, 14), ipady=4)

        self.var_no_add = tk.BooleanVar(value=True)
        self.var_no_switch = tk.BooleanVar(value=False)
        self.var_force = tk.BooleanVar(value=True)
        self.var_stack = tk.BooleanVar(value=False)
        self.var_allow_paid = tk.BooleanVar(value=False)
        self.var_list_only = tk.BooleanVar(value=False)

        for text, var in [
            ("--no-add", self.var_no_add),
            ("--no-switch", self.var_no_switch),
            ("--force", self.var_force),
            ("--stack", self.var_stack),
            ("--allow-paid", self.var_allow_paid),
            ("--list", self.var_list_only),
        ]:
            ttk.Checkbutton(opts, text=text, variable=var).pack(side="left", padx=6)

        self._make_btn(parent, "▶ Run Custom Configuration", self.run_custom, bg="#0284c7").pack(anchor="w", pady=(4, 0))

    # ---- Logging & Queue ----
    def log(self, msg: str, tag: str = "") -> None:
        self.log_queue.put(("log", f"{msg}\n|{tag}"))

    def _poll_queue(self) -> None:
        try:
            while True:
                kind, payload = self.log_queue.get_nowait()
                if kind == "log":
                    text, tag = payload.rsplit("|", 1)
                    self.txt_log.configure(state="normal")
                    self.txt_log.insert("end", text, (tag,) if tag else ())
                    self.txt_log.see("end")
                    self.txt_log.configure(state="disabled")
                    if "Action required:" in text or "Press [Enter]" in text:
                        self.btn_continue.configure(state="normal")
                elif kind == "ui":
                    payload()
        except queue.Empty:
            pass
        self.after(80, self._poll_queue)

    def _ui(self, fn) -> None:
        self.log_queue.put(("ui", fn))

    def _detect_tag(self, line: str) -> str:
        low = line.lower()
        if "❌" in line or "error" in low or "failed" in low or "traceback" in low:
            return "err"
        if "⚠️" in line or "⏸" in line or "warn" in low:
            return "warn"
        if "✅" in line or "success" in low or "ready" in low:
            return "ok"
        if line.startswith("▶") or line.startswith("==="):
            return "info"
        return ""

    # ---- Auto-Setup & Environment ----
    def start_auto_setup(self) -> None:
        if self.is_busy:
            messagebox.showinfo("Busy", "A task is currently running. Please wait or click Stop.")
            return
        self.is_busy = True
        self._set_global_status("⏳ Checking & setting up environment...", WARNING)
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        threading.Thread(target=self._auto_setup_worker, daemon=True).start()

    def _auto_setup_worker(self) -> None:
        try:
            self.log("============================================================", "info")
            self.log("▶ Checking & automatically configuring environment...", "info")

            v = sys.version_info
            py_str = f"Python {platform.python_version()}"
            if v < (3, 9):
                self._ui(lambda: self._set_badge(self.badge_python, f"{py_str} (Too old)", DANGER))
                self.log(f"❌ {py_str} < 3.9. Please install Python 3.10+ from python.org.", "err")
                return
            self._ui(lambda: self._set_badge(self.badge_python, f"✅ {py_str}", SUCCESS))
            self.log(f"   ✅ {py_str} ({platform.architecture()[0]})", "ok")

            frida_ver = get_frida_version()
            if frida_ver and frida_ver.startswith("16."):
                self._ui(lambda: self._set_badge(self.badge_frida, f"✅ frida {frida_ver}", SUCCESS))
                self.log(f"   ✅ frida {frida_ver} installed", "ok")
            else:
                msg = f"Installing frida 16.5.9 (current: {frida_ver or 'not installed'})..."
                self._ui(lambda: self._set_badge(self.badge_frida, "⏳ Installing...", WARNING))
                self.log(f"▶ {msg}", "info")
                installed = self._install_frida_16()
                if installed:
                    ver_now = get_frida_version() or "16.5.9"
                    self._ui(lambda: self._set_badge(self.badge_frida, f"✅ frida {ver_now}", SUCCESS))
                    self.log(f"   ✅ Installed frida {ver_now}", "ok")
                else:
                    self._ui(lambda: self._set_badge(self.badge_frida, "❌ Install failed", DANGER))
                    self.log("   ❌ Failed to install frida==16.5.9. Check network and retry.", "err")

            adb = find_existing_adb()
            if adb:
                self.adb_path = adb
                self._ui(lambda: self._set_badge(self.badge_adb, "✅ Ready", SUCCESS))
                self.log(f"   ✅ ADB: {adb}", "ok")
            else:
                self._ui(lambda: self._set_badge(self.badge_adb, "⏳ Downloading...", WARNING))
                self.log("▶ ADB not found — downloading Android platform-tools automatically...", "info")
                adb = self._download_platform_tools()
                if adb:
                    self.adb_path = adb
                    self._ui(lambda: self._set_badge(self.badge_adb, "✅ Downloaded", SUCCESS))
                    self.log(f"   ✅ Downloaded & extracted ADB: {adb}", "ok")
                else:
                    self._ui(lambda: self._set_badge(self.badge_adb, "❌ Missing ADB", DANGER))

            mumu_exe = find_mumu_exe()
            if mumu_exe:
                if is_mumu_running():
                    self._ui(lambda: self._set_badge(self.badge_mumu, "✅ Running", SUCCESS))
                    self.log(f"   ✅ MuMu Player is running ({mumu_exe})", "ok")
                else:
                    self._ui(lambda: self._set_badge(self.badge_mumu, "⏳ Starting MuMu...", WARNING))
                    self.log(f"▶ Found MuMu ({mumu_exe}), starting automatically...", "info")
                    self._start_mumu(mumu_exe)
                    time.sleep(6)
                    if is_mumu_running():
                        self._ui(lambda: self._set_badge(self.badge_mumu, "✅ Running", SUCCESS))
                    else:
                        self._ui(lambda: self._set_badge(self.badge_mumu, "⚠ Installed (Stopped)", WARNING))
            else:
                self._ui(lambda: self._set_badge(self.badge_mumu, "⚠ Not Installed", WARNING))
                self.log("   ⚠ MuMu Player not found. Click '🌐 Open / Install MuMu' to download from mumuplayer.com.", "warn")

            if self.adb_path:
                self._scan_devices()

            self.log("▶ Environment check finished!", "ok")
        finally:
            self.is_busy = False
            self._ui(self._finish_setup_ui)

    def _finish_setup_ui(self) -> None:
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0)
        frida_ok = bool(get_frida_version() and get_frida_version().startswith("16."))
        has_dev = bool(self.var_serial.get())
        if frida_ok and self.adb_path and has_dev:
            self._set_global_status("✅ Environment & Device Ready", SUCCESS)
        elif frida_ok and self.adb_path:
            self._set_global_status("⚠️ Tools ready — waiting for MuMu / device connection", WARNING)
        else:
            self._set_global_status("⚠️ Environment needs attention", WARNING)

    def _configure_mumu_root(self, mumu_exe: str) -> None:
        mgr = find_mumu_manager(mumu_exe)
        if not mgr:
            return
        try:
            subprocess.run(
                [mgr, "setting", "-v", "0", "-k", "root_permission", "-val", "true"],
                capture_output=True, timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            self.log("   ✅ Enabled ROOT permission in MuMu automatically via MuMuManager.", "ok")
        except Exception:
            pass

    def _start_mumu(self, mumu_exe: str) -> None:
        try:
            self._configure_mumu_root(mumu_exe)
            subprocess.Popen([mumu_exe], cwd=str(Path(mumu_exe).parent))
            self.log("   ▶ Sent start command to MuMu Player.", "info")
        except Exception as e:
            self.log(f"   ❌ Failed to start MuMu: {e}", "err")

    def launch_or_install_mumu_async(self) -> None:
        def _worker():
            mumu_exe = find_mumu_exe()
            if mumu_exe:
                if is_mumu_running():
                    self.log(f"✅ MuMu Player is running ({mumu_exe}). Rescanning ADB...", "ok")
                    self._ui(lambda: self._set_badge(self.badge_mumu, "✅ Running", SUCCESS))
                else:
                    self.log(f"▶ Starting MuMu Player ({mumu_exe})...", "info")
                    self._start_mumu(mumu_exe)
                    time.sleep(6)
                if not self.adb_path:
                    self.adb_path = find_existing_adb()
                if self.adb_path:
                    self._scan_devices()
            else:
                self.log(f"▶ Opening official MuMu download page: {MUMU_DOWNLOAD_PAGE}", "info")
                webbrowser.open(MUMU_DOWNLOAD_PAGE)
                self._ui(lambda: self._set_badge(self.badge_mumu, "⚠ Not Installed", WARNING))
                self.log("   👉 After installing MuMu, enable [ROOT] & [ADB Debugging] in MuMu Settings, then click '🔄 Scan Devices'.", "warn")

        threading.Thread(target=_worker, daemon=True).start()

    def _install_frida_16(self) -> bool:
        cmds = [
            [sys.executable, "-m", "pip", "install", "--no-cache-dir", "frida==16.5.9"],
            [sys.executable, "-m", "pip", "install", "--no-cache-dir", "-i", "https://pypi.tuna.tsinghua.edu.cn/simple", "frida==16.5.9"],
        ]
        for cmd in cmds:
            self.log("   $ " + " ".join(cmd[2:]), "muted")
            p = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="ignore",
            )
            assert p.stdout is not None
            for line in p.stdout:
                s = line.rstrip()
                if s:
                    self.log("   " + s, "muted")
            if p.wait() == 0:
                importlib.invalidate_caches()
                return True
        return False

    def _download_platform_tools(self) -> str | None:
        dest = BASE / "platform-tools"
        tmp = Path(tempfile.gettempdir()) / "platform-tools.zip"
        try:
            self._ui(lambda: (self.progress.stop(), self.progress.configure(mode="determinate", value=0)))
            with urllib.request.urlopen(PLATFORM_TOOLS_URL, timeout=180) as resp:
                total = int(resp.headers.get("Content-Length") or 0)
                downloaded = 0
                with open(tmp, "wb") as f:
                    while True:
                        chunk = resp.read(1024 * 128)
                        if not chunk:
                            break
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            pct = min(100, int(downloaded * 100 / total))
                            self._ui(lambda v=pct: self.progress.configure(value=v))
            self.log("   Extracting platform-tools...", "info")
            with zipfile.ZipFile(tmp) as z:
                z.extractall(BASE)
            tmp.unlink(missing_ok=True)
            adb = dest / "adb.exe"
            if adb.exists():
                return str(adb)
            self.log("   ❌ Extracted platform-tools but adb.exe was not found", "err")
            return None
        except Exception as e:
            self.log(f"   ❌ Failed to download platform-tools: {e}", "err")
            return None

    def _scan_devices(self) -> None:
        if not self.adb_path:
            return
        self.log("▶ Scanning ADB devices & emulator ports...", "info")
        for port in EMULATOR_PORTS:
            try:
                subprocess.run([self.adb_path, "connect", f"127.0.0.1:{port}"], capture_output=True, timeout=3)
            except Exception:
                pass
        try:
            out = subprocess.run(
                [self.adb_path, "devices"], capture_output=True, text=True, encoding="utf-8", errors="ignore", timeout=10
            ).stdout
        except Exception as e:
            self.log(f"   ❌ Error running adb devices: {e}", "err")
            return

        devices = [line.split("\t")[0].strip() for line in out.splitlines()[1:] if "\tdevice" in line]

        def _update():
            self.cmb_devices["values"] = devices
            if devices:
                if self.var_serial.get() not in devices:
                    self.var_serial.set(devices[0])
                self._set_badge(self.badge_device, f"✅ {len(devices)} device(s) ({devices[0]})", SUCCESS)
            else:
                self.var_serial.set("")
                self._set_badge(self.badge_device, "⚠️ No device found", WARNING)

        self._ui(_update)
        if devices:
            self.log(f"   ✅ Connected: {', '.join(devices)}", "ok")
        else:
            self.log("   ⚠️ No device detected. Start your emulator (MuMu/Nox) or connect a rooted phone with USB Debugging.", "warn")

    def refresh_devices_async(self) -> None:
        if not self.adb_path:
            self.adb_path = find_existing_adb()
        if not self.adb_path:
            messagebox.showwarning("Missing ADB", "ADB not found. Click 'Auto-Setup Environment'.")
            return
        threading.Thread(target=self._scan_devices, daemon=True).start()

    def _build_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        if self.adb_path:
            env["ADB_PATH"] = self.adb_path
            adb_dir = str(Path(self.adb_path).parent)
            env["PATH"] = adb_dir + os.pathsep + env.get("PATH", "")
        return env

    def run_deep_check(self) -> None:
        self.run_ultra(["--check"], "Deep Environment Check (--check)")

    def run_query_sku(self) -> None:
        sku = self.var_query_sku.get().strip() or "g1.2tb.ai.subs_variant"
        self.run_ultra(["--test-plans", "--sku", sku], f"Query SKU: {sku}")

    def run_custom(self) -> None:
        args: list[str] = []
        mode = self.var_acc_mode.get()
        if mode == "current":
            pw = self.var_pw.get().strip() or self.var_quick_pw.get().strip()
            acc = f"current@device:{pw}:" if pw else "current@device"
            args += ["--account", acc]
        elif mode == "single":
            email = self.var_email.get().strip()
            pw = self.var_pw.get().strip()
            totp = self.var_totp.get().strip()
            if not email:
                messagebox.showwarning("Missing Info", "Please enter the account Email.")
                return
            acc = f"{email}:{pw}:{totp}" if totp else f"{email}:{pw}"
            args += ["--account", acc]
        else:
            acc_file = self.var_acc_file.get().strip()
            if not acc_file or not Path(acc_file).exists():
                messagebox.showwarning("Missing File", "Please select a valid accounts file.")
                return
            args.append(acc_file)

        if self.var_no_add.get():
            args.append("--no-add")
        if self.var_no_switch.get():
            args.append("--no-switch")
        if self.var_force.get():
            args.append("--force")
        if self.var_stack.get():
            args.append("--stack")
        if self.var_allow_paid.get():
            args.append("--allow-paid")
        if self.var_list_only.get():
            args.append("--list")

        plan = self.var_plan.get().strip()
        if plan:
            args += ["--plan", plan]
        sku = self.var_custom_sku.get().strip()
        if sku:
            args += ["--sku", sku]

        self.run_ultra(args, "Custom Execution")

    def run_ultra(self, args: list[str], title: str) -> None:
        full_args = list(args)
        serial = self.var_serial.get().strip()
        if serial and "--serial" not in full_args and "--check" not in full_args:
            full_args += ["--serial", serial]
        self._launch_script("ultra0.py", full_args, title)

    def _launch_script(self, script_name: str, args: list[str], title: str) -> None:
        if self.is_busy or self.active_proc is not None:
            messagebox.showinfo("Running", "Another process is currently running. Please wait or click Stop.")
            return
        if not get_frida_version():
            messagebox.showwarning("Missing Frida", "frida 16.5.9 is not installed. Starting auto-setup...")
            self.start_auto_setup()
            return

        self.is_busy = True
        self._set_global_status(f"▶ Running: {title}", ACCENT)
        self.btn_stop.configure(state="normal")
        self.btn_continue.configure(state="disabled")
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)

        cmd = [sys.executable, "-u", str(BASE / script_name)] + args
        self.log(f"\n==================== {title} ====================", "info")
        self.log("   $ " + " ".join(cmd), "muted")

        def _worker():
            code = -1
            try:
                creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
                self.active_proc = subprocess.Popen(
                    cmd,
                    cwd=str(BASE),
                    env=self._build_env(),
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                    creationflags=creationflags,
                )
                assert self.active_proc.stdout is not None
                for line in self.active_proc.stdout:
                    s = line.rstrip("\r\n")
                    self.log(s, self._detect_tag(s))
                code = self.active_proc.wait()
            except Exception as e:
                self.log(f"❌ Execution error: {e}", "err")
            finally:
                self.active_proc = None
                self.is_busy = False

                def _done():
                    self.progress.stop()
                    self.progress.configure(mode="determinate", value=0)
                    self.btn_stop.configure(state="disabled")
                    self.btn_continue.configure(state="disabled")
                    if code == 0:
                        self._set_global_status(f"✅ Done: {title}", SUCCESS)
                    else:
                        self._set_global_status(f"⚠️ Exited (code {code}): {title}", WARNING)

                self._ui(_done)
                self.log(f"--- Process finished (exit code: {code}) ---", "info" if code == 0 else "warn")

        threading.Thread(target=_worker, daemon=True).start()

    def send_continue(self) -> None:
        if self.active_proc and self.active_proc.stdin:
            try:
                self.active_proc.stdin.write("\n")
                self.active_proc.stdin.flush()
                self.btn_continue.configure(state="disabled")
                self.log("▶ Sent continue signal...", "info")
            except Exception as e:
                self.log(f"❌ Failed to send continue signal: {e}", "err")

    def stop_running_process(self) -> None:
        if self.active_proc:
            try:
                self.active_proc.terminate()
                self.log("⏹ Requested process termination.", "warn")
            except Exception as e:
                self.log(f"❌ Failed to stop process: {e}", "err")

    def browse_accounts_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Select accounts list file",
            initialdir=str(BASE),
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
        )
        if path:
            self.var_acc_file.set(path)
            self.var_acc_mode.set("file")

    def open_reports_dir(self) -> None:
        REPORT_DIR.mkdir(exist_ok=True)
        if os.name == "nt":
            os.startfile(str(REPORT_DIR))
        else:
            subprocess.Popen(["xdg-open", str(REPORT_DIR)])

    def clear_log(self) -> None:
        self.txt_log.configure(state="normal")
        self.txt_log.delete("1.0", "end")
        self.txt_log.configure(state="disabled")

    def _set_global_status(self, text: str, color: str) -> None:
        self.lbl_global_status.configure(text=text, fg=color)

    def _on_close(self) -> None:
        if self.active_proc:
            if not messagebox.askyesno("Quit", "A process is currently running. Stop and quit?"):
                return
            try:
                self.active_proc.terminate()
            except Exception:
                pass
        self.destroy()


def main() -> None:
    app = UltraDesktopApp()
    app.mainloop()


if __name__ == "__main__":
    main()
