# -*- coding: utf-8 -*-
"""
视频转音频 - 一键批量转换工具 (Mac / Windows)
自动识别视频文件（mp4 / mov / mkv / avi ...），默认输出 MP3，可选 WAV 等格式。
界面：CustomTkinter，浅色（薄荷绿，默认）/ 深色（黑色）。
依赖：ffmpeg（打包时通过 imageio-ffmpeg 内置，用户无需另装）
"""
import os
import sys
import shutil
import subprocess
import threading
import queue
import time
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import customtkinter as ctk

APP_NAME = "视频转音频"
VIDEO_EXTS = {
    ".mp4", ".mov", ".m4v", ".mkv", ".avi", ".wmv", ".flv", ".webm", ".ts",
    ".mts", ".m2ts", ".3gp", ".mpg", ".mpeg", ".vob", ".f4v", ".rm", ".rmvb", ".ogv",
}

FORMATS = {
    "MP3": {"ext": ".mp3", "args": ["-c:a", "libmp3lame", "-b:a", "{q}"],
            "qualities": ["320k", "256k", "192k", "128k"], "default_q": "320k"},
    "WAV": {"ext": ".wav", "args": ["-c:a", "pcm_s16le"],
            "qualities": ["16-bit"], "default_q": "16-bit"},
    "M4A": {"ext": ".m4a", "args": ["-c:a", "aac", "-b:a", "{q}"],
            "qualities": ["256k", "192k", "128k"], "default_q": "256k"},
    "FLAC": {"ext": ".flac", "args": ["-c:a", "flac"],
             "qualities": ["无损"], "default_q": "无损"},
}
SAMPLE_RATES = ["原始", "44100", "48000"]

# ---------------- 配色 ----------------
KEYS = ["bg", "card", "line", "text", "sub", "accent", "accent_h", "on_accent",
        "soft", "soft_h", "row_alt", "select", "err", "run"]
LIGHT = dict(zip(KEYS, [  # 浅色：薄荷绿
    "#F3FAF7", "#FFFFFF", "#E2F1EA", "#1D2A26", "#7C9189", "#19AE87", "#139673",
    "#FFFFFF", "#E8F5EF", "#DAF0E6", "#F8FCFA", "#D3F3E6", "#D64545", "#1F8FD6"]))
DARK = dict(zip(KEYS, [   # 深色：黑色
    "#0A0A0A", "#141414", "#1F1F1F", "#EDEDED", "#7D7D7D", "#19AE87", "#20C094",
    "#FFFFFF", "#1C1C1C", "#272727", "#171717", "#15382D", "#FF6B6B", "#5AB8FF"]))
THEMES = {"浅色": (LIGHT, "Light"), "深色": (DARK, "Dark")}


def font_family():
    if sys.platform == "darwin":
        return "PingFang SC"
    if sys.platform == "win32":
        return "Microsoft YaHei UI"
    return "Noto Sans CJK SC"


# ---------------- 转换核心 ----------------
def find_ffmpeg():
    try:
        import imageio_ffmpeg
        path = imageio_ffmpeg.get_ffmpeg_exe()
        if path and os.path.exists(path):
            return path
    except Exception:
        pass
    for p in (shutil.which("ffmpeg"), "/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg"):
        if p and os.path.exists(p):
            return p
    return None


def is_video(path):
    return os.path.splitext(path)[1].lower() in VIDEO_EXTS


def scan(paths):
    out = []
    for p in paths:
        if os.path.isdir(p):
            for root, _, files in os.walk(p):
                for f in sorted(files):
                    if not f.startswith(".") and is_video(f):
                        out.append(os.path.join(root, f))
        elif os.path.isfile(p) and is_video(p):
            out.append(p)
    return out


def unique_path(path):
    base, ext = os.path.splitext(path)
    i = 1
    while os.path.exists(path):
        path = f"{base} ({i}){ext}"
        i += 1
    return path


def build_cmd(ffmpeg, src, dst, fmt, quality, rate):
    spec = FORMATS[fmt]
    # 绝对路径：防止以 "-" 开头的文件名被当成参数、"http:" 等前缀被当成协议
    src, dst = os.path.abspath(src), os.path.abspath(dst)
    # 只允许读本地文件：伪装成视频的播放列表等无法让 ffmpeg 访问网络
    cmd = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-protocol_whitelist", "file",
           "-i", src, "-vn", "-sn", "-dn", "-map", "0:a:0?"]
    cmd += [a.replace("{q}", quality) for a in spec["args"]]
    if rate != "原始":
        cmd += ["-ar", rate]
    cmd.append(dst)
    return cmd


