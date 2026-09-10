"""Changan Hub — desktop control surface for a Lamore 2023 head unit."""

from __future__ import annotations

import os
import queue
import subprocess
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable

from hub.adb import ENGINEERING_CODE, ENGINEERING_PIN, SHELL_PASSWORD, Adb, AdbError
from hub.catalog import CATALOG, package_from_row, package_label
from hub.installer import PROCESS_STAGES, classify_install_step, install_apk
from hub.journal import Journal
from hub.overlay import install_overlay, overlay_apk, remove_overlay, start_overlay, stop_overlay
from hub.paths import bundled_apps
from hub.signer import certificate_info, ensure_keystore
from hub.usb import list_usb_apks, removable_roots

BG = "#0B1220"
PANEL = "#121A2B"
CARD = "#182235"
ACCENT = "#3DDC97"
TEXT = "#F3F6FB"
MUTED = "#9AA7B8"
DANGER = "#FF6B6B"
FONT = ("Segoe UI", 11)
FONT_TITLE = ("Segoe UI", 20, "bold")
FONT_H = ("Segoe UI", 14, "bold")
FONT_MONO = ("Consolas", 10)


def _bind_theme(root: tk.Tk) -> None:
    root.configure(bg=BG)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    style.configure("TFrame", background=BG)
    style.configure("Card.TFrame", background=CARD)
    style.configure("TLabel", background=BG, foreground=TEXT, font=FONT)
    style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=FONT)
    style.configure("Title.TLabel", background=BG, foreground=ACCENT, font=FONT_TITLE)
    style.configure("H.TLabel", background=BG, foreground=TEXT, font=FONT_H)
    style.configure("Card.TLabel", background=CARD, foreground=TEXT, font=FONT)
    style.configure("CardMuted.TLabel", background=CARD, foreground=MUTED, font=FONT)
    style.configure(
        "Accent.TButton",
        background=ACCENT,
        foreground=BG,
        font=("Segoe UI", 11, "bold"),
        padding=10,
    )
    style.map("Accent.TButton", background=[("active", "#62F0B2")])
    style.configure("TButton", background="#243049", foreground=TEXT, padding=8, font=FONT)
    style.map("TButton", background=[("active", "#31405C")])
    style.configure("Nav.TButton", background=PANEL, foreground=TEXT, padding=12, font=FONT)
    style.map("Nav.TButton", background=[("active", CARD)])
    style.configure("TNotebook", background=BG, borderwidth=0)
    style.configure("TNotebook.Tab", background=PANEL, foreground=TEXT, padding=(16, 8))
    style.map("TNotebook.Tab", background=[("selected", CARD)], foreground=[("selected", ACCENT)])
    style.configure("TEntry", fieldbackground=CARD, foreground=TEXT)
    style.configure("Horizontal.TProgressbar", troughcolor=PANEL, background=ACCENT, thickness=12)


