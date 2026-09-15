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
from hub.capture import Recorder, take_screenshot as capture_screenshot, CAPTURE_VERSION
from hub.catalog import CATALOG, package_from_row, package_label
from hub.bundle import PACKAGE_SUFFIXES
from hub.installer import PROCESS_STAGES, classify_install_step, install_apk
from hub.journal import Journal
from hub.overlay import PACKAGE as OVERLAY_PACKAGE, install_overlay, overlay_apk, remove_overlay, start_overlay, stop_overlay
from hub.player import PACKAGE as PLAYER_PACKAGE, install_player, player_apk, start_player
from hub.aichat import PACKAGE as AICHAT_PACKAGE, aichat_apk, install_aichat, start_aichat
from hub.paths import bundled_apps, captures_dir
from hub.signer import certificate_info, ensure_keystore
from hub.usb import list_usb_apks, removable_roots
from hub.version import VERSION
from hub.hu_info import installed_version

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
        self.root.title(f"Changan Hub {VERSION} — Lamore 2023")
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
        self.recorder: Recorder | None = None
        self.record_status = tk.StringVar(value="Запись не идёт")
        self.last_capture = tk.StringVar(value="Файлов ещё нет")
        self.overlay_hu_ver = tk.StringVar(value="на ГУ: не проверяли")
        self.player_hu_ver = tk.StringVar(value="на ГУ: не проверяли")
        self.chat_hu_ver = tk.StringVar(value="на ГУ: не проверяли")
        self._stopping_record = False
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
        ).pack(anchor="w", padx=20, pady=(24, 2))
        tk.Label(
            nav,
            text=f"версия {VERSION}",
            bg=PANEL,
            fg=ACCENT,
            font=("Segoe UI", 10, "bold"),
        ).pack(anchor="w", padx=20, pady=(0, 2))
        tk.Label(
            nav,
            text="разработано в ИТ-Мастерской",
            bg=PANEL,
            fg=ACCENT,
            font=("Segoe UI", 9, "bold"),
            wraplength=180,
            justify="left",
        ).pack(anchor="w", padx=20, pady=(0, 6))
        tk.Label(
            nav, text="Lamore 2023 · Feiyu", bg=PANEL, fg=MUTED, font=("Segoe UI", 10)
        ).pack(anchor="w", padx=20, pady=(0, 20))

        pages = [
            ("connect", "Подключение"),
            ("ours", "Наши приложения"),
            ("install", "Сторонние APK"),
            ("apps", "Приложения ГУ"),
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
            height=4,
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
        ours = self._page_ours()
        self.pages["ours"] = ours
        self.pages["overlay"] = ours
        self.pages["player"] = ours
        self.pages["aichat"] = ours
        self.pages["install"] = self._page_install()
        self.pages["demo"] = self._page_demo()
        self.pages["apps"] = self._page_apps()
        self.pages["catalog"] = self._page_catalog()
        self.pages["tools"] = self._page_tools()
        for frame in self.pages.values():
            frame.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.show("connect", "Подключение")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(500, self._tick_record)

    def _scrollable_inner(self, page: ttk.Frame) -> ttk.Frame:
        """Page body that fits the leftover stack (loader + log stay on screen)."""
        holder = ttk.Frame(page)
        holder.pack(fill=tk.BOTH, expand=True)
        canvas = tk.Canvas(holder, bg=BG, highlightthickness=0, borderwidth=0)
        scroll = ttk.Scrollbar(holder, orient="vertical", command=canvas.yview)
        inner = ttk.Frame(canvas)
        window = canvas.create_window((0, 0), window=inner, anchor="nw")

        def sync_region(_event=None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all") or (0, 0, 0, 0))

        def sync_width(event: tk.Event) -> None:
            canvas.itemconfigure(window, width=max(event.width, 1))

        inner.bind("<Configure>", sync_region)
        canvas.bind("<Configure>", sync_width)
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        page._hub_canvas = canvas  # type: ignore[attr-defined]
        return inner

    def _wire_mousewheel(self, canvas: tk.Canvas, inner: tk.Widget) -> None:
        def wheel(event: tk.Event, view=canvas) -> str:
            delta = int(getattr(event, "delta", 0) or 0)
            if delta:
                units = int(-delta / 120) if abs(delta) >= 120 else (-1 if delta > 0 else 1)
                view.yview_scroll(units, "units")
            elif int(getattr(event, "num", 0) or 0) == 4:
                view.yview_scroll(-1, "units")
            elif int(getattr(event, "num", 0) or 0) == 5:
                view.yview_scroll(1, "units")
            return "break"

        def bind_tree(widget: tk.Widget) -> None:
            widget.bind("<MouseWheel>", wheel)
            widget.bind("<Button-4>", wheel)
            widget.bind("<Button-5>", wheel)
            for child in widget.winfo_children():
                bind_tree(child)

        bind_tree(inner)
        canvas.bind("<MouseWheel>", wheel)
        canvas.bind("<Button-4>", wheel)
        canvas.bind("<Button-5>", wheel)

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
        row = ttk.Frame(page)
        row.pack(anchor="w", pady=8, fill=tk.X)
        self.connect_btn = ttk.Button(
            row, text="Подключить / обновить", style="Accent.TButton", command=self.refresh_connection
        )
        self.connect_btn.pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(row, text="Перезапустить adb server", command=self.restart_adb).pack(side=tk.LEFT)
        steps = (
            f"Телефон ГУ: {ENGINEERING_CODE} → PIN {ENGINEERING_PIN} → USB → ADB "
            "(не Storage). После ACC повторить. "
            "Кабель ноутбук→штатный USB ГУ, не флешка E:. "
            f"Пароль shell {SHELL_PASSWORD} Hub вводит сам. "
            "Пустой список = ADB на ГУ выключен, не поломка программы."
        )
        tk.Label(page, text=steps, bg=BG, fg=TEXT, font=FONT, justify="left", wraplength=640).pack(
            anchor="w", pady=12
        )
        self.info_box = tk.Label(page, text="", bg=CARD, fg=TEXT, font=FONT_MONO, justify="left", anchor="nw")
        self.info_box.pack(fill=tk.X, pady=16)
        return page

    def _page_ours(self) -> ttk.Frame:
        page = ttk.Frame(self.stack)
        inner = self._scrollable_inner(page)
        ttk.Label(inner, text="Три приложения этой сборки", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            inner,
            text="Одна зелёная кнопка ставит пакет на ГУ. «Открыть» только запускает уже стоящее. "
            "Новая папка Hub не обновляет старый id — поэтому панель, плеер и чат ставятся новым именем. "
            "Флешка с музыкой и APK — в USB магнитолы, не в ноутбуке. "
            "Список прокручивается колёсиком и полосой справа.",
            style="Muted.TLabel",
            wraplength=720,
            justify="left",
        ).pack(anchor="w", pady=(6, 10))

        def card(title: str, bundled: str, status: tk.StringVar, install, open_fn) -> ttk.Button:
            box = tk.Frame(inner, bg=CARD, padx=16, pady=12)
            box.pack(fill=tk.X, pady=6)
            tk.Label(box, text=title, bg=CARD, fg=ACCENT, font=FONT_H).pack(anchor="w")
            tk.Label(box, text=bundled, bg=CARD, fg=MUTED, font=FONT).pack(anchor="w", pady=(2, 0))
            tk.Label(box, textvariable=status, bg=CARD, fg=TEXT, font=FONT).pack(anchor="w", pady=(2, 8))
            row = tk.Frame(box, bg=CARD)
            row.pack(anchor="w")
            btn = ttk.Button(row, text="Поставить эту версию", style="Accent.TButton", command=install)
            btn.pack(side=tk.LEFT)
            ttk.Button(row, text="Открыть", command=open_fn).pack(side=tk.LEFT, padx=8)
            return btn

        self.overlay_install_btn = card(
            "QuickBar — правая колонка",
            f"в ZIP: 1.3.16 · {OVERLAY_PACKAGE}",
            self.overlay_hu_ver,
            self.deploy_overlay,
            self.resume_overlay,
        )
        self.player_install_btn = card(
            "Lamore Player — музыка и видео",
            f"в ZIP: 1.1.7 · {PLAYER_PACKAGE}",
            self.player_hu_ver,
            self.deploy_player,
            self.resume_player,
        )
        self.chat_install_btn = card(
            "AI Chat — DeepSeek / YandexGPT",
            f"в ZIP: 1.0.5 · {AICHAT_PACKAGE}",
            self.chat_hu_ver,
            self.deploy_aichat,
            self.resume_aichat,
        )
        ttk.Label(
            inner,
            text="Отключить старую колонку — «Приложения ГУ». Скриншот и запись экрана — «Сервис».",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(8, 0))
        self._wire_mousewheel(page._hub_canvas, inner)  # type: ignore[attr-defined]
        return page

    def _page_install(self) -> ttk.Frame:
        page = ttk.Frame(self.stack)
        ttk.Label(page, text="Сторонние APK с диска", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            page,
            text="Яндекс, Кинопоиск, HUD — отсюда. QuickBar / плеер / чат ставьте в «Наши приложения», "
            "иначе легко нажать не ту кнопку. Hub переподпишет выбранный файл под белый список ГУ. "
            "Кабель ADB должен быть в магнитоле. Флешка в ноутбуке (диск D:) на ГУ не видна.",
            style="Muted.TLabel",
            wraplength=720,
            justify="left",
        ).pack(anchor="w", pady=(6, 8))
        row = ttk.Frame(page)
        row.pack(fill=tk.X, pady=(0, 8))
        self.install_btn = ttk.Button(
            row, text="Установить выбранный", style="Accent.TButton", command=self.install_selected
        )
        self.install_btn.pack(side=tk.LEFT)
        ttk.Button(row, text="Выбрать APK / XAPK…", command=self.pick_apk).pack(side=tk.LEFT, padx=8)
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
            text="Кнопка всегда сверху списка. Двойной клик по APK/XAPK тоже ставит его.",
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
            "Скрытие и сортировка — в зелёной колонке справа, не в ярлыке плагина. "
            "Старые quickbar/quickkeep/quickrise/quickstash/quickload не удаляются и новых кнопок в них нет. "
            "«Установить и запустить» пишет автозапуск ACC. Рабочая — com.changanhub.qb1_3_16. "
            "APK с флешки в колонке: сверху USB или Память ГУ. Серый ключ подписывает v1+v2 тем же серийником Feiyu, что и Hub; "
            "зелёная кнопка ставит (если подписи ещё нет — сначала подписывает). "
            "Плеер — отдельный раздел."
        )
        ttk.Label(
            page,
            text=body,
            style="Muted.TLabel",
            wraplength=640,
            justify="left",
        ).pack(anchor="w", pady=12, fill=tk.X)
        return page

    def _page_player(self) -> ttk.Frame:
        page = ttk.Frame(self.stack)
        ttk.Label(page, text="Плеер с флешки ГУ", style="Title.TLabel").pack(anchor="w")
        row = ttk.Frame(page)
        row.pack(fill=tk.X, pady=(12, 8))
        ttk.Button(
            row, text="Установить и открыть плеер", style="Accent.TButton", command=self.deploy_player
        ).pack(side=tk.LEFT)
        ttk.Button(row, text="Только открыть", command=self.resume_player).pack(side=tk.LEFT, padx=8)
        ttk.Label(page, text=f"APK: {player_apk()}", style="Muted.TLabel").pack(anchor="w")
        ttk.Label(
            page,
            text=(
                "Lamore Player 1.1.2 читает USB и память ГУ (не флешку ноутбука). "
                "Шрифты и вкладки как у AI Chat, поля 8%/10% плюс зазор под QuickBar. "
                "Центр экрана: вкладки Музыка / Видео / Эквалайзер / Визуализация. "
                "Музыка: файловый менеджер флешки, кнопка Обновить после вставки USB, "
                "очередь, шаффл, повтор, теги, 10-полосный EQ с отдельными жанрами, "
                "BassBoost/Virtualizer/Loudness на audioSessionId. "
                "Видео: полный экран, SRT/ASS рядом с файлом, выбор звуковой дорожки. "
                "Заставки: спектр, волна, частицы, круг, OpenGL-туман под ритм. "
                "Форматы, которые умеет декодер Feiyu: MP3, AAC, M4A, FLAC, WAV, OGG, OPUS, "
                "MP4, MKV, WebM, MOV, TS; WMA/AVI/HEVC/DTS — только если чип их открывает. "
                "Пакет: com.changanhub.pl1_1_7. Старые pl1_1_6 / pl1_1_5 / playload / playrise / lamoreplayer Feiyu не удаляет — "
                "Hub ставит новый id, как QuickBar → qb1_3_16. Без Google Play и без Compose. "
                "Макет экранов без установки на ГУ: docs\\player-layout.html в браузере ноутбука."
            ),
            style="Muted.TLabel",
            wraplength=640,
            justify="left",
        ).pack(anchor="w", pady=12, fill=tk.X)
        return page

    def _page_aichat(self) -> ttk.Frame:
        page = ttk.Frame(self.stack)
        ttk.Label(page, text="AI Chat — DeepSeek и YandexGPT", style="Title.TLabel").pack(anchor="w")
        row = ttk.Frame(page)
        row.pack(fill=tk.X, pady=(12, 8))
        ttk.Button(
            row, text="Установить и открыть чат", style="Accent.TButton", command=self.deploy_aichat
        ).pack(side=tk.LEFT)
        ttk.Button(row, text="Только открыть", command=self.resume_aichat).pack(side=tk.LEFT, padx=8)
        ttk.Label(page, text=f"APK: {aichat_apk()}", style="Muted.TLabel").pack(anchor="w")
        ttk.Label(
            page,
            text=(
                "AI Chat 1.0.4 ходит в интернет с ГУ (SIM/Wi‑Fi), без Google Play. "
                "Озвучка ответов — встроенный RHVoice (голос Елена внутри APK), "
                "системный TTS Android на Feiyu не нужен. "
                "Вкладки: Чат / Настройки / История / Голос. Шрифты ×2, поля 8%/10% "
                "плюс зазор справа под свёрнутый QuickBar. "
                "Провайдеры: DeepSeek (api.deepseek.com) и YandexGPT. Ключи в Android Keystore. "
                "Микрофона на Feiyu нет: голосовой помощник машины — iFlytek, "
                "это не Android SpeechRecognizer. Пишите Яндекс-клавиатурой. "
                "Русские вкладки — из приложения; язык системы ГУ может остаться китайским. "
                "Пакет: com.changanhub.ch1_0_5 (старые chatload / chatrise / aichat Feiyu не удаляет). "
                "Макет: docs\\aichat-layout.html."
            ),
            style="Muted.TLabel",
            wraplength=640,
            justify="left",
        ).pack(anchor="w", pady=12, fill=tk.X)
        return page

    def _page_demo(self) -> ttk.Frame:
        page = ttk.Frame(self.stack)
        ttk.Label(page, text="Демо для клиентов", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            page,
            text="Снимок и видео экрана ГУ → папка captures на флешке, рядом с Хабом.",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(6, 8))
        grid = ttk.Frame(page)
        grid.pack(anchor="w", pady=(0, 8))
        self.demo_shot_btn = ttk.Button(
            grid, text="Сделать скриншот", style="Accent.TButton", command=self.take_screenshot
        )
        self.demo_shot_btn.grid(row=0, column=0, sticky="ew", padx=6, pady=6)
        self.demo_rec60_btn = ttk.Button(
            grid, text="Запись 60 с", style="Accent.TButton", command=lambda: self.start_record(60)
        )
        self.demo_rec60_btn.grid(row=0, column=1, sticky="ew", padx=6, pady=6)
        self.demo_stop_btn = ttk.Button(grid, text="Стоп", command=self.stop_record)
        self.demo_stop_btn.grid(row=0, column=2, sticky="ew", padx=6, pady=6)
        self.demo_rec30_btn = ttk.Button(grid, text="Запись 30 с", command=lambda: self.start_record(30))
        self.demo_rec30_btn.grid(row=1, column=0, sticky="ew", padx=6, pady=6)
        self.demo_rec180_btn = ttk.Button(grid, text="Запись 3 мин", command=lambda: self.start_record(180))
        self.demo_rec180_btn.grid(row=1, column=1, sticky="ew", padx=6, pady=6)
        ttk.Button(grid, text="Папка captures", command=self.open_captures_folder).grid(
            row=1, column=2, sticky="ew", padx=6, pady=6
        )
        ttk.Label(page, textvariable=self.record_status, style="H.TLabel").pack(anchor="w", pady=(4, 2))
        ttk.Label(page, textvariable=self.last_capture, style="Muted.TLabel").pack(anchor="w")
        ttk.Label(
            page,
            text=(
                "Скриншот обычно захватывает и правую панель QuickBar. "
                "Если кодек ГУ не пишет MP4 (Encoder −38), Hub сам снимает кадры в GIF. "
                "Всплывающая панель в ролике screenrecord может не попасть — для панели лучше фото. "
                "Максимум 3 минуты. Перед съёмкой нажмите «Подключить»."
            ),
            style="Muted.TLabel",
            wraplength=640,
            justify="left",
        ).pack(anchor="w", pady=8, fill=tk.X)
        return page

    def _page_apps(self) -> ttk.Frame:
        page = ttk.Frame(self.stack)
        ttk.Label(page, text="Что уже стоит на ГУ", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            page,
            text=(
                "Рабочая панель: QuickBar 1.3.16 · com.changanhub.qb1_3_16. "
                "Плеер: 1.1.7 · com.changanhub.pl1_1_7. Чат: 1.0.5 · com.changanhub.ch1_0_5. "
                "Штатное меню Feiyu сторонние APK не показывает — список здесь полный. "
                "Ярлыки старых quickbar/quickkeep/quickrise без нового свайпа. "
                "«Запустить выбранное» на них поднимает колонку справа. "
                "Фильтр: пустое поле показывает все; «ch» прячет Яндекс."
            ),
            style="Muted.TLabel",
            wraplength=640,
            justify="left",
        ).pack(anchor="w", pady=(4, 0))
        row = ttk.Frame(page)
        row.pack(fill=tk.X, pady=8)
        ttk.Button(row, text="Обновить список", style="Accent.TButton", command=self.refresh_packages).pack(
            side=tk.LEFT
        )
        self.launch_btn = ttk.Button(row, text="Запустить выбранное", command=self.launch_selected)
        self.launch_btn.pack(side=tk.LEFT, padx=8)
        ttk.Button(row, text="Удалить / отключить", command=self.disable_selected).pack(side=tk.LEFT)
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
        inner = self._scrollable_inner(page)
        ttk.Label(inner, text="Что имеет смысл поставить", style="Title.TLabel").pack(
            anchor="w", pady=(0, 8)
        )
        for app in CATALOG:
            card = self._card(inner, app.name, f"{app.summary}\n{app.notes} {app.url or ''}".strip())
            card.pack(fill=tk.X, pady=6)
        self._wire_mousewheel(page._hub_canvas, inner)  # type: ignore[attr-defined]
        return page

    def _page_tools(self) -> ttk.Frame:
        page = ttk.Frame(self.stack)
        ttk.Label(page, text="Сервис и диагностика", style="Title.TLabel").pack(anchor="w")
        grid = ttk.Frame(page)
        grid.pack(anchor="w", pady=16)
        actions = [
            ("Свойства ГУ", self.refresh_connection),
            ("Снимок экрана", self.take_screenshot),
            ("Запись видео ГУ", lambda: self.show("demo", "Демо")),
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
                msg = str(exc)
                self._ui(lambda m=msg: messagebox.showerror("ADB", m))
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
        if not adb.serial:
            return False
        state = adb.raw(["get-state"], timeout=8)
        blob = f"{state.stdout or ''} {state.stderr or ''}".lower()
        if "not found" in blob or "offline" in blob or "unauthorized" in blob:
            return False
        return "device" in blob

    def _assert_install(self, lines: list[str], title: str) -> None:
        joined = "\n".join(lines)
        low = joined.lower()
        if "device not found" in low or "гу отвалилась" in low or "не удалось скопировать" in low:
            raise AdbError(
                "ГУ пропала из ADB. Кабель ноутбук→магнитола, USB → ADB. "
                "Пока флешка в компьютере (диск D:), установка на ГУ не идёт."
            )
        if "не установлен" in low:
            raise AdbError(f"{title} не встал. Смотрите журнал.")

    def _refresh_ours_versions(self, adb: Adb) -> None:
        overlay = installed_version(adb, OVERLAY_PACKAGE) or "нет"
        player = installed_version(adb, PLAYER_PACKAGE) or "нет"
        chat = installed_version(adb, AICHAT_PACKAGE) or "нет"
        self._ui(lambda: self.overlay_hu_ver.set(f"на ГУ: {overlay}"))
        self._ui(lambda: self.player_hu_ver.set(f"на ГУ: {player}"))
        self._ui(lambda: self.chat_hu_ver.set(f"на ГУ: {chat}"))

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
            time.sleep(2)
            devices = adb.devices()
        if not devices:
            self._ui(lambda: self.status.set("Устройств нет. Включите ADB на ГУ и проверьте кабель."))
            self._ui(lambda: self._set_dot(False))
            self._ui(
                lambda: self.info_box.configure(
                    text=(
                        "adb devices пуст — ноутбук не видит ГУ.\n"
                        "После ACC снова: Телефон → *#*#888 → PIN 369875 → USB → ADB "
                        "(не USB Storage).\n"
                        "Кабель data ноутбук→штатный USB ГУ. Флешка с Hub — это не ADB.\n"
                        "Затем «Подключить / обновить». Если пусто — «Перезапустить adb server»."
                    )
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
        self._refresh_ours_versions(adb)

    def refresh_apk_list(self) -> None:
        self.apk_list.delete(0, tk.END)
        folder = bundled_apps()
        files: list[Path] = []
        for suffix in PACKAGE_SUFFIXES:
            files.extend(folder.glob(f"*{suffix}"))
        OUR_APKS = ("quickbar", "player", "aichat")
        files = sorted({item.resolve() for item in files}, key=lambda p: p.name.lower())
        files = [
            item
            for item in files
            if not any(token in item.name.lower() for token in OUR_APKS)
        ]
        if not files:
            self.apk_list.insert(tk.END, f"(пусто) положите APK/XAPK в {folder}")
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
        self.root.update_idletasks()
        path = filedialog.askopenfilename(
            parent=self.root,
            title="Выберите APK или XAPK",
            initialdir=str(bundled_apps()),
            filetypes=(
                ("APK", "*.apk"),
                ("XAPK", "*.xapk"),
                ("APKM", "*.apkm"),
                ("APKS", "*.apks"),
                ("Все файлы", "*.*"),
            ),
        )
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
            self.log(f"Флешка: {len(apks)} APK/XAPK. Hub переподпишет выбранный под белый список ГУ.")
            return
        initial = str(roots[0]) if roots else None
        self.root.update_idletasks()
        path = filedialog.askopenfilename(
            parent=self.root,
            title="APK / XAPK на флешке",
            filetypes=(
                ("APK", "*.apk"),
                ("XAPK", "*.xapk"),
                ("APKM", "*.apkm"),
                ("APKS", "*.apks"),
                ("Все файлы", "*.*"),
            ),
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
            messagebox.showinfo("Установка", "Выберите APK или XAPK в списке")
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
                self.log(
                    "Готово"
                    if "пакет установлен" in joined or "панель на гу сохранена" in joined
                    else "Не установлено"
                )
                if "not auth" in joined or "-118" in joined:
                    self._ui(
                        lambda: messagebox.showerror(
                            "ГУ отказала в установке",
                            "Окно 提示 «is not auth, install failed!» — белый список Feiyu (код -118).\n"
                            "Пришлите logs\\hub.log и data\\probe\\ (VecentekApp.apk, boot-ext.vdex, whitelist.json, publicKey.cert).",
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
                        "Пришлите logs\\hub.log и data\\probe\\ (VecentekApp.apk, boot-ext.vdex, whitelist.json, publicKey.cert).",
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
            self._assert_install(lines, "QuickBar")
            self._refresh_ours_versions(adb)
            joined = "\n".join(lines).lower()
            if "not auth" in joined or "-118" in joined:
                self._ui(
                    lambda: messagebox.showerror(
                        "ГУ отказала в установке",
                        "Окно 提示 «com.changanhub.quickbar is not auth, install failed!» — "
                        "белый список Feiyu (код -118).\n"
                        "Пришлите logs\\hub.log и data\\probe\\ (VecentekApp.apk, boot-ext.vdex, whitelist.json, publicKey.cert).",
                    )
                )

        self._work("QuickBar", go)

    def deploy_player(self) -> None:
        def go() -> None:
            adb = self._need_adb()
            if not adb or not self._hu_ready(adb):
                raise AdbError("Сначала нажмите «Подключить». Без serial установка плеера не стартует.")

            def progress(message: str, percent: int) -> None:
                self._show_progress(message, percent)

            lines = install_player(adb, progress=progress)
            for line in lines:
                self.journal.write("INFO", "player", line)
            self._assert_install(lines, "Плеер")
            self._refresh_ours_versions(adb)
            joined = "\n".join(lines).lower()
            if "not auth" in joined or "-118" in joined:
                self._ui(
                    lambda: messagebox.showerror(
                        "ГУ отказала в установке",
                        "Окно 提示 «is not auth, install failed!» — белый список Feiyu (код -118).\n"
                        "Пришлите logs\\hub.log и data\\probe\\ (VecentekApp.apk, boot-ext.vdex, whitelist.json, publicKey.cert).",
                    )
                )

        self._work("Lamore Player", go)

    def resume_player(self) -> None:
        def go() -> None:
            adb = self._need_adb()
            if not adb or not self._hu_ready(adb):
                raise AdbError("Сначала нажмите «Подключить». Без ГУ плеер не открою.")

            def progress(message: str, percent: int) -> None:
                self._show_progress(message, percent)

            for line in start_player(adb, progress=progress):
                self.journal.write("INFO", "player", line)

        self._work("Запуск плеера", go)

    def deploy_aichat(self) -> None:
        def go() -> None:
            adb = self._need_adb()
            if not adb or not self._hu_ready(adb):
                raise AdbError("Сначала нажмите «Подключить». Без serial установка чата не стартует.")

            def progress(message: str, percent: int) -> None:
                self._show_progress(message, percent)

            lines = install_aichat(adb, progress=progress)
            for line in lines:
                self.journal.write("INFO", "aichat", line)
            self._assert_install(lines, "Чат")
            self._refresh_ours_versions(adb)
            joined = "\n".join(lines).lower()
            if "not auth" in joined or "-118" in joined:
                self._ui(
                    lambda: messagebox.showerror(
                        "ГУ отказала в установке",
                        "Окно 提示 «is not auth, install failed!» — белый список Feiyu (код -118).\n"
                        "Пришлите logs\\hub.log и data\\probe\\ (VecentekApp.apk, boot-ext.vdex, whitelist.json, publicKey.cert).",
                    )
                )

        self._work("AI Chat", go)

    def resume_aichat(self) -> None:
        def go() -> None:
            adb = self._need_adb()
            if not adb or not self._hu_ready(adb):
                raise AdbError("Сначала нажмите «Подключить». Без ГУ чат не открою.")

            def progress(message: str, percent: int) -> None:
                self._show_progress(message, percent)

            for line in start_aichat(adb, progress=progress):
                self.journal.write("INFO", "aichat", line)

        self._work("Запуск AI Chat", go)

    def resume_overlay(self) -> None:
        def go() -> None:
            adb = self._need_adb()
            if not adb or not self._hu_ready(adb):
                raise AdbError("Сначала нажмите «Подключить». Без ГУ запуск панели не стартует.")

            def progress(message: str, percent: int) -> None:
                self._show_progress(message, percent)

            for line in start_overlay(adb, progress=progress):
                self.journal.write("INFO", "overlay", line)

        self._work("Запуск панели", go)

    def kill_overlay(self) -> None:
        def go() -> None:
            adb = self._need_adb()
            if not adb or not self._hu_ready(adb):
                raise AdbError("Сначала нажмите «Подключить».")
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
            from hub.overlay import LEGACY_PACKAGES, PACKAGE

            if PACKAGE in pkgs:
                self.log(f"Рабочая панель в списке: QuickBar · {PACKAGE}")
            elif any(p in pkgs for p in LEGACY_PACKAGES):
                leftovers = ", ".join(p for p in LEGACY_PACKAGES if p in pkgs)
                self.log(
                    f"На ГУ только старые панели ({leftovers}). Скрытия и сортировки в них нет. "
                    f"Установите заново из «Наши приложения» — пакет {PACKAGE}."
                )
            else:
                self.log(
                    f"Пакетов: {len(pkgs)}. QuickBar ({PACKAGE}) нет — "
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
            from hub.overlay import launch_overlay_target, start_overlay
            from hub.player import launch_player_target, start_player
            from hub.aichat import launch_aichat_target, start_aichat

            adb = self._need_adb()
            if not adb:
                return
            overlay = launch_overlay_target(pkg)
            if overlay:
                if not self._hu_ready(adb):
                    raise AdbError("Сначала нажмите «Подключить». Без ГУ панель не запущу.")

                def progress(message: str, percent: int) -> None:
                    self._show_progress(message, percent)

                self.log(
                    f"{pkg} — ярлык панели. Запускаю рабочую QuickBar ({overlay}): "
                    "скрытие и сортировка в зелёной колонке справа, не в меню приложений."
                )
                for line in start_overlay(adb, progress=progress):
                    self.journal.write("INFO", "apps", line)
                return
            player = launch_player_target(pkg)
            if player:
                if not self._hu_ready(adb):
                    raise AdbError("Сначала нажмите «Подключить». Без ГУ плеер не открою.")

                def progress_player(message: str, percent: int) -> None:
                    self._show_progress(message, percent)

                self.log(f"{pkg} — ярлык плеера. Запускаю {player}.")
                for line in start_player(adb, progress=progress_player):
                    self.journal.write("INFO", "apps", line)
                return
            chat = launch_aichat_target(pkg)
            if chat:
                if not self._hu_ready(adb):
                    raise AdbError("Сначала нажмите «Подключить». Без ГУ чат не открою.")

                def progress_chat(message: str, percent: int) -> None:
                    self._show_progress(message, percent)

                self.log(f"{pkg} — ярлык чата. Запускаю {chat}.")
                for line in start_aichat(adb, progress=progress_chat):
                    self.journal.write("INFO", "apps", line)
                return
            result = adb.launch(pkg)
            self.log(result.text or result.stderr or f"launch {pkg}")

        self._work(f"Запуск {pkg}", go)

    def disable_selected(self) -> None:
        selection = self.pkg_list.curselection()
        if not selection:
            return
        pkg = package_from_row(self.pkg_list.get(selection[0]))

        def go() -> None:
            from hub.overlay import disable_user_package

            adb = self._need_adb()
            if not adb or not self._hu_ready(adb):
                raise AdbError("Сначала нажмите «Подключить».")

            def progress(message: str, percent: int) -> None:
                self._show_progress(message, percent)

            for line in disable_user_package(adb, pkg, progress=progress):
                self.journal.write("INFO", "apps", line)
            self.refresh_packages()

        self._work(f"Удаление {pkg}", go)

    def take_screenshot(self) -> None:
        def go() -> None:
            adb = self._need_adb()
            if not adb or not self._hu_ready(adb):
                raise AdbError("Сначала нажмите «Подключить». Без ГУ снимок не сделаю.")
            dest = capture_screenshot(adb)
            self.log(f"скриншот {dest}")
            self._ui(lambda p=dest: self.last_capture.set(f"Последний файл: {p}"))
            self._ui(lambda: self._show_progress(f"Скриншот: {dest.name}", 100))

        self._work("Скриншот", go)

    def start_record(self, seconds: int) -> None:
        if self.recorder is not None and self.recorder.running:
            self.log("запись уже идёт — сначала «Стоп»")
            return

        def go() -> None:
            adb = self._need_adb()
            if not adb or not self._hu_ready(adb):
                raise AdbError("Сначала нажмите «Подключить». Без ГУ запись не начну.")
            rec = Recorder(adb)
            dest = rec.start(seconds)
            self.recorder = rec
            kind = "кадры GIF" if rec.mode == "frames" else "MP4"
            self._ui(lambda: self.record_status.set(f"Идёт запись 0 с / {seconds} с ({kind})"))
            self._ui(lambda p=dest: self.last_capture.set(f"Пишу: {p.name}"))
            self.log(f"съёмка v{CAPTURE_VERSION} → {dest.name} ({kind})")

        self._work(f"Старт записи {seconds} с", go)

    def stop_record(self) -> None:
        rec = self.recorder
        if rec is None or self._stopping_record:
            return
        self._stopping_record = True

        def go() -> None:
            try:
                dest = rec.stop()
                self.recorder = None
                self.log(f"видео {dest}")
                self._ui(lambda: self.record_status.set("Запись не идёт"))
                self._ui(lambda p=dest: self.last_capture.set(f"Последний файл: {p}"))
                self._ui(
                    lambda p=dest: messagebox.showinfo("Видео с ГУ", f"Сохранено:\n{p}")
                )
            finally:
                self._stopping_record = False
                if self.recorder is rec:
                    self.recorder = None

        self._work("Стоп записи", go)

    def open_captures_folder(self) -> None:
        folder = captures_dir()
        self.journal.action("открыть captures", str(folder))
        self._open_path(folder)

    def _open_path(self, path: Path) -> None:
        try:
            if os.name == "nt":
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                subprocess.run(["xdg-open", str(path)], check=False)
        except Exception as exc:  # noqa: BLE001
            self.journal.error("open-path", exc)

    def _tick_record(self) -> None:
        try:
            if not self.root.winfo_exists():
                return
        except tk.TclError:
            return
        rec = self.recorder
        if rec is not None:
            if rec.running:
                self.record_status.set(f"Идёт запись {rec.elapsed()} с / {rec.limit} с")
            elif not self._stopping_record and not self.busy:
                self.stop_record()
        try:
            self.root.after(500, self._tick_record)
        except tk.TclError:
            return

    def _on_close(self) -> None:
        rec = self.recorder
        self.recorder = None
        if rec is not None:
            try:
                rec.stop(flush_wait=0.3)
            except Exception as exc:  # noqa: BLE001
                self.journal.error("record-close", exc)
        self.root.destroy()

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