def convert_one(ffmpeg, src, dst, fmt, quality, rate, procs, lock):
    kwargs = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    tmp = dst + ".part" + FORMATS[fmt]["ext"]
    p = subprocess.Popen(build_cmd(ffmpeg, src, tmp, fmt, quality, rate),
                         stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, **kwargs)
    with lock:
        procs.add(p)
    _, err = p.communicate()
    with lock:
        procs.discard(p)
    if p.returncode == 0 and os.path.exists(tmp) and os.path.getsize(tmp) > 0:
        os.replace(tmp, dst)
        return True, ""
    if os.path.exists(tmp):
        try:
            os.remove(tmp)
        except OSError:
            pass
    text = err.decode("utf-8", "ignore")
    msg = text.strip().splitlines()
    tail = msg[-1] if msg else "未知错误"
    if "Stream #" in text and "Audio:" not in text:
        tail = "该视频没有音轨"
    elif "No such file" in text:
        tail = "文件不存在"
    elif "Invalid data found" in text:
        tail = "文件损坏或不是有效视频"
    return False, tail


_cpu_prev = None


def cpu_busy():
    """返回电脑 CPU 繁忙程度 0~1（取不到时返回 None）。"""
    global _cpu_prev
    try:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes
            idle, kern, user = wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME()
            ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern),
                                                  ctypes.byref(user))
            v = lambda ft: (ft.dwHighDateTime << 32) | ft.dwLowDateTime
            cur = (v(idle), v(kern) + v(user))  # kernel 时间已包含 idle
            prev, _cpu_prev = _cpu_prev, cur
            if not prev or cur[1] == prev[1]:
                return None
            return 1 - (cur[0] - prev[0]) / (cur[1] - prev[1])
        if sys.platform == "darwin":
            import ctypes
            lib = ctypes.CDLL("/usr/lib/libSystem.dylib")
            lib.mach_host_self.restype = ctypes.c_uint
            info = (ctypes.c_uint * 4)()  # user, system, idle, nice（时钟滴答）
            cnt = ctypes.c_uint(4)
            if lib.host_statistics(lib.mach_host_self(), 3, info, ctypes.byref(cnt)) != 0:
                return None
            cur = (info[2], info[0] + info[1] + info[2] + info[3])
            prev, _cpu_prev = _cpu_prev, cur
            if not prev or cur[1] == prev[1]:
                return None
            return 1 - (cur[0] - prev[0]) / (cur[1] - prev[1])
        return os.getloadavg()[0] / (os.cpu_count() or 1)
    except Exception:
        return None


# ---------------- 界面 ----------------
try:
    from tkinterdnd2 import TkinterDnD, DND_FILES

    class Root(ctk.CTk, TkinterDnD.DnDWrapper):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            try:
                self.TkdndVersion = TkinterDnD._require(self)
                self.dnd_ok = True
            except Exception:
                self.dnd_ok = False
except Exception:
    DND_FILES = None

    class Root(ctk.CTk):
        dnd_ok = False


