from __future__ import annotations

import os
import subprocess
import sys
import threading
import webbrowser
import tkinter as tk
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from .core import DEFAULT_BLUSH_LABEL, DEFAULT_EXPRESSION_LABEL, Project, ProjectError, detect_cpu_threads
from .pbd_converter import (
    PbdConfigError,
    ensure_pbd_config_folder,
    has_pbd_input,
    install_pbd_dlls_from_plugin_folder,
    missing_pbd_dll_files,
)

APP_TITLE = (
    "オトメ世界の歩き方 立绘合成器 Ver1.2 （ 温馨提示：JSON/PBD为身体和表情的空间坐标文件，"
    "SINFO为衣服与表情对应文件，PNG/TLG为预览与合成用的图片文件"
    "————该项目由 ユイ可愛ね 制作，GPT4.5 编写 ，开源于Github，严止任何人倒卖谋利！！！）"
)

THANKS_TEXT = """感谢名单

1. PBD 文件的处理：
   参考了zhaomaoniu大佬（https://github.com/zhaomaoniu）的代码，非常感谢，曾一度以为没办法转换呢，幸好有大佬的仓库！
   PBDConverter：https://github.com/zhaomaoniu/PBDConverter

2. TLG 文件的处理：
   参考了 rr- 大佬（https://github.com/rr-）的代码，使用批处理脚本，真快！不用手动复制了！
   tlg2png：https://github.com/vn-tools/tlg2png

目前支持的游戏：
   
   1.オトメ世界の歩き
   2.何度目かのはじめまして
"""

THANKS_LINKS = (
    ("zhaomaoniu", "https://github.com/zhaomaoniu"),
    ("PBDConverter", "https://github.com/zhaomaoniu/PBDConverter"),
    ("rr-", "https://github.com/rr-"),
    ("tlg2png", "https://github.com/vn-tools/tlg2png"),
)