class HubApp:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Changan Hub — Lamore 2023")
        self.root.geometry("1180x760")
        self.root.minsize(960, 640)
        _bind_theme(self.root)

        self.log_q: queue.Queue[str] = queue.Queue()
        self.journal = Journal()
        self.journal.subscribe(self.log_q.put)
        self.adb: Adb | None = None
        self.status = tk.StringVar(value="ГУ не подключена")
        self.page = tk.StringVar(value="connect")
        self.busy = False
        self.busy_title = ""
        self.step_var = tk.StringVar(value="Ожидание — нажмите «Подключить», затем ставьте панель")
        self.queue_var = tk.StringVar(value="Очередь пуста")
        self.elapsed_var = tk.StringVar(value="")
        self.pct_var = tk.StringVar(value="")
        self.progress_var = tk.DoubleVar(value=0)
        self._busy_t0 = 0.0
        self._last_progress_t = 0.0
        self._active_stage: str | None = None
        self.jobs: queue.Queue[tuple[str, Callable[[], None]]] = queue.Queue()
        self._worker = threading.Thread(target=self._job_loop, daemon=True, name="hub-worker")
        self._worker.start()

        try:
            self.adb = Adb(on_log=self.journal.adb)
            self.journal.write("INFO", "adb", f"бинарник: {self.adb.binary}")
        except AdbError as exc:
            self.status.set(str(exc))
            self.journal.error("adb", exc)

        self._build()
        self.root.after(150, self._pump_log)
        self.journal.write("INFO", "app", "Changan Hub запущен. Установка идёт через официальный ADB.")
        try:
            info = certificate_info()
            self.journal.write(
                "INFO",
                "cert",
                f"локальный сертификат serial=0x{info['serial_hex']}",
                path=info["path"],
            )
        except Exception as exc:  # noqa: BLE001
            self.journal.error("cert", exc)
        self.root.after(400, self.refresh_connection)

    def _build(self) -> None:
        shell = ttk.Frame(self.root)
        shell.pack(fill=tk.BOTH, expand=True)

        nav = tk.Frame(shell, bg=PANEL, width=220)
        nav.pack(side=tk.LEFT, fill=tk.Y)
        nav.pack_propagate(False)
        tk.Label(
            nav, text="CHANGAN HUB", bg=PANEL, fg=ACCENT, font=("Segoe UI", 16, "bold")
        ).pack(anchor="w", padx=20, pady=(24, 4))
        tk.Label(
            nav, text="Lamore 2023 · Feiyu", bg=PANEL, fg=MUTED, font=("Segoe UI", 10)
        ).pack(anchor="w", padx=20, pady=(0, 20))

        pages = [
            ("connect", "Подключение"),
            ("install", "Установка APK"),
            ("overlay", "Правая панель"),
            ("apps", "Приложения ГУ"),
            ("catalog", "Каталог"),
            ("tools", "Сервис"),
        ]
        for key, label in pages:
            ttk.Button(
                nav,
                text=label,
                style="Nav.TButton",
                command=lambda k=key, t=label: self.show(k, t),
            ).pack(fill=tk.X, padx=12, pady=3)

        ttk.Button(nav, text="Проверить ADB", command=self.refresh_connection).pack(
            side=tk.BOTTOM, fill=tk.X, padx=12, pady=12
        )

        main = ttk.Frame(shell)
        main.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        top = ttk.Frame(main)
        top.pack(fill=tk.X, padx=20, pady=(16, 8))
        ttk.Label(top, textvariable=self.status, style="H.TLabel").pack(side=tk.LEFT)
        self.dot = tk.Canvas(top, width=18, height=18, bg=BG, highlightthickness=0)
        self.dot.pack(side=tk.RIGHT)
        self._set_dot(False)

        loader = tk.Frame(main, bg=CARD)
        loader.pack(fill=tk.X, padx=20, pady=(0, 8))
        head = tk.Frame(loader, bg=CARD)
        head.pack(fill=tk.X, padx=12, pady=(8, 0))
        tk.Label(head, text="Процесс установки", bg=CARD, fg=TEXT, font=FONT_H).pack(side=tk.LEFT)
        tk.Label(head, textvariable=self.elapsed_var, bg=CARD, fg=MUTED, font=("Segoe UI", 10)).pack(
            side=tk.LEFT, padx=12
        )
        tk.Label(head, textvariable=self.pct_var, bg=CARD, fg=ACCENT, font=("Segoe UI", 10, "bold")).pack(
            side=tk.RIGHT
        )
        tk.Label(loader, textvariable=self.step_var, bg=CARD, fg=ACCENT, font=FONT, anchor="w").pack(
            fill=tk.X, padx=12, pady=(4, 2)
        )
        self.progress_bar = ttk.Progressbar(
            loader, variable=self.progress_var, maximum=100, mode="determinate"
        )
        self.progress_bar.pack(fill=tk.X, padx=12, pady=4)
        stages = tk.Frame(loader, bg=CARD)
        stages.pack(fill=tk.X, padx=12, pady=(0, 4))
        self.stage_labels: dict[str, tk.Label] = {}
        for i, (key, title) in enumerate(PROCESS_STAGES):
            lbl = tk.Label(
                stages,
                text=f"○  {title}",
                bg=CARD,
                fg=MUTED,
                font=("Segoe UI", 10),
                anchor="w",
            )
            lbl.grid(row=i // 2, column=i % 2, sticky="w", padx=(0, 28), pady=1)
            self.stage_labels[key] = lbl
        qrow = tk.Frame(loader, bg=CARD)
        qrow.pack(fill=tk.X, padx=12, pady=(0, 8))
        tk.Label(qrow, textvariable=self.queue_var, bg=CARD, fg=MUTED, font=("Segoe UI", 10)).pack(
            side=tk.LEFT
        )
        ttk.Button(qrow, text="Сбросить очередь", command=self.clear_queue).pack(side=tk.RIGHT)
        self.root.after(400, self._tick_loader)

        log_frame = tk.Frame(main, bg=PANEL)
        log_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=20, pady=(8, 12))
        log_top = tk.Frame(log_frame, bg=PANEL)
        log_top.pack(fill=tk.X, padx=8, pady=(6, 0))
        tk.Label(log_top, text="Журнал → папка logs на флешке (hub.log)", bg=PANEL, fg=MUTED).pack(side=tk.LEFT)
        ttk.Button(log_top, text="Копировать", command=self.copy_log).pack(side=tk.RIGHT, padx=4)
        ttk.Button(log_top, text="Открыть файл", command=self.open_log_file).pack(side=tk.RIGHT, padx=4)
        ttk.Button(log_top, text="Очистить экран", command=self.clear_log_view).pack(side=tk.RIGHT, padx=4)
        self.log_widget = tk.Text(
            log_frame,
            height=7,
            bg="#0A101C",
            fg=TEXT,
            insertbackground=TEXT,
            font=FONT_MONO,
            relief=tk.FLAT,
            wrap=tk.WORD,
        )
        self.log_widget.pack(fill=tk.X, padx=8, pady=8)

        self.stack = ttk.Frame(main)
        self.stack.pack(fill=tk.BOTH, expand=True, padx=20)
        self.pages: dict[str, ttk.Frame] = {}
        self.pages["connect"] = self._page_connect()
        self.pages["install"] = self._page_install()
        self.pages["overlay"] = self._page_overlay()
        self.pages["apps"] = self._page_apps()
        self.pages["catalog"] = self._page_catalog()
        self.pages["tools"] = self._page_tools()
        for frame in self.pages.values():
            frame.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.show("connect", "Подключение")

    def _card(self, parent: tk.Widget, title: str, body: str) -> tk.Frame:
        card = tk.Frame(parent, bg=CARD, padx=16, pady=14)
        tk.Label(card, text=title, bg=CARD, fg=ACCENT, font=FONT_H).pack(anchor="w")
        tk.Label(card, text=body, bg=CARD, fg=MUTED, font=FONT, wraplength=760, justify="left").pack(
            anchor="w", pady=(6, 0)
        )
        return card

    def _page_connect(self) -> ttk.Frame:
        page = ttk.Frame(self.stack)
        ttk.Label(page, text="USB-A → USB-A и инженерное меню", style="Title.TLabel").pack(anchor="w")
        steps = (
            "1. На ГУ откройте Phone / Телефон. Наберите "
            f"{ENGINEERING_CODE} и нажмите вызов.\n"
            f"2. Пароль инженерного меню: {ENGINEERING_PIN}. Меню может быть на китайском — "
            "это нормально даже на английской ГУ.\n"
            "3. Второй пункт слева (USB). Нажмите кнопку ADB. Не USB Storage.\n"
            "4. Кабель USB-A — USB-A именно data-кабель (4 контакта), не зарядка. "
            "Вставьте в штатный USB под парящей консолью / в боксе.\n"
            "5. На ноутбуке Windows: драйвер Google USB / Universal ADB. "
            "Если в диспетчере устройств «Unknown Android» — обновите драйвер вручную.\n"
            f"6. Пароль adb shell, если спросит: {SHELL_PASSWORD}. Hub вводит его сам.\n"
            "Сертификат разработчика Changan не нужен: Hub сам выпускает локальный ключ "
            "с серийником 0xddb66eefd98476f3, который принимает CertificateManager ГУ."
        )
        tk.Label(page, text=steps, bg=BG, fg=TEXT, font=FONT, justify="left", wraplength=820).pack(
            anchor="w", pady=12
        )
        row = ttk.Frame(page)
        row.pack(anchor="w", pady=8)
        ttk.Button(row, text="Подключить / обновить", style="Accent.TButton", command=self.refresh_connection).pack(
            side=tk.LEFT, padx=(0, 8)
        )
        ttk.Button(row, text="Перезапустить adb server", command=self.restart_adb).pack(side=tk.LEFT)
        self.info_box = tk.Label(page, text="", bg=CARD, fg=TEXT, font=FONT_MONO, justify="left", anchor="nw")
        self.info_box.pack(fill=tk.BOTH, expand=True, pady=16)
        return page

    def _page_install(self) -> ttk.Frame:
        page = ttk.Frame(self.stack)
        ttk.Label(page, text="Установка приложений", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            page,
            text="Любой APK будет переподписан под Changan (v1+v2) и поставлен через push + один pm install -r -t -g. "
            "Белое окно 提示 «is not auth, install failed!» — отказ белого списка при установке. "
            "Окно 提示 «is auth app, not allow delete!» — Feiyu не даёт удалять уже авторизованный пакет. "
            "Hub при несовпадении подписи пробует короткий pm uninstall --user 0, иначе ставит новую "
            "QuickBar как com.changanhub.quicklane и отключает старые quickbar/quickdock. "
            "adb install на Feiyu зависает — Hub его не вызывает. "
            "«Открыть флешку» — APK с USB; Hub сам переподпишет под белый список ГУ.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(6, 8))
        row = ttk.Frame(page)
        row.pack(fill=tk.X, pady=(0, 8))
        self.install_btn = ttk.Button(
            row, text="Установить выбранный", style="Accent.TButton", command=self.install_selected
        )
        self.install_btn.pack(side=tk.LEFT)
        ttk.Button(row, text="Выбрать APK…", command=self.pick_apk).pack(side=tk.LEFT, padx=8)
        self.usb_btn = ttk.Button(row, text="Открыть флешку", command=self.open_usb_stick)
        self.usb_btn.pack(side=tk.LEFT)
        ttk.Button(row, text="Папка apps/", command=self.open_apps_folder).pack(side=tk.LEFT, padx=8)
        self.apk_list = tk.Listbox(
            page, bg=CARD, fg=TEXT, font=FONT, selectbackground=ACCENT, selectforeground=BG, height=8
        )
        self.apk_list.pack(fill=tk.BOTH, expand=True, pady=(0, 4))
        self.apk_list.bind("<Double-1>", lambda _e: self.install_selected())
        ttk.Label(
            page,
            text="Кнопка всегда сверху списка. Двойной клик по APK тоже ставит его.",
            style="Muted.TLabel",
        ).pack(anchor="w")
        self.refresh_apk_list()
        return page

    def _page_overlay(self) -> ttk.Frame:
        page = ttk.Frame(self.stack)
        ttk.Label(page, text="Правая панель поверх всех окон", style="Title.TLabel").pack(anchor="w")
        row = ttk.Frame(page)
        row.pack(fill=tk.X, pady=(12, 8))
        self.overlay_install_btn = ttk.Button(
            row, text="Установить и запустить панель", style="Accent.TButton", command=self.deploy_overlay
        )
        self.overlay_install_btn.pack(side=tk.LEFT)
        ttk.Button(row, text="Только запустить", command=self.resume_overlay).pack(side=tk.LEFT, padx=8)
        ttk.Button(row, text="Остановить", command=self.kill_overlay).pack(side=tk.LEFT, padx=8)
        ttk.Button(row, text="Удалить с ГУ", command=self.wipe_overlay).pack(side=tk.LEFT)
        ttk.Label(
            page,
            text=f"APK: {overlay_apk()}",
            style="Muted.TLabel",
        ).pack(anchor="w")
        body = (
            "«Удалить с ГУ» только отключает панель: Feiyu не удаляет auth-пакет "
            "(提示 «is auth app, not allow delete!»). Повторная установка ставит новый "
            "com.changanhub.quicklane и отключает старые quickbar/quickdock. "
            "Запуск поднимает только сервис справа — окно приложения не всплывает поверх карты. "
            "Свёрнуто панель сама не разворачивается (сеть/USB/watchdog только держат процесс). "
            "Клавиатура — одна кнопка на 20% ниже верха. После ACC колонка поднимается в том же виде. "
            "На экране — зелёная колонка СПРАВА, не иконка в меню."
        )
        ttk.Label(
            page,
            text=body,
            style="Muted.TLabel",
            wraplength=640,
            justify="left",
        ).pack(anchor="w", pady=12, fill=tk.X)
        return page

    def _page_apps(self) -> ttk.Frame:
        page = ttk.Frame(self.stack)
        ttk.Label(page, text="Что уже стоит на ГУ", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            page,
            text="После установки панели здесь появится строка «QuickBar (правая панель) · "
            "com.changanhub.quicklane». Старые com.changanhub.quickbar и com.changanhub.quickdock "
            "могут остаться в списке — Feiyu их не удаляет (提示 not allow delete). "
            "На экране — зелёная колонка справа. В фильтре наберите quickbar, quickdock или quicklane.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(4, 0))
        row = ttk.Frame(page)
        row.pack(fill=tk.X, pady=8)
        ttk.Button(row, text="Обновить список", style="Accent.TButton", command=self.refresh_packages).pack(
            side=tk.LEFT
        )
        self.launch_btn = ttk.Button(row, text="Запустить выбранное", command=self.launch_selected)
        self.launch_btn.pack(side=tk.LEFT, padx=8)
        self.pkg_filter = tk.StringVar()
        entry = tk.Entry(row, textvariable=self.pkg_filter, bg=CARD, fg=TEXT, insertbackground=TEXT)
        entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)
        entry.bind("<KeyRelease>", lambda _e: self._apply_pkg_filter())
        self.pkg_all: list[str] = []
        self.pkg_list = tk.Listbox(page, bg=CARD, fg=TEXT, font=FONT_MONO, selectbackground=ACCENT)
        self.pkg_list.pack(fill=tk.BOTH, expand=True, pady=8)
        return page

    def _page_catalog(self) -> ttk.Frame:
        page = ttk.Frame(self.stack)
        ttk.Label(page, text="Что имеет смысл поставить", style="Title.TLabel").pack(anchor="w", pady=(0, 8))
        canvas = tk.Canvas(page, bg=BG, highlightthickness=0)
        scroll = ttk.Scrollbar(page, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        inner.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=inner, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        for app in CATALOG:
            card = self._card(inner, app.name, f"{app.summary}\n{app.notes} {app.url or ''}".strip())
            card.pack(fill=tk.X, pady=6)
        return page

    def _page_tools(self) -> ttk.Frame:
        page = ttk.Frame(self.stack)
        ttk.Label(page, text="Сервис и диагностика", style="Title.TLabel").pack(anchor="w")
        grid = ttk.Frame(page)
        grid.pack(anchor="w", pady=16)
        actions = [
            ("Свойства ГУ", self.refresh_connection),
            ("Снимок экрана", self.take_screenshot),
            ("Открыть Android Settings", self.open_settings),
            ("Очистить кэш лаунчера", self.clear_launcher),
            ("Перезагрузить ГУ", self.reboot_hu),
            ("Показать сертификат", self.show_cert),
            ("Открыть журнал", self.open_log_file),
        ]
        for i, (label, fn) in enumerate(actions):
            ttk.Button(grid, text=label, command=fn).grid(row=i // 2, column=i % 2, sticky="ew", padx=6, pady=6)
        ttk.Label(
            page,
            text="Перезагрузка ГУ также делается удержанием громкости «−» на руле 10–20 секунд.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=12)
        return page

    def show(self, name: str, title: str | None = None) -> None:
        self.journal.action("раздел", title or name)
        self.page.set(name)
        self.pages[name].tkraise()

    def log(self, message: str) -> None:
        self.journal.write("INFO", "ui", message)

    def _ui(self, fn: Callable[[], None]) -> None:
        self.root.after(0, fn)

    def _pump_log(self) -> None:
        while True:
            try:
                line = self.log_q.get_nowait()
            except queue.Empty:
                break
            self.log_widget.insert(tk.END, line.rstrip() + "\n")
            self.log_widget.see(tk.END)
        self.root.after(120, self._pump_log)

    def copy_log(self) -> None:
        self.journal.action("копировать журнал")
        text = self.log_widget.get("1.0", tk.END)
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.journal.write("INFO", "ui", "журнал скопирован в буфер")

    def clear_log_view(self) -> None:
        self.journal.action("очистить экран журнала")
        self.log_widget.delete("1.0", tk.END)
        self.journal.write("INFO", "ui", f"файл журнала не тронут: {self.journal.path}")

    def open_log_file(self) -> None:
        self.journal.action("открыть файл журнала", str(self.journal.path))
        path = self.journal.path
        try:
            if os.name == "nt":
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                subprocess.run(["xdg-open", str(path)], check=False)
        except Exception as exc:  # noqa: BLE001
            self.journal.error("log-open", exc)

    def _set_dot(self, on: bool) -> None:
        self.dot.delete("all")
        self.dot.create_oval(3, 3, 15, 15, fill=ACCENT if on else DANGER, outline="")

    def _need_adb(self) -> Adb | None:
        if not self.adb:
            try:
                self.adb = Adb(on_log=self.journal.adb)
                self.journal.write("INFO", "adb", f"бинарник: {self.adb.binary}")
            except AdbError as exc:
                self.journal.error("adb", exc)
                self._ui(lambda: messagebox.showerror("ADB", str(exc)))
                return None
        else:
            self.adb.on_log = self.journal.adb
        return self.adb

    def _tick_loader(self) -> None:
        try:
            if not self.root.winfo_exists():
                return
        except tk.TclError:
            return
        if self.busy:
            elapsed = int(time.monotonic() - self._busy_t0)
            self.elapsed_var.set(f"идёт {elapsed} с")
            if time.monotonic() - self._last_progress_t > 1.2:
                if str(self.progress_bar.cget("mode")) != "indeterminate":
                    self.progress_bar.configure(mode="indeterminate")
                    self.progress_bar.start(12)
        try:
            self.root.after(400, self._tick_loader)
        except tk.TclError:
            return

    def _reset_stages(self) -> None:
        self._active_stage = None

        def go() -> None:
            for key, title in PROCESS_STAGES:
                self.stage_labels[key].configure(text=f"○  {title}", fg=MUTED)

        self._ui(go)

    def _apply_stage(self, message: str, percent: int) -> None:
        key = classify_install_step(message)
        if key:
            self._active_stage = key
        low = message.lower()
        failed = any(word in low for word in ("ошибка", "не удалась", "не удалось", "не найден"))
        # Only tick the whole pipeline if we actually entered an install stage.
        finished = percent >= 100 and not failed and self._active_stage is not None
        active = self._active_stage

        def go() -> None:
            titles = dict(PROCESS_STAGES)
            order = [k for k, _ in PROCESS_STAGES]
            idx = order.index(active) if active in titles else -1
            for i, stage in enumerate(order):
                title = titles[stage]
                widget = self.stage_labels[stage]
                if failed and stage == active:
                    widget.configure(text=f"✕  {title}", fg=DANGER)
                elif finished or (idx >= 0 and i < idx):
                    widget.configure(text=f"✓  {title}", fg=ACCENT)
                elif stage == active:
                    widget.configure(text=f"●  {title}  …", fg=ACCENT)

        self._ui(go)

    def _show_progress(self, message: str, percent: int) -> None:
        queued = self.jobs.qsize()
        qtext = "Очередь пуста" if queued == 0 else f"В очереди ещё {queued}"
        pct = max(0, min(100, int(percent)))
        self._last_progress_t = time.monotonic()
        self._apply_stage(message, pct)

        def go() -> None:
            self.step_var.set(message)
            self.queue_var.set(qtext)
            self.pct_var.set(f"{pct} %")
            self.progress_bar.stop()
            self.progress_bar.configure(mode="determinate")
            self.progress_var.set(pct)

        self._ui(go)
        self.journal.write("INFO", "step", message, pct=pct)

    def clear_queue(self) -> None:
        self.journal.action("сбросить очередь")
        dropped = 0
        while True:
            try:
                self.jobs.get_nowait()
                dropped += 1
            except queue.Empty:
                break
        self.journal.write(
            "WARN",
            "job",
            f"снято из очереди: {dropped}. Текущий шаг доработает (лимит ADB 8–40 с).",
        )
        self._show_progress(self.step_var.get() or "Ожидание", int(self.progress_var.get()))

    def _work(self, title: str, fn: Callable[[], None]) -> None:
        self.journal.action("кнопка", title)
        if self.busy:
            self.journal.write(
                "WARN",
                "job",
                f"пропуск «{title}»: уже выполняется «{self.busy_title}». Дождитесь лоадера или сбросьте очередь.",
            )
            self._ui(lambda: self.queue_var.set(f"Идёт «{self.busy_title}» — повтор не ставлю"))
            return
        pending = list(self.jobs.queue)
        if any(t == title for t, _ in pending):
            self.journal.write("WARN", "job", f"«{title}» уже в очереди")
            return
        waiting = self.jobs.qsize()
        if waiting:
            self.journal.write("INFO", "job", f"в очереди: {title} (перед этим ещё {waiting})")
        else:
            self.journal.write("INFO", "job", f"старт: {title}")
        self.jobs.put((title, fn))
        self._ui(lambda: self.queue_var.set(f"В очереди ещё {self.jobs.qsize()}"))

    def _job_loop(self) -> None:
        while True:
            title, fn = self.jobs.get()
            self.busy = True
            self.busy_title = title
            self._busy_t0 = time.monotonic()
            self._last_progress_t = time.monotonic()
            self._reset_stages()
            self._show_progress(f"Выполняется: {title}", 5)
            self.journal.write("INFO", "job", f"выполняется: {title}")
            try:
                fn()
                self.journal.write("INFO", "job", f"готово: {title}")
                elapsed = int(time.monotonic() - self._busy_t0)
                self._ui(lambda n=elapsed: self.elapsed_var.set(f"готово за {n} с"))
                self._show_progress(f"Готово: {title}", 100)
            except AdbError as exc:
                self.journal.write("ERROR", title, str(exc))
                self._show_progress(f"Ошибка: {exc}", 100)
            except Exception as exc:  # noqa: BLE001
                self.journal.error(title, exc)
                self._show_progress(f"Ошибка: {title}", 100)
            finally:
                self.busy = False
                self.busy_title = ""
                left = self.jobs.qsize()
                self._ui(
                    lambda n=left: self.queue_var.set("Очередь пуста" if n == 0 else f"В очереди ещё {n}")
                )
                self._ui(lambda: self.progress_bar.stop())

    def _hu_ready(self, adb: Adb) -> bool:
        # Never call adb.connected() here: devices -l was the last line in the
        # user's log before install hung, and it blocks the worker with no loader.
        return bool(adb.serial)

    def refresh_connection(self) -> None:
        def go() -> None:
            adb = self._need_adb()
            if not adb:
                return
            adb.start_server()
            self._refresh_now(adb)

        self._work("Подключение", go)

    def restart_adb(self) -> None:
        def go() -> None:
            adb = self._need_adb()
            if not adb:
                return
            adb.kill_server()
            adb.start_server()
            self.log("adb server перезапущен")
            self._refresh_now(adb)

        self._work("adb restart", go)

    def _refresh_now(self, adb: Adb) -> None:
        devices = adb.devices()
        if not devices:
            self._ui(lambda: self.status.set("Устройств нет. Включите ADB на ГУ и проверьте кабель."))
            self._ui(lambda: self._set_dot(False))
            self._ui(
                lambda: self.info_box.configure(
                    text="adb devices пуст.\nКабель data? ADB в инженерном меню? Драйвер Windows?"
                )
            )
            self.journal.write("WARN", "connect", "adb devices пуст")
            return
        lines = ["Найденные устройства:"]
        for dev in devices:
            lines.append(f"  {dev['raw']}")
            self.journal.write("INFO", "connect", dev["raw"])
        ready = [d for d in devices if d["state"] == "device"]
        if not ready:
            self._ui(lambda: self.status.set("ГУ видна, но не в состоянии device"))
            self._ui(lambda: self._set_dot(False))
            text = "\n".join(lines)
            self._ui(lambda t=text: self.info_box.configure(text=t))
            return
        adb.serial = ready[0]["serial"]
        self._ui(lambda: self.status.set(f"Подключено · {adb.serial}"))
        self._ui(lambda: self._set_dot(True))
        pretty = "\n".join(lines) + (
            "\n\nADB device есть. Свойства ГУ специально не спрашиваем — "
            "getprop на Feiyu часто вешает shell. Ставьте панель сразу."
        )
        self._ui(lambda t=pretty: self.info_box.configure(text=t))
        self.journal.write("INFO", "connect", f"индикатор зелёный, serial={adb.serial}")

    def refresh_apk_list(self) -> None:
        self.apk_list.delete(0, tk.END)
        folder = bundled_apps()
        files = sorted(folder.glob("*.apk"))
        if not files:
            self.apk_list.insert(tk.END, f"(пусто) положите APK в {folder}")
            return
        for item in files:
            self.apk_list.insert(tk.END, str(item))

    def open_apps_folder(self) -> None:
        folder = bundled_apps()
        self.log(str(folder))
        try:
            if os.name == "nt":
                os.startfile(folder)  # type: ignore[attr-defined]
            else:
                subprocess.run(["xdg-open", str(folder)], check=False)
        except Exception as exc:  # noqa: BLE001
            self.log(str(exc))

    def pick_apk(self) -> None:
        self.journal.action("выбрать APK")
        path = filedialog.askopenfilename(filetypes=[("APK", "*.apk")])
        if not path:
            self.journal.write("INFO", "ui", "выбор APK отменён")
            return
        self.journal.write("INFO", "ui", f"выбран APK {path}")
        self.apk_list.insert(0, path)
        self.apk_list.selection_clear(0, tk.END)
        self.apk_list.selection_set(0)

    def open_usb_stick(self) -> None:
        self.journal.action("открыть флешку")
        apks = list_usb_apks()
        roots = removable_roots()
        if apks:
            self.apk_list.delete(0, tk.END)
            for item in apks:
                self.apk_list.insert(tk.END, str(item))
            self.apk_list.selection_clear(0, tk.END)
            self.apk_list.selection_set(0)
            self.log(f"Флешка: {len(apks)} APK. Hub переподпишет выбранный под белый список ГУ.")
            return
        initial = str(roots[0]) if roots else None
        path = filedialog.askopenfilename(
            title="APK на флешке",
            filetypes=[("APK", "*.apk")],
            initialdir=initial,
        )
        if not path:
            self.journal.write("INFO", "ui", "флешка: APK не выбран")
            return
        self.journal.write("INFO", "ui", f"флешка APK {path}")
        self.apk_list.insert(0, path)
        self.apk_list.selection_clear(0, tk.END)
        self.apk_list.selection_set(0)

    def install_selected(self) -> None:
        selection = self.apk_list.curselection()
        if not selection:
            messagebox.showinfo("Установка", "Выберите APK в списке")
            return
        path = Path(self.apk_list.get(selection[0]))
        if not path.exists():
            messagebox.showerror("Установка", f"Нет файла {path}")
            return

        def go() -> None:
            adb = self._need_adb()
            if not adb or not self._hu_ready(adb):
                raise AdbError("Сначала нажмите «Подключить». Без serial установка не стартует.")

            def progress(message: str, percent: int) -> None:
                self._show_progress(message, percent)

            if path.name.lower().startswith("quickbar"):
                lines = install_overlay(adb, progress=progress)
                for line in lines:
                    self.journal.write("INFO", "overlay", line)
                joined = "\n".join(lines).lower()
                self.log("Готово" if "пакет установлен" in joined else "Не установлено")
                if "not auth" in joined or "-118" in joined:
                    self._ui(
                        lambda: messagebox.showerror(
                            "ГУ отказала в установке",
                            "Окно 提示 «is not auth, install failed!» — белый список Feiyu (код -118).\n"
                            "В журнале смотрите serial уже стоящих приложений и строку «Подписано».\n"
                            "Пришлите logs\\hub.log, если снова отказ.",
                        )
                    )
                return
            report = install_apk(adb, path, progress=progress)
            self.log("Готово" if report.ok else "Не установлено")
            if not report.ok and any("not auth" in line.lower() or "-118" in line for line in report.log):
                self._ui(
                    lambda: messagebox.showerror(
                        "ГУ отказала в установке",
                        "Окно 提示 «is not auth, install failed!» — белый список Feiyu (код -118).\n"
                        "В журнале смотрите serial уже стоящих приложений и строку «Подписано».\n"
                        "Пришлите logs\\hub.log, если снова отказ.",
                    )
                )

        self._work(f"Установка {path.name}", go)

    def deploy_overlay(self) -> None:
        def go() -> None:
            adb = self._need_adb()
            if not adb or not self._hu_ready(adb):
                raise AdbError("Сначала нажмите «Подключить». Без serial установка не стартует.")

            def progress(message: str, percent: int) -> None:
                self._show_progress(message, percent)

            lines = install_overlay(adb, progress=progress)
            for line in lines:
                self.journal.write("INFO", "overlay", line)
            joined = "\n".join(lines).lower()
            if "not auth" in joined or "-118" in joined:
                self._ui(
                    lambda: messagebox.showerror(
                        "ГУ отказала в установке",
                        "Окно 提示 «com.changanhub.quickbar is not auth, install failed!» — "
                        "белый список Feiyu (код -118).\n"
                        "В журнале — serial приложений на ГУ и способ подписи. "
                        "Пришлите logs\\hub.log, если отказ повторится.",
                    )
                )

        self._work("QuickBar", go)

    def resume_overlay(self) -> None:
        def go() -> None:
            adb = self._need_adb()
            if not adb:
                return
            def progress(message: str, percent: int) -> None:
                self._show_progress(message, percent)
            for line in start_overlay(adb, progress=progress):
                self.journal.write("INFO", "overlay", line)

        self._work("Запуск панели", go)

    def kill_overlay(self) -> None:
        def go() -> None:
            adb = self._need_adb()
            if not adb:
                return
            for line in stop_overlay(adb):
                self.log(line)

        self._work("Стоп панели", go)

    def wipe_overlay(self) -> None:
        def go() -> None:
            adb = self._need_adb()
            if not adb or not self._hu_ready(adb):
                raise AdbError("Сначала нажмите «Подключить». Без serial удаление не стартует.")

            def progress(message: str, percent: int) -> None:
                self._show_progress(message, percent)

            for line in remove_overlay(adb, progress=progress):
                self.journal.write("INFO", "overlay", line)

        self._work("Удаление панели", go)

    def refresh_packages(self) -> None:
        def go() -> None:
            adb = self._need_adb()
            if not adb or not self._hu_ready(adb):
                self.log("Нет ГУ — сначала «Подключить»")
                return
            pkgs = adb.packages()
            self.pkg_all = pkgs
            self.root.after(0, self._apply_pkg_filter)
            if any(p in pkgs for p in ("com.changanhub.quicklane", "com.changanhub.quickdock", "com.changanhub.quickbar")):
                self.log("Панель есть в списке: QuickBar · com.changanhub.quicklane")
            else:
                self.log(
                    f"Пакетов: {len(pkgs)}. QuickBar (com.changanhub.quicklane) нет — "
                    "установка не прошла, в меню ГУ его тоже не будет."
                )

        self._work("Список пакетов", go)

    def _apply_pkg_filter(self) -> None:
        q = self.pkg_filter.get().lower().strip()
        self.pkg_list.delete(0, tk.END)
        for pkg in self.pkg_all:
            row = package_label(pkg)
            if q and q not in row.lower() and q not in pkg.lower():
                continue
            self.pkg_list.insert(tk.END, row)

    def launch_selected(self) -> None:
        selection = self.pkg_list.curselection()
        if not selection:
            return
        pkg = package_from_row(self.pkg_list.get(selection[0]))

        def go() -> None:
            adb = self._need_adb()
            if not adb:
                return
            result = adb.launch(pkg)
            self.log(result.text or result.stderr or f"launch {pkg}")

        self._work(f"Запуск {pkg}", go)

    def take_screenshot(self) -> None:
        def go() -> None:
            adb = self._need_adb()
            if not adb:
                return
            dest = bundled_apps().parent / "screenshots" / "hu.png"
            result = adb.screenshot(dest)
            self.log(result.text or f"сохранено {dest}")

        self._work("Скриншот", go)

    def open_settings(self) -> None:
        def go() -> None:
            adb = self._need_adb()
            if not adb:
                return
            result = adb.launch("com.android.settings")
            self.log(result.text or result.stderr)

        self._work("Settings", go)

    def clear_launcher(self) -> None:
        def go() -> None:
            adb = self._need_adb()
            if not adb:
                return
            for result in adb.clear_launcher_cache():
                self.log(result.text or "cleared")

        self._work("Кэш лаунчера", go)

    def reboot_hu(self) -> None:
        if not messagebox.askyesno("Ребут", "Перезагрузить головное устройство?"):
            return

        def go() -> None:
            adb = self._need_adb()
            if not adb:
                return
            result = adb.reboot()
            self.log(result.text or "reboot")

        self._work("Reboot", go)

    def show_cert(self) -> None:
        info = certificate_info(ensure_keystore())
        messagebox.showinfo(
            "Сертификат",
            "\n".join(f"{k}: {v}" for k, v in info.items())
            + "\n\nЭто не сертификат Changan, а локальный ключ с тем же serial "
            "(openssl-совместимый, без CA:TRUE). Разработческий сертификат завода не нужен. "
            "Если на ГУ всплывает 提示 «is not auth», Hub сам перевыпустит старый ключ из data\\certs."
        )

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    HubApp().run()