class App:
    PADX = 28

    def __init__(self, root, initial=()):
        self.root = root
        self.ffmpeg = find_ffmpeg()
        self.files, self.items = [], {}
        self.msgs = queue.Queue()
        self.running = False
        self.stop_flag = threading.Event()
        self.procs, self.lock = set(), threading.Lock()
        self.done_count = 0
        self.theme = "浅色"
        self.P = LIGHT
        self.themed = []   # (控件, {选项: 配色键})
        self.segs = []     # 分段按钮（选中项白字）

        ff = font_family()
        self.f_title = ctk.CTkFont(ff, 18, "bold")
        self.f_body = ctk.CTkFont(ff, 13)
        self.f_sub = ctk.CTkFont(ff, 12)
        self.f_small = ctk.CTkFont(ff, 11)
        self.f_btn = ctk.CTkFont(ff, 13, "bold")

        root.title(APP_NAME)
        try:  # 窗口 / 任务栏图标
            base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
            self._icon = tk.PhotoImage(file=os.path.join(base, "assets", "icon.png"))
            root.iconphoto(True, self._icon)
        except Exception:
            pass
        root.geometry("900x620")
        root.minsize(780, 540)
        self._build()
        self.apply_theme("浅色")
        self._enable_drop()
        if sys.platform == "darwin":  # 拖到 Dock 图标 / 「打开方式」
            try:
                root.createcommand("::tk::mac::OpenDocument", lambda *a: self.add_paths(a))
            except Exception:
                pass
        root.after(80, self._poll)
        if initial:
            root.after(300, lambda: self.add_paths(initial))
        if not self.ffmpeg:
            messagebox.showerror(APP_NAME, "未找到 ffmpeg，无法转换。")

    # ---------- 主题 ----------
    def w(self, cls, parent, **kw):
        """创建控件；"@键" 形式的颜色会登记，切换主题时自动更新。"""
        refs = {k: v[1:] for k, v in kw.items() if isinstance(v, str) and v.startswith("@")}
        for k, key in refs.items():
            kw[k] = self.P[key]
        widget = cls(parent, **kw)
        if refs:
            self.themed.append((widget, refs))
        return widget

    def apply_theme(self, name):
        self.theme = name
        self.P, mode = THEMES[name]
        ctk.set_appearance_mode(mode)
        self.root.configure(fg_color=self.P["bg"])
        for widget, refs in self.themed:
            try:
                widget.configure(**{k: self.P[key] for k, key in refs.items()})
            except Exception:
                pass
        for s in self.segs:
            self._paint_seg(s)
        self.theme_btn.configure(text="☾  深色" if name == "浅色" else "☀  浅色")
        self._apply_tree_style()

    def toggle_theme(self):
        self.apply_theme("深色" if self.theme == "浅色" else "浅色")

    # ---------- 小部件 ----------
    def ghost(self, parent, text, cmd, width=0, **kw):
        """轻量文字按钮：无底色，悬停才显示浅色底。"""
        return self.w(ctk.CTkButton, parent, text=text, command=cmd, font=self.f_sub,
                      width=width, height=30, corner_radius=8, fg_color="transparent",
                      hover_color="@soft", text_color="@text",
                      text_color_disabled="@sub", **kw)

    def primary(self, parent, text, cmd, width=120, height=32, font=None):
        return self.w(ctk.CTkButton, parent, text=text, command=cmd, font=font or self.f_btn,
                      width=width, height=height, corner_radius=height // 2,
                      fg_color="@accent", hover_color="@accent_h", text_color="@on_accent",
                      text_color_disabled="@on_accent")

    def text(self, parent, text="", sub=False, small=False, **kw):
        f = self.f_small if small else (self.f_sub if sub else self.f_body)
        return self.w(ctk.CTkLabel, parent, text=text, font=f,
                      text_color="@sub" if (sub or small) else "@text", **kw)

    def option(self, parent, var, values, width=84):
        return self.w(ctk.CTkOptionMenu, parent, variable=var, values=values, width=width,
                      height=28, corner_radius=8, font=self.f_sub, dropdown_font=self.f_sub,
                      fg_color="@soft", button_color="@soft", button_hover_color="@soft_h",
                      text_color="@text", dropdown_fg_color="@card",
                      dropdown_hover_color="@soft", dropdown_text_color="@text")

    def seg(self, parent, values, var, cmd=None):
        def on_change(v):
            self._paint_seg(s)
            if cmd:
                cmd(v)
        s = self.w(ctk.CTkSegmentedButton, parent, values=values, variable=var,
                   command=on_change, font=self.f_sub, height=28, corner_radius=8,
                   border_width=2, fg_color="@soft", selected_color="@accent",
                   selected_hover_color="@accent_h", unselected_color="@soft",
                   unselected_hover_color="@soft_h")
        self.segs.append(s)
        self._paint_seg(s)
        return s

    def _paint_seg(self, s):
        """选中项是实色底 → 白字；未选中项 → 正文色。"""
        cur = s.get()
        for v, b in s._buttons_dict.items():
            b.configure(text_color=self.P["on_accent"] if v == cur else self.P["text"])

    # ---------- 布局 ----------
    def _build(self):
        r, px = self.root, self.PADX
        r.grid_columnconfigure(0, weight=1)
        r.grid_rowconfigure(2, weight=1)

        # 顶部
        head = ctk.CTkFrame(r, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=px, pady=(22, 0))
        dot = self.w(ctk.CTkLabel, head, text="♪", width=28, height=28, corner_radius=8,
                     fg_color="@accent", text_color="@on_accent", font=self.f_btn)
        dot.pack(side="left")
        self.w(ctk.CTkLabel, head, text=APP_NAME, font=self.f_title,
               text_color="@text").pack(side="left", padx=(10, 10))
        self.text(head, "MP4 / MOV 等视频批量转 MP3、WAV", sub=True).pack(side="left", pady=(3, 0))
        self.theme_btn = self.ghost(head, "☾  深色", self.toggle_theme, width=72)
        self.theme_btn.pack(side="right")

        # 工具栏
        bar = ctk.CTkFrame(r, fg_color="transparent")
        bar.grid(row=1, column=0, sticky="ew", padx=px, pady=(18, 10))
        self.primary(bar, "＋ 添加视频", self.add_files, width=112).pack(side="left")
        self.ghost(bar, "添加文件夹", self.add_folder).pack(side="left", padx=(10, 0))
        self.ghost(bar, "移除选中", self.remove_selected).pack(side="left", padx=(2, 0))
        self.ghost(bar, "清空", self.clear).pack(side="left", padx=(2, 0))
        self.count_var = tk.StringVar(value="")
        self.w(ctk.CTkLabel, bar, textvariable=self.count_var, font=self.f_sub,
               text_color="@sub").pack(side="right")

        # 列表
        lst = self.w(ctk.CTkFrame, r, fg_color="@card", corner_radius=12,
                     border_width=1, border_color="@line")
        lst.grid(row=2, column=0, sticky="nsew", padx=px)
        lst.grid_columnconfigure(0, weight=1)
        lst.grid_rowconfigure(0, weight=1)
        self.style = ttk.Style(r)
        self.style.theme_use("clam")
        self.tree = ttk.Treeview(lst, columns=("name", "type", "status"), show="headings",
                                 selectmode="extended", style="M.Treeview")
        for col, txt, wd, anc in (("name", "文件名", 460, "w"), ("type", "格式", 70, "center"),
                                  ("status", "状态", 220, "w")):
            self.tree.heading(col, text=txt, anchor=anc)
            self.tree.column(col, width=wd, anchor=anc, stretch=(col != "type"))
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(12, 0), pady=8)
        sb = self.w(ctk.CTkScrollbar, lst, command=self.tree.yview, width=10,
                    button_color="@line", button_hover_color="@sub", fg_color="transparent")
        sb.grid(row=0, column=1, sticky="ns", padx=(2, 6), pady=10)
        self.tree.configure(yscrollcommand=sb.set)

        self.empty = self.w(ctk.CTkFrame, lst, fg_color="@card", corner_radius=12)
        self._show_empty()
        box = ctk.CTkFrame(self.empty, fg_color="transparent")
        box.place(relx=0.5, rely=0.5, anchor="center")
        self.w(ctk.CTkLabel, box, text="↓", width=48, height=48, corner_radius=24,
               fg_color="@soft", text_color="@accent",
               font=ctk.CTkFont(font_family(), 22, "bold")).pack()
        self.text(box, "拖入视频或文件夹").pack(pady=(12, 2))
        self.text(box, "自动识别 MP4 · MOV · MKV · AVI · WMV · FLV · WEBM", small=True).pack()
        for wdg in (self.empty, box):
            wdg.bind("<Button-1>", lambda e: self.add_files())

        # 设置（无边框，平铺两行）
        st = ctk.CTkFrame(r, fg_color="transparent")
        st.grid(row=3, column=0, sticky="ew", padx=px, pady=(16, 0))
        st.grid_columnconfigure(8, weight=1)
        g = dict(pady=4, sticky="w")
        self.text(st, "格式", sub=True).grid(row=0, column=0, padx=(0, 10), **g)
        self.fmt_var = tk.StringVar(value="MP3")
        self.seg(st, list(FORMATS), self.fmt_var, self._on_fmt).grid(row=0, column=1, **g)
        self.text(st, "音质", sub=True).grid(row=0, column=2, padx=(24, 8), **g)
        self.q_var = tk.StringVar(value=FORMATS["MP3"]["default_q"])
        self.q_menu = self.option(st, self.q_var, FORMATS["MP3"]["qualities"])
        self.q_menu.grid(row=0, column=3, **g)
        self.text(st, "采样率", sub=True).grid(row=0, column=4, padx=(24, 8), **g)
        self.rate_var = tk.StringVar(value="原始")
        self.option(st, self.rate_var, SAMPLE_RATES).grid(row=0, column=5, **g)

        self.text(st, "保存", sub=True).grid(row=1, column=0, padx=(0, 10), **g)
        self.out_mode = tk.StringVar(value="原视频旁边")
        self.seg(st, ["原视频旁边", "指定文件夹"], self.out_mode, self._on_out).grid(
            row=1, column=1, **g)
        self.out_dir = tk.StringVar(value="")
        self.out_lbl = self.w(ctk.CTkLabel, st, textvariable=self.out_dir, font=self.f_small,
                              text_color="@sub", anchor="w")
        self.out_lbl.grid(row=1, column=2, columnspan=5, padx=(24, 0), sticky="ew", pady=4)
        self.out_btn = self.ghost(st, "更改…", self.pick_out)
        self.overwrite = tk.BooleanVar(value=False)
        self.w(ctk.CTkCheckBox, st, text="覆盖同名文件", variable=self.overwrite,
               font=self.f_small, text_color="@sub", fg_color="@accent",
               hover_color="@accent_h", border_color="@sub", checkmark_color="@on_accent",
               checkbox_width=16, checkbox_height=16, border_width=1,
               corner_radius=4).grid(row=1, column=8, sticky="e", pady=4)

        # 底部
        foot = ctk.CTkFrame(r, fg_color="transparent")
        foot.grid(row=4, column=0, sticky="ew", padx=px, pady=(18, 22))
        foot.grid_columnconfigure(0, weight=1)
        self.status_var = tk.StringVar(value="就绪")
        self.w(ctk.CTkLabel, foot, textvariable=self.status_var, font=self.f_sub,
               text_color="@sub", anchor="w", height=18).grid(row=0, column=0, sticky="ew")
        self.prog = self.w(ctk.CTkProgressBar, foot, height=4, corner_radius=2,
                           fg_color="@line", progress_color="@accent")
        self.prog.set(0)
        self.prog.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        self.open_btn = self.w(ctk.CTkButton, foot, text="打开文件夹", command=self.open_output,
                               font=self.f_sub, width=96, height=30, corner_radius=15,
                               fg_color="transparent", hover_color="@soft",
                               text_color="@accent", border_width=1, border_color="@accent")
        self.stop_btn = self.ghost(foot, "停止", self.stop, width=56, state="disabled")
        self.stop_btn.grid(row=0, column=2, rowspan=2, padx=(10, 6))
        self.start_btn = self.primary(foot, "开始转换", self.start, width=132, height=38)
        self.start_btn.grid(row=0, column=3, rowspan=2)
        self.outputs = []
        self._refresh_count()

    def _show_empty(self):
        self.empty.place(relx=0.5, rely=0.5, anchor="center", relwidth=0.99, relheight=0.97)

    def _apply_tree_style(self):
        g = self.P.get
        ff = font_family()
        s = self.style
        s.configure("M.Treeview", background=g("card"), fieldbackground=g("card"),
                    foreground=g("text"), rowheight=30, borderwidth=0, relief="flat",
                    font=(ff, -13))
        s.map("M.Treeview", background=[("selected", g("select"))],
              foreground=[("selected", g("text"))])
        s.configure("M.Treeview.Heading", background=g("card"), foreground=g("sub"),
                    font=(ff, -11), relief="flat", borderwidth=0, padding=(4, 6))
        s.map("M.Treeview.Heading", background=[("active", g("card"))])
        s.layout("M.Treeview", [("M.Treeview.treearea", {"sticky": "nswe"})])
        self.tree.tag_configure("odd", background=g("row_alt"))
        self.tree.tag_configure("even", background=g("card"))
        self.tree.tag_configure("ok", foreground=g("text"))
        self.tree.tag_configure("err", foreground=g("err"))
        self.tree.tag_configure("run", foreground=g("run"))

    def _enable_drop(self):
        if not getattr(self.root, "dnd_ok", False) or DND_FILES is None:
            return
        for wdg in (self.root, self.tree):
            try:
                wdg.drop_target_register(DND_FILES)
                wdg.dnd_bind("<<Drop>>",
                             lambda e: self.add_paths(self.root.tk.splitlist(e.data)))
            except Exception:
                pass

    def _on_fmt(self, _=None):
        spec = FORMATS[self.fmt_var.get()]
        self.q_menu.configure(values=spec["qualities"])
        self.q_var.set(spec["default_q"])

    def _on_out(self, _=None):
        if self.out_mode.get() == "指定文件夹":
            self.out_btn.grid(row=1, column=7, sticky="w", pady=4)
            if not self.out_dir.get():
                self.pick_out()
            if not self.out_dir.get():  # 取消选择 → 回到原视频旁边
                self.out_mode.set("原视频旁边")
                self._on_out()
                return
        else:
            self.out_btn.grid_remove()
            self.out_dir.set("")
        for s in self.segs:
            self._paint_seg(s)

    def pick_out(self):
        d = filedialog.askdirectory(title="选择音频保存文件夹")
        if d:
            self.out_dir.set(d)

    # ---------- 列表 ----------
    def add_files(self):
        if self.running:
            return
        pat = " ".join("*" + e for e in sorted(VIDEO_EXTS))
        fs = filedialog.askopenfilenames(title="选择视频",
                                         filetypes=[("视频文件", pat), ("所有文件", "*.*")])
        self.add_paths(fs)

    def add_folder(self):
        d = filedialog.askdirectory(title="选择包含视频的文件夹（含子文件夹）")
        if d:
            self.add_paths([d])

    def _row_tags(self, idx, extra=None):
        t = ["odd" if idx % 2 else "even"]
        if extra:
            t.append(extra)
        return tuple(t)

    def add_paths(self, paths):
        if self.running or not paths:
            return
        found = scan(paths)
        for f in found:
            f = os.path.abspath(f)
            if f in self.items:
                continue
            ext = os.path.splitext(f)[1].lstrip(".").upper()
            iid = self.tree.insert("", "end", values=(os.path.basename(f), ext, "待转换"),
                                   tags=self._row_tags(len(self.files)))
            self.items[f] = iid
            self.files.append(f)
        self._refresh_count()
        if not found:
            messagebox.showinfo(APP_NAME, "没有识别到视频文件。")

    def remove_selected(self):
        if self.running:
            return
        rev = {v: k for k, v in self.items.items()}
        for iid in self.tree.selection():
            path = rev.get(iid)
            self.tree.delete(iid)
            self.items.pop(path, None)
            if path in self.files:
                self.files.remove(path)
        for i, f in enumerate(self.files):
            self.tree.item(self.items[f], tags=self._row_tags(i))
        self._refresh_count()

    def clear(self):
        if self.running:
            return
        self.outputs = []
        self.open_btn.grid_remove()
        self.tree.delete(*self.tree.get_children())
        self.files.clear()
        self.items.clear()
        self.prog.set(0)
        self.status_var.set("就绪")
        self._refresh_count()

    def _refresh_count(self):
        self.count_var.set(f"{len(self.files)} 个视频" if self.files else "")
        if self.files:
            self.empty.place_forget()
        else:
            self._show_empty()

    # ---------- 转换 ----------
    def _target(self, src):
        ext = FORMATS[self.fmt_var.get()]["ext"]
        name = os.path.splitext(os.path.basename(src))[0] + ext
        custom = self.out_mode.get() == "指定文件夹" and self.out_dir.get()
        folder = self.out_dir.get() if custom else os.path.dirname(src)
        dst = os.path.join(folder, name)
        if not self.overwrite.get():
            dst = unique_path(dst)
        return dst

    def start(self):
        if self.running:
            return
        if not self.ffmpeg:
            messagebox.showerror(APP_NAME, "未找到 ffmpeg，无法转换。")
            return
        if not self.files:
            messagebox.showinfo(APP_NAME, "请先添加视频。")
            return
        if self.out_mode.get() == "指定文件夹" and self.out_dir.get():
            os.makedirs(self.out_dir.get(), exist_ok=True)
        self.running = True
        self.done_count = 0
        self.outputs = []
        self.open_btn.grid_remove()
        self.stop_flag.clear()
        self.start_btn.configure(state="disabled", text="转换中…")
        self.stop_btn.configure(state="normal")
        self.prog.set(0)
        for i, f in enumerate(self.files):
            v = self.tree.item(self.items[f], "values")
            self.tree.item(self.items[f], values=(v[0], v[1], "排队中"), tags=self._row_tags(i))
        args = (list(self.files), self.fmt_var.get(), self.q_var.get(), self.rate_var.get(),
                )
        threading.Thread(target=self._run, args=args, daemon=True).start()

    def _run(self, files, fmt, quality, rate):
        reserved, rlock = set(), threading.Lock()

        def job(src):
            if self.stop_flag.is_set():
                self.msgs.put(("item", src, "已取消", None))
                return None
            with rlock:
                dst = self._target(src)
                while dst in reserved and not self.overwrite.get():
                    base, ext = os.path.splitext(dst)
                    dst = unique_path(base + " (1)" + ext)
                reserved.add(dst)
            self.msgs.put(("item", src, "转换中…", "run"))
            ok, err = convert_one(self.ffmpeg, src, dst, fmt, quality, rate,
                                  self.procs, self.lock)
            if self.stop_flag.is_set() and not ok:
                self.msgs.put(("item", src, "已取消", None))
                return None
            if ok:
                self.outputs.append(dst)
            self.msgs.put(("item", src, ("✓  " + os.path.basename(dst)) if ok else ("✕  " + err),
                           "ok" if ok else "err"))
            return ok

        # 自动并行：按 CPU 核数起步，转换中每 2 秒看一次电脑负载，忙就减、闲就加
        cores = os.cpu_count() or 2
        max_w = max(1, min(8, cores - 1))
        limit = max(1, min(max_w, cores // 2, len(files)))
        pending, active, results = list(files), set(), []
        cpu_busy()  # 初始化 CPU 采样
        last_check = time.time()
        with ThreadPoolExecutor(max_workers=max_w) as ex:
            while pending or active:
                while pending and len(active) < limit:
                    active.add(ex.submit(job, pending.pop(0)))
                done, _ = wait(active, timeout=0.5, return_when=FIRST_COMPLETED)
                for fut in done:
                    results.append(fut.result())
                    self.msgs.put(("tick", len(files), limit))
                active -= done
                if time.time() - last_check >= 2:
                    last_check = time.time()
                    busy = cpu_busy()
                    if busy is not None:
                        if busy > 0.9 and limit > 1:
                            limit -= 1
                        elif busy < 0.7 and limit < max_w:
                            limit += 1
        self.msgs.put(("done", results.count(True), results.count(False), results.count(None)))

    # ---------- 打开输出文件夹 ----------
    def output_folders(self):
        seen = []
        for f in self.outputs:
            d = os.path.dirname(f)
            if d not in seen:
                seen.append(d)
        return seen

    def open_output(self):
        folders = self.output_folders()
        for d in folders[:5]:  # 输出分散在多个文件夹时，最多打开 5 个
            first = next((f for f in sorted(self.outputs) if os.path.dirname(f) == d and os.path.exists(f)), None)
            try:
                if sys.platform == "darwin":
                    subprocess.Popen(["open", "-R", first] if first else ["open", d])
                elif sys.platform == "win32":
                    if first:
                        subprocess.Popen(["explorer", "/select,", os.path.normpath(first)])
                    else:
                        os.startfile(d)
                else:
                    subprocess.Popen(["xdg-open", d])
            except Exception as e:
                messagebox.showerror(APP_NAME, f"无法打开文件夹：{e}")

    def done_dialog(self, ok, bad, cancel):
        P = self.P
        top = ctk.CTkToplevel(self.root, fg_color=P["card"])
        top.title(APP_NAME)
        top.resizable(False, False)
        top.transient(self.root)
        ff = font_family()
        ctk.CTkLabel(top, text="✓" if not bad else "!", width=44, height=44, corner_radius=22,
                     fg_color=P["accent"] if not bad else P["err"], text_color=P["on_accent"],
                     font=ctk.CTkFont(ff, 20, "bold")).pack(pady=(26, 10))
        ctk.CTkLabel(top, text="转换完成" if not bad else "转换完成（有失败）",
                     font=ctk.CTkFont(ff, 16, "bold"), text_color=P["text"]).pack()
        detail = f"成功 {ok} 个  ·  失败 {bad} 个" + (f"  ·  取消 {cancel} 个" if cancel else "")
        ctk.CTkLabel(top, text=detail, font=self.f_sub, text_color=P["sub"]).pack(pady=(4, 20))
        row = ctk.CTkFrame(top, fg_color="transparent")
        row.pack(padx=28, pady=(0, 24))

        def close():
            top.grab_release()
            top.destroy()

        def open_and_close():
            close()
            self.open_output()

        ctk.CTkButton(row, text="关闭", command=close, font=self.f_sub, width=96, height=34,
                      corner_radius=17, fg_color=P["soft"], hover_color=P["soft_h"],
                      text_color=P["text"]).pack(side="left", padx=6)
        if self.outputs:
            ctk.CTkButton(row, text="打开文件夹", command=open_and_close, font=self.f_btn,
                          width=120, height=34, corner_radius=17, fg_color=P["accent"],
                          hover_color=P["accent_h"], text_color=P["on_accent"]
                          ).pack(side="left", padx=6)
        top.update_idletasks()
        w, h = max(300, top.winfo_reqwidth()), top.winfo_reqheight()
        x = self.root.winfo_rootx() + (self.root.winfo_width() - w) // 2
        y = self.root.winfo_rooty() + (self.root.winfo_height() - h) // 3
        top.geometry(f"{w}x{h}+{x}+{y}")
        top.bind("<Escape>", lambda e: close())
        top.bind("<Return>", lambda e: open_and_close() if self.outputs else close())
        top.after(50, lambda: (top.lift(), top.focus_force(), top.grab_set()))
        self.dialog = top

    def stop(self):
        self.stop_flag.set()
        with self.lock:
            for p in list(self.procs):
                try:
                    p.kill()
                except Exception:
                    pass
        self.status_var.set("正在停止…")

    def _poll(self):
        try:
            while True:
                m = self.msgs.get_nowait()
                if m[0] == "item":
                    _, src, text, tag = m
                    iid = self.items.get(src)
                    if iid:
                        v = self.tree.item(iid, "values")
                        self.tree.item(iid, values=(v[0], v[1], text),
                                       tags=self._row_tags(self.files.index(src), tag))
                        if tag == "run":
                            self.tree.see(iid)
                elif m[0] == "tick":
                    self.done_count += 1
                    self.prog.set(self.done_count / m[1])
                    self.status_var.set(f"正在转换  {self.done_count} / {m[1]}"
                                        f"  ·  自动同时转 {m[2]} 个")
                elif m[0] == "done":
                    _, ok, bad, cancel = m
                    self.running = False
                    self.start_btn.configure(state="normal", text="开始转换")
                    self.stop_btn.configure(state="disabled")
                    self.status_var.set(f"完成  ·  成功 {ok}  ·  失败 {bad}"
                                        + (f"  ·  取消 {cancel}" if cancel else ""))
                    if self.outputs:
                        self.open_btn.grid(row=0, column=1, rowspan=2, padx=(20, 0))
                    self.root.update_idletasks()
                    self.done_dialog(ok, bad, cancel)
        except queue.Empty:
            pass
        self.root.after(80, self._poll)


def cli(argv):
    """命令行模式：python video2audio.py --cli 文件或文件夹... [--format mp3|wav|m4a|flac]"""
    fmt = "MP3"
    if "--format" in argv:
        i = argv.index("--format")
        fmt = argv[i + 1].upper() if i + 1 < len(argv) else ""
        del argv[i:i + 2]
        if fmt not in FORMATS:
            print("格式只能是：" + " / ".join(FORMATS))
            return 2
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        print("未找到 ffmpeg")
        return 2
    files = scan(argv)
    procs, lock, ok = set(), threading.Lock(), 0
    for src in files:
        dst = unique_path(os.path.splitext(src)[0] + FORMATS[fmt]["ext"])
        good, err = convert_one(ffmpeg, src, dst, fmt, FORMATS[fmt]["default_q"], "原始",
                                procs, lock)
        ok += good
        print(("OK  " if good else "ERR ") + src + ("" if good else "  " + err))
    print(f"完成 {ok}/{len(files)}")
    return 0 if ok == len(files) else 1


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--cli":
        sys.exit(cli(sys.argv[2:]))
    ctk.set_appearance_mode("Light")  # 默认浅色（薄荷绿）
    root = Root()
    initial = [a for a in sys.argv[1:] if os.path.exists(a)]
    App(root, initial)
    root.mainloop()