def _resource_path(*parts: str) -> Path:
    if getattr(sys, "_MEIPASS", None):
        return Path(sys._MEIPASS).joinpath(*parts)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent.joinpath(*parts)


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1600x900")
        self.resizable(False, False)

        self.project: Project | None = None
        self.preview_photo = None
        self.preview_after_id = None
        self.canvas_image_id = None
        self.window_icon_photo = None

        self.cpu_threads = detect_cpu_threads()
        # 加载项目时默认使用“CPU 线程数的 50% + 2”，并且不超过本机 CPU 逻辑线程数。
        self.default_load_threads = min(self.cpu_threads, max(1, self.cpu_threads // 2 + 2))
        self.executor = ThreadPoolExecutor(max_workers=max(4, self.cpu_threads))
        self.load_future: Future | None = None
        self.preview_future: Future | None = None
        self.preview_token = 0

        self.json_dir_var = tk.StringVar()
        self.sinfo_dir_var = tk.StringVar()
        self.png_var = tk.StringVar()

        self.pose_var = tk.StringVar()
        self.body_var = tk.StringVar()
        self.expr_var = tk.StringVar()
        self.blush_var = tk.StringVar()
        self.include_no_expression_var = tk.BooleanVar(value=False)
        self.open_folder_after_export_var = tk.BooleanVar(value=True)
        self.export_workers_var = tk.StringVar(value=str(self.cpu_threads))
        self.load_workers_var = tk.StringVar(value=str(self.default_load_threads))
        self.batch_progress_var = tk.DoubleVar(value=0.0)
        self.batch_progress_text_var = tk.StringVar(value="0%")
        self.load_progress_var = tk.DoubleVar(value=0.0)
        self.load_progress_text_var = tk.StringVar(value="0%")
        self.status_var = tk.StringVar(value="请选择 JSON/PBD 目录、SINFO 目录和 PNG/TLG 目录后加载。")

        self.pose_value_to_stem: dict[str, str] = {}
        self._batch_progress = {"done": 0, "total": 0, "active": False}
        self._batch_progress_lock = threading.Lock()
        self._load_progress = {"done": 0, "total": 0, "active": False, "message": ""}
        self._load_progress_lock = threading.Lock()
        self._action_buttons: list[ttk.Button] = []

        try:
            ensure_pbd_config_folder()
        except Exception:
            pass

        self._build_ui()
        self._setup_window_icon()
        self._center_window(1600, 900)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _center_window(self, width: int, height: int) -> None:
        self.update_idletasks()
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        x = max((screen_w - width) // 2, 0)
        y = max((screen_h - height) // 2, 0)
        self.geometry(f"{width}x{height}+{x}+{y}")

    def _setup_window_icon(self) -> None:
        ico_path = _resource_path("assets", "app_icon.ico")
        png_path = _resource_path("assets", "app_icon.png")
        try:
            if ico_path.exists():
                self.iconbitmap(default=str(ico_path))
        except Exception:
            pass
        try:
            if png_path.exists():
                icon_img = Image.open(png_path).convert("RGBA")
                icon_img.thumbnail((256, 256), Image.LANCZOS)
                self.window_icon_photo = ImageTk.PhotoImage(icon_img)
                self.iconphoto(True, self.window_icon_photo)
        except Exception:
            pass

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)
        root.columnconfigure(0, weight=0, minsize=540)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(0, weight=1)

        left = ttk.Frame(root)
        left.grid(row=0, column=0, sticky="nsew")
        right = ttk.LabelFrame(root, text="预览")
        right.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(0, weight=1)

        input_box = ttk.LabelFrame(left, text="输入目录")
        input_box.pack(fill="x")
        self._row_dir_picker(input_box, "JSON/PBD目录", self.json_dir_var, self.pick_json_dir)
        self._row_dir_picker(input_box, "SINFO 目录", self.sinfo_dir_var, self.pick_sinfo_dir)
        self._row_dir_picker(input_box, "PNG/TLG 目录", self.png_var, self.pick_png_dir)

        btns = ttk.Frame(input_box)
        btns.pack(fill="x", padx=8, pady=(4, 4))
        self._add_action_button(btns, "加载项目", self.load_project).pack(side="left")
        self._add_action_button(btns, "分析规律", self.show_analysis).pack(side="left", padx=6)
        self._add_action_button(btns, "导出当前 PNG", self.export_current).pack(side="left")
        self._add_action_button(btns, "导出当前姿势全部组合", self.export_scene_all).pack(side="left", padx=6)
        self._add_action_button(btns, "本项目引用", self.show_thanks).pack(side="left")

        load_progress_row = ttk.Frame(input_box)
        load_progress_row.pack(fill="x", padx=8, pady=(0, 6))
        load_progress_row.columnconfigure(1, weight=1)
        ttk.Label(load_progress_row, text="加载进度").grid(row=0, column=0, sticky="w", padx=(0, 8))
        self.load_progressbar = ttk.Progressbar(
            load_progress_row,
            orient="horizontal",
            mode="determinate",
            maximum=100,
            variable=self.load_progress_var,
        )
        self.load_progressbar.grid(row=0, column=1, sticky="ew")
        ttk.Label(load_progress_row, textvariable=self.load_progress_text_var, width=8).grid(row=0, column=2, sticky="e", padx=(8, 0))

        export_opts = ttk.Frame(input_box)
        export_opts.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Checkbutton(
            export_opts,
            text='批量导出时包含“无表情”组合',
            variable=self.include_no_expression_var,
            onvalue=True,
            offvalue=False,
        ).grid(row=0, column=0, sticky="w")
        ttk.Checkbutton(
            export_opts,
            text='导出完成后自动打开文件夹',
            variable=self.open_folder_after_export_var,
            onvalue=True,
            offvalue=False,
        ).grid(row=1, column=0, sticky="w", pady=(4, 0))

        thread_box = ttk.Frame(export_opts)
        thread_box.grid(row=0, column=1, rowspan=2, sticky="e", padx=(20, 0))

        export_thread_row = ttk.Frame(thread_box)
        export_thread_row.pack(fill="x", anchor="e")
        ttk.Label(export_thread_row, text="导出时使用的CPU线程数").pack(side="left")
        worker_values = sorted({1, 2, 4, 6, 8, 12, 16, self.cpu_threads})
        self.export_workers_combo = ttk.Combobox(
            export_thread_row,
            textvariable=self.export_workers_var,
            state="readonly",
            width=8,
            values=[str(v) for v in worker_values],
        )
        self.export_workers_combo.pack(side="left", padx=(6, 0))

        load_thread_row = ttk.Frame(thread_box)
        load_thread_row.pack(fill="x", anchor="e", pady=(6, 0))
        ttk.Label(load_thread_row, text="加载项目时使用的CPU线程数").pack(side="left")
        load_worker_values = list(range(1, self.cpu_threads + 1))
        self.load_workers_combo = ttk.Combobox(
            load_thread_row,
            textvariable=self.load_workers_var,
            state="readonly",
            width=8,
            values=[str(v) for v in load_worker_values],
        )
        self.load_workers_combo.pack(side="left", padx=(6, 0))

        ttk.Label(
            export_opts,
            text="批量导出及导入的是PBD和TLG文件，软件卡顿是正常的，请耐心等待！",
            foreground="#666666",
        ).grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))

        progress_row = ttk.Frame(export_opts)
        progress_row.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        progress_row.columnconfigure(0, weight=1)
        self.batch_progressbar = ttk.Progressbar(
            progress_row,
            orient="horizontal",
            mode="determinate",
            maximum=100,
            variable=self.batch_progress_var,
        )
        self.batch_progressbar.grid(row=0, column=0, sticky="ew")
        ttk.Label(progress_row, textvariable=self.batch_progress_text_var, width=8).grid(row=0, column=1, sticky="e", padx=(8, 0))

        options = ttk.LabelFrame(left, text="组合选项")
        options.pack(fill="x", pady=(10, 0))
        self.pose_combo = self._stacked_combo(options, "姿势及其图片分辨率", self.pose_var, self.on_pose_changed)
        self.body_combo = self._stacked_combo(options, "身体服装", self.body_var, self.schedule_preview)
        self.expr_combo = self._stacked_combo(options, "表情", self.expr_var, self.schedule_preview)
        self.blush_combo = self._stacked_combo(options, "红晕", self.blush_var, self.schedule_preview)

        info_box = ttk.LabelFrame(left, text="当前信息")
        info_box.pack(fill="x", pady=(10, 0))
        self.info_text = tk.Text(info_box, height=12, width=64)
        self.info_text.pack(fill="x", expand=False)

        match_box = ttk.LabelFrame(left, text="当前匹配到的图层")
        match_box.pack(fill="both", expand=True, pady=(10, 0))
        self.match_text = tk.Text(match_box, height=16, width=64)
        self.match_text.pack(fill="both", expand=True)

        ttk.Label(left, textvariable=self.status_var, wraplength=520, justify="left").pack(fill="x", pady=(8, 0))

        self.preview_canvas = tk.Canvas(right, bg="#d9d9d9", highlightthickness=0)
        self.preview_canvas.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        self.preview_canvas.bind("<Configure>", self._on_canvas_configure)

    def _add_action_button(self, parent, text: str, cmd):
        btn = ttk.Button(parent, text=text, command=cmd)
        self._action_buttons.append(btn)
        return btn

    def _set_busy(self, busy: bool, message: str | None = None) -> None:
        state = "disabled" if busy else "normal"
        for btn in self._action_buttons:
            try:
                btn.configure(state=state)
            except Exception:
                pass
        try:
            self.configure(cursor="watch" if busy else "")
        except Exception:
            pass
        if message:
            self.status_var.set(message)

    def _row_dir_picker(self, parent, label: str, var: tk.StringVar, cmd) -> None:
        row = ttk.Frame(parent)
        row.pack(fill="x", padx=8, pady=4)
        ttk.Label(row, text=label, width=12).pack(side="left")
        ttk.Entry(row, textvariable=var).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="选择", command=cmd).pack(side="left", padx=(8, 0))

    def _stacked_combo(self, parent, label: str, var: tk.StringVar, cmd) -> ttk.Combobox:
        block = ttk.Frame(parent)
        block.pack(fill="x", padx=8, pady=4)
        ttk.Label(block, text=label).pack(anchor="w")
        combo = ttk.Combobox(block, textvariable=var, state="readonly")
        combo.pack(fill="x", expand=True, pady=(2, 0))
        combo.bind("<<ComboboxSelected>>", lambda _e: cmd())
        return combo

    def pick_json_dir(self) -> None:
        path = filedialog.askdirectory(title="选择 JSON/PBD 目录")
        if path:
            self.json_dir_var.set(path)
            self.sinfo_dir_var.set(path)

    def pick_sinfo_dir(self) -> None:
        path = filedialog.askdirectory(title="选择 SINFO 目录")
        if path:
            self.sinfo_dir_var.set(path)

    def pick_png_dir(self) -> None:
        path = filedialog.askdirectory(title="选择 PNG/TLG 目录")
        if path:
            self.png_var.set(path)

    def _selected_export_workers(self) -> int:
        try:
            return max(1, int(self.export_workers_var.get().strip() or str(self.cpu_threads)))
        except Exception:
            return self.cpu_threads

    def _selected_load_workers(self) -> int:
        try:
            value = int(self.load_workers_var.get().strip() or str(self.default_load_threads))
        except Exception:
            value = self.default_load_threads
        return min(self.cpu_threads, max(1, value))

    def _ensure_pbd_plugin_configured(self, json_input: str) -> bool:
        """If .pbd files are selected and plugin DLLs are missing, ask for the game plugin folder."""
        try:
            contains_pbd = has_pbd_input(json_input)
        except Exception:
            contains_pbd = False
        if not contains_pbd:
            return True

        missing_dlls = missing_pbd_dll_files()
        if not missing_dlls:
            return True

        messagebox.showinfo(
            "配置 PBD 文件解析",
            "检测到 JSON/PBD 目录中包含 .pbd 文件。\n\n"
            "首次解析 PBD 需要游戏 plugin 文件夹里的 json.dll 和 PackinOne.dll。\n"
            "接下来请选择游戏的 plugin 文件夹，软件会自动复制这两个 DLL 到 PBD 文件解析配置目录。",
        )

        while True:
            plugin_dir = filedialog.askdirectory(title="选择游戏 plugin 文件夹（包含 json.dll 和 PackinOne.dll）")
            if not plugin_dir:
                return False
            try:
                cfg = install_pbd_dlls_from_plugin_folder(plugin_dir)
            except PbdConfigError as exc:
                retry = messagebox.askretrycancel(
                    "PBD 配置失败",
                    f"{exc}\n\n是否重新选择游戏 plugin 文件夹？",
                )
                if not retry:
                    return False
                continue
            except Exception as exc:
                retry = messagebox.askretrycancel(
                    "PBD 配置失败",
                    f"复制 DLL 时失败：{exc}\n\n是否重新选择游戏 plugin 文件夹？",
                )
                if not retry:
                    return False
                continue

            messagebox.showinfo(
                "PBD 配置完成",
                "已从游戏 plugin 文件夹复制 json.dll 和 PackinOne.dll。\n\n"
                f"配置目录：{cfg}",
            )
            return True

    def _set_load_progress(self, done: int, total: int, active: bool, message: str = "") -> None:
        with self._load_progress_lock:
            self._load_progress["done"] = max(0, int(done))
            self._load_progress["total"] = max(0, int(total))
            self._load_progress["active"] = bool(active)
            self._load_progress["message"] = message

    def _refresh_load_progress_ui(self) -> None:
        with self._load_progress_lock:
            done = int(self._load_progress.get("done", 0))
            total = int(self._load_progress.get("total", 0))
            active = bool(self._load_progress.get("active", False))
            message = str(self._load_progress.get("message", ""))
        if total > 0:
            pct = max(0.0, min(100.0, done * 100.0 / total))
            self.load_progress_var.set(pct)
            self.load_progress_text_var.set(f"{pct:.1f}%")
            if active and message:
                self.status_var.set(message)
        else:
            self.load_progress_var.set(0.0)
            self.load_progress_text_var.set("0%")
            if active and message:
                self.status_var.set(message)

    def _set_batch_progress(self, done: int, total: int, active: bool | None = None) -> None:
        with self._batch_progress_lock:
            self._batch_progress["done"] = max(0, int(done))
            self._batch_progress["total"] = max(0, int(total))
            if active is not None:
                self._batch_progress["active"] = bool(active)

    def _refresh_batch_progress_ui(self) -> None:
        with self._batch_progress_lock:
            done = int(self._batch_progress.get("done", 0))
            total = int(self._batch_progress.get("total", 0))
            active = bool(self._batch_progress.get("active", False))
        if total > 0:
            pct = max(0.0, min(100.0, done * 100.0 / total))
            self.batch_progress_var.set(pct)
            self.batch_progress_text_var.set(f"{pct:.1f}%")
            if active:
                self.status_var.set(f"正在批量导出当前姿势全部组合…… {done}/{total} ({pct:.1f}%)")
        else:
            self.batch_progress_var.set(0.0)
            self.batch_progress_text_var.set("0%")

    def _open_folder(self, target: str | os.PathLike[str]) -> None:
        path = Path(target)
        folder = path if path.is_dir() else path.parent
        if not folder.exists():
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(str(folder))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(folder)])
            else:
                subprocess.Popen(["xdg-open", str(folder)])
        except Exception:
            pass

    def _current_scene(self):
        if not self.project or not self.project.scenes:
            raise ProjectError("项目未加载。")
        pose_value = self.pose_var.get().strip()
        if pose_value and pose_value in self.pose_value_to_stem:
            return self.project.find_scene(self.pose_value_to_stem[pose_value])
        return self.project.scenes[0]

    def load_project(self) -> None:
        json_dir = self.json_dir_var.get().strip()
        if not json_dir:
            messagebox.showerror("错误", "请先选择 JSON/PBD 目录。")
            return
        png_dir = self.png_var.get().strip()
        if not png_dir:
            messagebox.showerror("错误", "请先选择 PNG/TLG 目录。")
            return
        if self.load_future and not self.load_future.done():
            self.status_var.set("项目仍在加载中，请稍候。")
            return
        if not self._ensure_pbd_plugin_configured(json_dir):
            self.status_var.set("已取消 PBD 文件解析配置。")
            return

        self._set_load_progress(0, 0, True, "正在解析 JSON/PBD / SINFO / PNG/TLG，请稍候……")
        self._refresh_load_progress_ui()
        self._set_busy(True, "正在解析 JSON/PBD / SINFO / PNG/TLG，请稍候……")
        if self.project:
            self.project.close()
            self.project = None
        raw_sinfo_dir = self.sinfo_dir_var.get().strip()
        if raw_sinfo_dir:
            sinfo_dir = raw_sinfo_dir
        else:
            json_input = Path(json_dir).expanduser()
            sinfo_dir = str(json_input.parent if json_input.suffix.lower() in {".json", ".pbd"} else json_input)
            self.sinfo_dir_var.set(sinfo_dir)
        load_workers = self._selected_load_workers()

        def load_and_preload() -> Project:
            pbd_stats = {"done": 0, "total": 0}

            def pbd_progress(done: int, total_count: int) -> None:
                if total_count > 0:
                    pbd_stats["done"] = done
                    pbd_stats["total"] = total_count
                    self._set_load_progress(
                        done,
                        total_count,
                        True,
                        f"正在使用 {load_workers} 个 CPU 并行任务解析 PBD 为 JSON…… {done}/{total_count}",
                    )

            project = Project.from_directories(
                json_dir,
                sinfo_dir,
                png_dir,
                pbd_workers=load_workers,
                pbd_progress_callback=pbd_progress,
            )
            cached, total = project.tlg_cache_status()
            if total <= 0:
                if pbd_stats["total"] > 0:
                    self._set_load_progress(
                        pbd_stats["total"],
                        pbd_stats["total"],
                        False,
                        f"PBD 解析完成：{pbd_stats['done']}/{pbd_stats['total']}；未检测到需要缓存的 TLG 图层。",
                    )
                else:
                    self._set_load_progress(0, 0, False, "未检测到需要缓存的 TLG 图层。")
                return project

            missing = max(total - cached, 0)
            if missing <= 0:
                self._set_load_progress(total, total, False, f"TLG 磁盘缓存全部命中：{total}/{total}，无需重新加载。")
                return project

            self._set_load_progress(
                cached,
                total,
                True,
                f"检测到 {total} 个 TLG 图层，已命中缓存 {cached} 个；正在使用 {load_workers} 个 CPU 并行任务生成剩余缓存…… {cached}/{total}",
            )

            def progress(done: int, total_count: int) -> None:
                self._set_load_progress(
                    done,
                    total_count,
                    True,
                    f"正在使用 {load_workers} 个 CPU 并行任务写入 TLG 磁盘缓存…… {done}/{total_count}",
                )

            cached_count, converted_count, total_count = project.preload_tlg_images(progress, max_workers=load_workers)
            self._set_load_progress(
                total_count,
                total_count,
                False,
                f"TLG 磁盘缓存完成：缓存命中 {cached_count} 个，新生成 {converted_count} 个，共 {total_count} 个。",
            )
            return project

        self.load_future = self.executor.submit(load_and_preload)
        self.after(80, self._poll_load_future)

    def _poll_load_future(self) -> None:
        self._refresh_load_progress_ui()
        future = self.load_future
        if not future:
            return
        if not future.done():
            self.after(80, self._poll_load_future)
            return
        try:
            self.project = future.result()
        except Exception as exc:
            self._set_load_progress(0, 0, False, "")
            self._refresh_load_progress_ui()
            self._set_busy(False)
            messagebox.showerror("加载失败", str(exc))
            return

        self._refresh_load_progress_ui()
        self.pose_value_to_stem = {scene.pose_label: scene.stem for scene in self.project.scenes}
        pose_values = list(self.pose_value_to_stem.keys())
        self.pose_combo["values"] = pose_values
        self.pose_var.set(pose_values[0] if pose_values else "")
        self._refresh_scene_options()
        with self._load_progress_lock:
            total = int(self._load_progress.get("total", 0))
        preload_note = f"，TLG 磁盘缓存 {total} 个" if total > 0 else ""
        self._set_busy(False, f"已加载 {len(self.project.scenes)} 个姿势{preload_note}。")
        self.schedule_preview()

    def _refresh_scene_options(self) -> None:
        scene = self._current_scene()
        body_values = [layer.label for layer in scene.body_layers]
        expr_values = [DEFAULT_EXPRESSION_LABEL] + [layer.name for layer in scene.expression_layers]
        blush_values = [DEFAULT_BLUSH_LABEL] + [layer.name for layer in scene.blush_layers]

        self.body_combo["values"] = body_values
        self.expr_combo["values"] = expr_values
        self.blush_combo["values"] = blush_values

        default_body = next((layer.label for layer in scene.body_layers if layer.layer_id == scene.default_body_id), body_values[0] if body_values else "")
        default_expr = next((layer.name for layer in scene.expression_layers if layer.layer_id == scene.default_expression_id), DEFAULT_EXPRESSION_LABEL)
        default_blush = next((layer.name for layer in scene.blush_layers if layer.layer_id == scene.default_blush_id), DEFAULT_BLUSH_LABEL)

        self.body_var.set(default_body)
        self.expr_var.set(default_expr)
        self.blush_var.set(default_blush)

    def on_pose_changed(self) -> None:
        if not self.project:
            return
        self._refresh_scene_options()
        self.schedule_preview()

    def _current_selection(self):
        scene = self._current_scene()
        return self.project.make_selection(
            scene_stem=scene.stem,
            body_label=self.body_var.get().strip() or None,
            expression_name=self.expr_var.get().strip() or DEFAULT_EXPRESSION_LABEL,
            blush_name=self.blush_var.get().strip() or DEFAULT_BLUSH_LABEL,
        )

    def _on_canvas_configure(self, _event=None) -> None:
        if self.preview_after_id:
            self.after_cancel(self.preview_after_id)
        self.preview_after_id = self.after(80, self.schedule_preview)

    def schedule_preview(self) -> None:
        if not self.project:
            return
        try:
            scene = self._current_scene()
            selection = self._current_selection()
            cw = max(300, self.preview_canvas.winfo_width() - 20)
            ch = max(300, self.preview_canvas.winfo_height() - 20)
        except Exception as exc:
            self.status_var.set(str(exc))
            return

        self.preview_token += 1
        token = self.preview_token
        self.status_var.set("正在生成预览……")
        future = self.executor.submit(self.project.make_preview, selection, (cw, ch))
        self.preview_future = future
        self.after(20, lambda: self._poll_preview_future(future, token, scene))

    def _poll_preview_future(self, future: Future, token: int, scene) -> None:
        if not future.done():
            self.after(20, lambda: self._poll_preview_future(future, token, scene))
            return
        if token != self.preview_token:
            return
        try:
            preview, scale, result = future.result()
        except Exception as exc:
            if token == self.preview_token:
                self.status_var.set(str(exc))
            return
        self._apply_preview(scene, preview, scale, result)

    def _apply_preview(self, scene, preview, scale, result) -> None:
        self.preview_photo = ImageTk.PhotoImage(preview)
        self.preview_canvas.delete("all")
        self.preview_canvas.create_image(
            max(self.preview_canvas.winfo_width() // 2, 1),
            max(self.preview_canvas.winfo_height() // 2, 1),
            image=self.preview_photo,
            anchor="center",
        )

        info_lines = [
            f"姿势及其图片分辨率: {scene.pose_label}",
            f"JSON: {scene.json_path.name}",
            f"SINFO: {scene.sinfo_path.name if scene.sinfo_path else '无'}",
            f"画布: {scene.canvas_width} x {scene.canvas_height}",
            f"身体服装: {self.body_var.get()}",
            f"表情: {self.expr_var.get()}",
            f"红晕: {self.blush_var.get()}",
            f"预览缩放: {scale:.2%}",
            f"匹配图层: {sum(1 for x in result.matched if x.path)} / {len(result.matched)}",
        ]
        self.info_text.delete("1.0", "end")
        self.info_text.insert("1.0", "\n".join(info_lines))

        lines = []
        for item in result.matched:
            if item.path:
                lines.append(f"✓ {item.layer.label} [{item.layer.layer_id}] -> {item.path.name} ({item.status})")
            else:
                lines.append(f"✗ {item.layer.label} [{item.layer.layer_id}] -> {item.status}")
        if result.warnings:
            lines.append("")
            lines.append("警告：")
            lines.extend(f"- {w}" for w in result.warnings)
        self.match_text.delete("1.0", "end")
        self.match_text.insert("1.0", "\n".join(lines))
        self.status_var.set(f"已加载: {scene.pose_label}")

    def export_current(self) -> None:
        if not self.project:
            messagebox.showerror("错误", "请先加载项目。")
            return
        try:
            scene = self._current_scene()
            selection = self._current_selection()
        except Exception as exc:
            messagebox.showerror("错误", str(exc))
            return
        out = filedialog.asksaveasfilename(
            title="导出当前 PNG",
            defaultextension=".png",
            initialfile=f"{scene.stem}_export.png",
            filetypes=[("PNG", "*.png")],
        )
        if not out:
            return
        self._set_busy(True, "正在导出当前 PNG……")
        future = self.executor.submit(self.project.export_current, out, selection)
        self.after(80, lambda: self._poll_export_future(future, out, "single"))

    def export_scene_all(self) -> None:
        if not self.project:
            messagebox.showerror("错误", "请先加载项目。")
            return
        scene = self._current_scene()
        out_dir = filedialog.askdirectory(title="选择导出目录")
        if not out_dir:
            return
        include_no_expression = bool(self.include_no_expression_var.get())
        workers = self._selected_export_workers()
        self._set_batch_progress(0, 0, active=True)
        self._refresh_batch_progress_ui()

        def progress_callback(done: int, total: int) -> None:
            self._set_batch_progress(done, total, active=True)

        self._set_busy(True, f"正在批量导出当前姿势全部组合……（{workers} 线程）")
        future = self.executor.submit(
            self.project.export_scene_all_combinations,
            scene.stem,
            out_dir,
            include_no_expression,
            workers,
            progress_callback,
        )
        self.after(120, lambda: self._poll_export_future(future, out_dir, "batch"))

    def _poll_export_future(self, future: Future, target: str, mode: str) -> None:
        if mode == "batch":
            self._refresh_batch_progress_ui()
        if not future.done():
            self.after(80, lambda: self._poll_export_future(future, target, mode))
            return
        self._set_busy(False)
        try:
            result = future.result()
        except Exception as exc:
            if mode == "batch":
                self._set_batch_progress(0, 0, active=False)
                self._refresh_batch_progress_ui()
            messagebox.showerror("导出失败", str(exc))
            return
        if mode == "single":
            warnings = result
            msg = f"已导出: {target}"
            if warnings:
                msg += "\n\n警告：\n" + "\n".join(warnings)
            messagebox.showinfo("导出完成", msg)
            if self.open_folder_after_export_var.get():
                self._open_folder(target)
        else:
            total = len(result)
            self._set_batch_progress(total, total, active=False)
            self._refresh_batch_progress_ui()
            mode_note = "（已包含无表情）" if self.include_no_expression_var.get() else "（已跳过无表情）"
            thread_note = f"线程数：{self._selected_export_workers()}"
            messagebox.showinfo("导出完成", f"已导出 {len(result)} 张 PNG 到:\n{target}\n{mode_note}\n{thread_note}")
            if self.open_folder_after_export_var.get():
                self._open_folder(target)


    def show_thanks(self) -> None:
        win = tk.Toplevel(self)
        win.title("感谢")
        self.update_idletasks()

        # 感谢窗口固定贴齐主程序窗口左上角，避免由系统自动摆放导致偏移。
        main_x = self.winfo_x()
        main_y = self.winfo_y()
        win.geometry(f"720x360+{main_x}+{main_y}")
        win.resizable(False, False)
        win.transient(self)

        txt = tk.Text(win, wrap="word", height=12, padx=12, pady=10)
        txt.pack(fill="both", expand=True, padx=10, pady=(10, 6))
        txt.insert("1.0", THANKS_TEXT)
        txt.configure(state="disabled")

        link_frame = ttk.Frame(win)
        link_frame.pack(fill="x", padx=10, pady=(0, 6))
        ttk.Label(link_frame, text="友情链接：").pack(side="left")
        for label, url in THANKS_LINKS:
            ttk.Button(
                link_frame,
                text=label,
                command=lambda target=url: webbrowser.open(target),
            ).pack(side="left", padx=(6, 0))

        ttk.Button(win, text="关闭", command=win.destroy).pack(pady=(0, 10))
        win.grab_set()

    def show_analysis(self) -> None:
        if not self.project:
            messagebox.showerror("错误", "请先加载项目。")
            return
        win = tk.Toplevel(self)
        win.title("差分合成规律分析")
        win.geometry("960x720")
        txt = tk.Text(win, wrap="word")
        txt.pack(fill="both", expand=True)
        txt.insert("1.0", self.project.analysis_report())
        txt.configure(state="disabled")

    def _on_close(self) -> None:
        try:
            self.executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
        self.destroy()


def run_app() -> None:
    app = App()
    app.mainloop()


__all__ = ["App", "run_app", "APP_TITLE"]
