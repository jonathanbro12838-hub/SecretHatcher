"""
Secret Hatch Notifer+  (black / red)
------------------------------
Watches your Roblox windows for the secret-hatch screen (the big BLACK egg
silhouette in the middle of the screen, or the "Hold to Reveal!" text).
When it sees one it posts to the shared community Discord channel, pings the
Discord ID you typed in, and attaches a picture of that Roblox window.

What it sends: your Discord ID mention, the account name, and an image of the
Roblox window only (never your whole desktop). It sends nothing until a secret
hatch is detected or you press a Test button. Windows only.
"""
import sys

if sys.platform != "win32":
    sys.exit("Secret Hatch Notifer+ only runs on Windows.")

import webbrowser, tempfile, subprocess, winsound
import io, os, re, json, time, queue, ctypes, base64, datetime, threading

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

import cv2
import numpy as np
import psutil
import requests
import mss
import win32con, win32gui, win32process, win32ui
from PIL import Image
from tkinter import ttk, messagebox, filedialog
import tkinter as tk
import customtkinter as ctk

BG, SIDEBAR, PANEL, PANEL2, BORDER = "#0c0c0d", "#111113", "#18181b", "#222226", "#2c2c31"
TEXT, MUTED = "#ececee", "#8d8d95"
ACCENT, ACCENT_HOT, ACCENT_DEEP, BANNER, GREEN = "#e9e9ec", "#ffffff", "#34343a", "#1d1d21", "#4ade80"
AMBER, DANGER, ON_ACCENT = "#fbbf24", "#ef4444", "#0c0c0d"

APP_VERSION = "1.3.1"
# Where the app looks for new versions. Use ONE of:
#   - a GitHub releases link:  "https://api.github.com/repos/YOUR-NAME/YOUR-REPO/releases/latest"
#   - a link to a small JSON file you host:  {"version": "1.1.0", "url": "https://download-link", "notes": "what's new"}
# Leave it empty to turn update checking off.
UPDATE_URL = "https://api.github.com/repos/jonathanbro12838-hub/hatcher-releases/releases/latest"

GWL_EXSTYLE, WS_EX_LAYERED, WS_EX_TRANSPARENT, WS_EX_NOACTIVATE, LWA_ALPHA = -20, 0x80000, 0x20, 0x08000000, 2
ROBLOX_EXES = ("robloxplayerbeta.exe", "robloxplayer.exe", "windows10universal.exe")
ID_RE = re.compile(r"^\d{17,20}$")
FULL_W, FULL_H = 1280, 720

def resource_path(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


SOUND_PATH = resource_path("alert.wav")


def play_sound():
    try:
        winsound.PlaySound(SOUND_PATH, winsound.SND_FILENAME | winsound.SND_ASYNC)
    except Exception:
        pass


# Settings and stats live in AppData, so the exe works from anywhere (Downloads, Desktop, a USB stick)
# and never leaves extra files next to it.
APP_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Secret Hatch Notifer+")
try:
    os.makedirs(APP_DIR, exist_ok=True)
except Exception:
    APP_DIR = os.path.dirname(sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__))
CONFIG_PATH = os.path.join(APP_DIR, "config.json")
STATS_PATH = os.path.join(APP_DIR, "stats.json")
DEFAULTS = {"discord_id": "", "rearm": 6, "interval": 1.0, "peek": 5, "minimized": True,
            "fullsize": False, "reveal_delay": 8, "dc_warn": True, "reveal_pic": False,
            "sound_ui": True, "sound_alert": True}

# Shared community webhook, kept out of the UI and not stored in plain text.
# (Anyone determined can still extract it from a client; see README notes.)
try:
    import hw_secrets as _S  # written at build time from GitHub secrets / webhooks.txt, never stored in the repo
except Exception:
    _S = None
_K = b"hw-community-v1"


def _hook(kind="main"):
    blob = getattr(_S, "TEST" if kind == "test" else "MAIN", "") if _S else ""
    if not blob:
        raise RuntimeError("this copy was built without a Discord webhook")
    raw = base64.b64decode(blob)
    return bytes(c ^ _K[i % len(_K)] for i, c in enumerate(raw)).decode()


def is_reveal_text(text):
    t = re.sub(r"[^a-z0-9]", "", text.lower()).replace("0", "o").replace("1", "l")
    if "holdtoreve" in t or "holdtoreal" in t or "toreveal" in t:
        return True
    return "reveal" in t and "hold" in t


def find_black_egg(frame):
    """True if a big solid-black silhouette (the unrevealed secret) sits in the middle of the window.

    Works for tiny, narrow, tall or half-snapped windows: it only looks at the shape's RELATIVE size and position,
    and it is fine if the shape runs into the window edges (a narrow window crops the sides of the scene)."""
    if frame is None or frame.size == 0:
        return False
    h, w = frame.shape[:2]
    if h < 40 or w < 40:
        return False
    sc = 480.0 / max(h, w)
    sw, sh = max(24, int(w * sc)), max(24, int(h * sc))
    small = cv2.resize(frame, (sw, sh), interpolation=cv2.INTER_AREA if sc < 1 else cv2.INTER_LINEAR)
    H, W = small.shape[:2]
    peak = small.max(axis=2)
    dark = (peak < 16).astype(np.uint8)
    if dark.mean() > 0.75:  # almost all black = loading screen / black capture, not a secret
        return False
    if (peak > 60).mean() < 0.10:  # needs real picture around it (the game UI), not just a few pixels
        return False
    dark = cv2.morphologyEx(dark, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    n, _, stats, cents = cv2.connectedComponentsWithStats(dark, connectivity=8)
    lum = small.mean(axis=2)
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if not (0.04 <= area / float(W * H) <= 0.80):
            continue
        cx, cy = cents[i]
        if not (0.20 * W <= cx <= 0.80 * W and 0.15 * H <= cy <= 0.85 * H):
            continue
        if area / float(bw * bh) < 0.50 or not (0.35 <= bh / float(bw) <= 3.5):
            continue
        pad = 6
        x0, y0, x1, y1 = max(0, x - pad), max(0, y - pad), min(W, x + bw + pad), min(H, y + bh + pad)
        ring = lum[y0:y1, x0:x1].copy()
        ring[(y - y0):(y - y0 + bh), (x - x0):(x - x0 + bw)] = np.nan
        if np.isfinite(ring).any() and np.nanmean(ring) < 20:
            continue
        return True
    return False


def is_disconnect_text(text):
    t = re.sub(r"[^a-z0-9]", "", text.lower())
    keys = ("disconnected", "errorcode", "youwerekicked", "lostconnection", "connectionerror",
            "serverhasshutdown", "servershutdown", "connectionattemptfailed")
    return any(k in t for k in keys)


def parse_version(v):
    nums = re.findall(r"\d+", str(v))
    return tuple(int(n) for n in nums[:4]) or (0,)


def fetch_update_info():
    r = requests.get(UPDATE_URL, timeout=8, headers={"Accept": "application/json", "User-Agent": "SecretHatchNotifer"})
    r.raise_for_status()
    d = r.json()
    ver = d.get("tag_name") or d.get("version") or ""
    url = d.get("html_url") or d.get("url") or ""
    notes = d.get("body") or d.get("notes") or ""
    asset = ""
    for a in d.get("assets") or []:
        if str(a.get("name", "")).lower().endswith(".exe"):
            asset = a.get("browser_download_url") or ""
            break
    if not asset:
        asset = d.get("download") or ""
    return str(ver), str(url), str(notes), str(asset)


def load_stats():
    st = {"total": 0, "accounts": {}, "history": []}
    try:
        with open(STATS_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
        st["total"] = int(d.get("total", 0))
        st["accounts"] = {str(k): int(v) for k, v in d.get("accounts", {}).items()}
        st["history"] = [h for h in d.get("history", []) if "t" in h and "account" in h]
    except Exception:
        pass
    return st


def save_stats(stats):
    try:
        with open(STATS_PATH, "w", encoding="utf-8") as f:
            json.dump(stats, f)
    except Exception:
        pass


def make_thumb(frame, w=224, h=126):
    img = Image.fromarray(frame)
    img.thumbnail((w, h), Image.BILINEAR)
    canvas = Image.new("RGB", (w, h), (0, 0, 0))
    canvas.paste(img, ((w - img.width) // 2, (h - img.height) // 2))
    return canvas


def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            for k, v in json.load(f).items():
                if k in cfg:
                    cfg[k] = v
    except Exception:
        pass
    return cfg


def save_config(cfg):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


def fmt_uptime(sec):
    sec = int(max(0, sec))
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m {s:02d}s"


def to_jpeg_bytes(frame, max_width=1280):
    img = Image.fromarray(frame)
    if img.width < 800:  # tiny window: enlarge so the picture in Discord is still easy to see
        img = img.resize((800, max(1, int(img.height * 800 / img.width))), Image.LANCZOS)
    if img.width > max_width:
        img = img.resize((max_width, int(img.height * max_width / img.width)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def post_discord(payload, image_bytes=None, ping_id=None, test=False):
    payload = dict(payload)
    payload["allowed_mentions"] = {"users": [ping_id]} if ping_id else {"parse": []}
    if image_bytes:
        r = requests.post(_hook("test" if test else "main"), data={"payload_json": json.dumps(payload)},
                          files={"files[0]": ("secret.jpg", image_bytes, "image/jpeg")}, timeout=20)
    else:
        r = requests.post(_hook("test" if test else "main"), json=payload, timeout=20)
    if r.status_code >= 300:
        raise RuntimeError(f"Discord replied {r.status_code}: {r.text[:120]}")


# --------------------------------------------------------------------------
# Windows: find Roblox windows and capture them
# --------------------------------------------------------------------------
def find_roblox_windows(name_cache):
    found = []

    def callback(hwnd, _):
        if not win32gui.IsWindowVisible(hwnd):
            return True
        if win32gui.GetWindow(hwnd, win32con.GW_OWNER):
            return True
        title = win32gui.GetWindowText(hwnd)
        if not title.strip().lower().startswith("roblox"):
            return True
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:
            return True
        if pid not in name_cache:
            try:
                name_cache[pid] = psutil.Process(pid).name().lower()
            except Exception:
                name_cache[pid] = ""
        if name_cache[pid] in ROBLOX_EXES:
            found.append((hwnd, pid, title))
        return True

    win32gui.EnumWindows(callback, None)
    return found


def client_geometry(hwnd):
    left, top, right, bottom = win32gui.GetClientRect(hwnd)
    sx, sy = win32gui.ClientToScreen(hwnd, (0, 0))
    return sx, sy, right - left, bottom - top


def is_small(hwnd):
    """True if the window is smaller than a normal game view (and not maximized)."""
    try:
        if win32gui.IsZoomed(hwnd):
            return False
        _, _, cw, ch = client_geometry(hwnd)
        return cw < FULL_W - 40 or ch < FULL_H - 40
    except Exception:
        return False


def bring_to_front(hwnd):
    try:
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        win32gui.SetForegroundWindow(hwnd)
    except Exception:
        try:
            ctypes.windll.user32.FlashWindow(hwnd, True)
        except Exception:
            pass


def looks_incomplete(frame):
    """True if the frame is missing or two or more quarters of it are pure black (a partial window capture)."""
    if frame is None or frame.size == 0:
        return True
    h, w = frame.shape[:2]
    if h < 20 or w < 20:
        return True
    black = 0
    for ys in (slice(0, h // 2), slice(h // 2, h)):
        for xs in (slice(0, w // 2), slice(w // 2, w)):
            if frame[ys, xs][::8, ::8].max() < 8:
                black += 1
    return black >= 2


class Grabber:
    """Captures the whole game area of a window. One instance per thread."""

    def __init__(self):
        self._sct = None

    def _screen(self, hwnd):
        sx, sy, cw, ch = client_geometry(hwnd)
        if cw < 10 or ch < 10:
            return None
        if self._sct is None:
            self._sct = mss.mss()
        shot = self._sct.grab({"left": sx, "top": sy, "width": cw, "height": ch})
        return np.ascontiguousarray(np.asarray(shot)[:, :, :3][:, :, ::-1])

    def _printwindow(self, hwnd):
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        w, h = right - left, bottom - top
        if w < 10 or h < 10:
            return None
        hwnd_dc = win32gui.GetWindowDC(hwnd)
        mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
        save_dc = mfc_dc.CreateCompatibleDC()
        bitmap = win32ui.CreateBitmap()
        try:
            bitmap.CreateCompatibleBitmap(mfc_dc, w, h)
            save_dc.SelectObject(bitmap)
            ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetSafeHdc(), 2)  # 2 = render full content
            bits = bitmap.GetBitmapBits(True)
            arr = np.frombuffer(bits, dtype=np.uint8).reshape(h, w, 4)
            sx, sy, cw, ch = client_geometry(hwnd)
            ox, oy = sx - left, sy - top
            arr = arr[oy:oy + ch, ox:ox + cw, :3][:, :, ::-1]
            return np.ascontiguousarray(arr)
        finally:
            win32gui.DeleteObject(bitmap.GetHandle())
            save_dc.DeleteDC()
            mfc_dc.DeleteDC()
            win32gui.ReleaseDC(hwnd, hwnd_dc)

    def grab(self, hwnd, mode):
        if mode.startswith("Screen"):
            return self._screen(hwnd)
        frame = self._printwindow(hwnd)
        if mode.startswith("Window"):
            return frame
        # Auto: fall back to a screen grab if the window capture came back black or only partly drawn
        if frame is None or frame.size == 0 or frame.mean() < 2 or looks_incomplete(frame):
            try:
                alt = self._screen(hwnd)
            except Exception:
                alt = None
            if alt is not None and not looks_incomplete(alt):
                return alt
            if frame is None or frame.size == 0 or frame.mean() < 2:
                return alt
        return frame

    def peek(self, hwnd, mode, settle=1.2, full=False):
        """Look at a MINIMIZED window without the user seeing anything.

        The window is restored without taking focus, made fully see-through and click-through, read through its own
        render (PrintWindow), then minimized again and its normal style put back. If that gives a black picture it
        falls back to a very short visible peek."""
        ex_old = None
        frame = None
        try:
            ex_old = win32gui.GetWindowLong(hwnd, GWL_EXSTYLE)
            win32gui.SetWindowLong(hwnd, GWL_EXSTYLE, ex_old | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE)
            win32gui.SetLayeredWindowAttributes(hwnd, 0, 0, LWA_ALPHA)  # fully see-through
        except Exception:
            ex_old = None
        try:
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 3, ctypes.byref(ctypes.c_int(1)), 4)  # no minimize/restore animation
        except Exception:
            pass
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_SHOWNOACTIVATE)
            time.sleep(settle)  # give the game time to draw a fresh frame
            for attempt in range(2):
                frame = self._printwindow(hwnd)
                if frame is not None and frame.size and frame.mean() >= 2:
                    return frame
                time.sleep(0.8)
            if ex_old is not None:  # the invisible read came back black: show it for a moment instead
                try:
                    win32gui.SetLayeredWindowAttributes(hwnd, 0, 255, LWA_ALPHA)
                except Exception:
                    pass
                time.sleep(0.5)
                alt = self.grab(hwnd, mode)
                if alt is not None and alt.size:
                    return alt
            return frame
        finally:
            try:
                win32gui.ShowWindow(hwnd, win32con.SW_SHOWMINNOACTIVE)
            except Exception:
                pass
            if ex_old is not None:
                try:
                    win32gui.SetWindowLong(hwnd, GWL_EXSTYLE, ex_old)
                except Exception:
                    pass
            try:
                ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 3, ctypes.byref(ctypes.c_int(0)), 4)
            except Exception:
                pass

    def capture(self, hwnd, mode, allow_peek=True, full=False):
        if win32gui.IsIconic(hwnd):
            return self.peek(hwnd, mode, full=full) if allow_peek else None
        return self.grab(hwnd, mode)  # never resizes or moves the user's window



def snap_window(hwnd, allow_peek=True, full=True):
    """Picture of ONE Roblox window (its game area only), never the desktop or other windows.

    Uses the window's own render (PrintWindow), so windows on top of it don't show up. A screen grab is only
    used if that render is black AND nothing else is covering the middle of the window."""
    g = Grabber()
    frame = g.capture(hwnd, "Window", allow_peek=allow_peek, full=full)
    if frame is not None and frame.size and frame.mean() >= 2 and not looks_incomplete(frame):
        return frame
    try:
        sx, sy, cw, ch = client_geometry(hwnd)
        top = ctypes.windll.user32.GetAncestor(win32gui.WindowFromPoint((sx + cw // 2, sy + ch // 2)), 2)
        if top == hwnd:  # window is on top, so a screen grab of its area is just this window
            alt = g.capture(hwnd, "Screen", allow_peek=allow_peek, full=full)
            if alt is not None and alt.size:
                return alt
    except Exception:
        pass
    return frame


class StatCard(ctk.CTkFrame):
    def __init__(self, master, title):
        super().__init__(master, fg_color=PANEL, border_width=1, border_color=BORDER, corner_radius=12)
        self.val = ctk.CTkLabel(self, text="0", text_color=TEXT, font=ctk.CTkFont(size=28, weight="bold"))
        self.val.pack(anchor="w", padx=16, pady=(12, 0))
        ctk.CTkLabel(self, text=title, text_color=MUTED, font=ctk.CTkFont(size=11)).pack(anchor="w", padx=16, pady=(0, 12))

    def set(self, v):
        self.val.configure(text=f"{int(v):,}")


class AccountCard(ctk.CTkFrame):
    """One Roblox window: live preview, memory, status, watch switch and a Manage menu."""
    W, H = 224, 126

    def __init__(self, master, app, st):
        super().__init__(master, fg_color=PANEL, border_width=2, border_color=BORDER, corner_radius=12)
        self.app, self.hwnd, self.seen_v, self.last = app, st.hwnd, -1, None
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=10, pady=(8, 4))
        self.name = ctk.CTkLabel(top, text=st.label, text_color=TEXT, anchor="w", font=ctk.CTkFont(size=12, weight="bold"))
        self.name.pack(side="left")
        self.mem = ctk.CTkLabel(top, text="", text_color=MUTED, font=ctk.CTkFont(size=10))
        self.mem.pack(side="left", padx=(8, 0))
        self.menu_btn = ctk.CTkButton(top, text="Manage ▾", width=74, height=24, corner_radius=7, fg_color=PANEL2,
                                      hover_color=ACCENT_DEEP, text_color=TEXT, font=ctk.CTkFont(size=11),
                                      command=self._menu)
        self.menu_btn.pack(side="right")
        self.img = ctk.CTkLabel(self, text="Waiting for a preview…", text_color=MUTED, width=self.W, height=self.H,
                                fg_color="#000000", corner_radius=6, font=ctk.CTkFont(size=11))
        self.img.pack(padx=10)
        bot = ctk.CTkFrame(self, fg_color="transparent")
        bot.pack(fill="x", padx=10, pady=(6, 9))
        self.dot = ctk.CTkLabel(bot, text="●", text_color=MUTED, font=ctk.CTkFont(size=12))
        self.dot.pack(side="left")
        self.status = ctk.CTkLabel(bot, text="", text_color=MUTED, font=ctk.CTkFont(size=11), anchor="w")
        self.status.pack(side="left", padx=(4, 0))
        self.watch_var = tk.BooleanVar(value=st.watch)
        ctk.CTkSwitch(bot, text="Watch", variable=self.watch_var, command=self._toggle, width=40, text_color=TEXT,
                      font=ctk.CTkFont(size=11), progress_color=GREEN, fg_color=ACCENT_DEEP).pack(side="right")
        for w in (self, top, bot, self.img, self.name, self.mem, self.dot, self.status):
            w.bind("<Button-1>", self._select)
            w.bind("<Double-1>", lambda e: self.app.open_view(self.hwnd))

    def _select(self, _e=None):
        self.app.select(self.hwnd)

    def _toggle(self):
        self.app.set_watch(self.hwnd, bool(self.watch_var.get()))

    def _menu(self):
        self.app.select(self.hwnd)
        m = tk.Menu(self, tearoff=0, bg=PANEL2, fg=TEXT, activebackground=ACCENT_DEEP, activeforeground=TEXT, bd=0)
        m.add_command(label="Open live view", command=self.app.on_view)
        m.add_command(label="Test detection (no send)", command=self.app.on_test_read)
        m.add_command(label="Rename…", command=self.app.on_rename)
        m.add_command(label="Bring to front", command=self.app.on_front)
        try:
            m.tk_popup(self.menu_btn.winfo_rootx(), self.menu_btn.winfo_rooty() + self.menu_btn.winfo_height())
        finally:
            m.grab_release()

    def refresh(self, st, mem, status, color, selected):
        sig = (st.label, mem, status, color, selected, st.watch, st.hit)
        if sig != self.last:
            self.last = sig
            self.name.configure(text=st.label[:18])
            self.mem.configure(text=mem)
            self.status.configure(text=status, text_color=color)
            self.dot.configure(text_color=color)
            self.configure(border_color=ACCENT if selected else (AMBER if (st.hit and st.watch) else BORDER))
            if self.watch_var.get() != st.watch:
                self.watch_var.set(st.watch)
        if st.thumb is not None and st.thumb_v != self.seen_v:
            self.seen_v = st.thumb_v
            ci = ctk.CTkImage(light_image=st.thumb, dark_image=st.thumb, size=(self.W, self.H))
            self.img.configure(image=ci, text="")
            self.ci = ci


class WinState:
    def __init__(self, hwnd, pid, label):
        self.hwnd, self.pid, self.label = hwnd, pid, label
        self.watch, self.armed = True, True
        self.streak = 0
        self.last_peek = 0.0
        self.gone_since = None
        self.dc_streak = self.dc_clear = 0
        self.thumb, self.thumb_v, self.thumb_t = None, 0, 0.0
        self.last_txt = self.last_full = 0.0
        self.dc_sent = False
        self.hit = False
        self.status = "Starting…"
        try:
            self.proc = psutil.Process(pid)
            self.proc.cpu_percent(None)
        except Exception:
            self.proc = None


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.title("Secret Hatch Notifer+")
        self.geometry("1320x820")
        self.minsize(1120, 700)
        self.configure(fg_color=BG)
        try:  # CustomTkinter sets its own icon after startup, so set ours slightly later
            self.after(250, lambda: self.iconbitmap(resource_path("icon.ico")))
        except Exception:
            pass
        self.cfg = load_config()
        self.settings = dict(self.cfg)
        self.states, self.name_cache = {}, {}
        self.counter = 0
        self.log_q = queue.Queue()
        self.stop = threading.Event()
        self.running = False
        self.ocr = None
        self.ocr_lock = threading.Lock()
        self.last_test = 0.0
        self.stats = load_stats()
        self.stats_lock = threading.Lock()
        self.session = {}
        self._tick_n = 0
        self._last_saved = None
        self.page, self.selected = "workspace", None
        self.cards, self.card_order, self.pages, self.nav, self.kv = {}, [], {}, {}, {}
        self.dc_count = self.fail_count = 0
        self.update_info, self._updating = None, False
        self._build_ui()
        self._sync()
        self.scan_windows()
        self.after(700, self._tick)
        self.after(4000, self._periodic_update_check)
        threading.Thread(target=self._worker, daemon=True).start()
        threading.Thread(target=self._preview_worker, daemon=True).start()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.log("Ready. Enter your Discord ID, then press START.")

    # ------------------------------------------------------------------ UI
    def _click(self):
        if self.settings.get("sound_ui", True):
            play_sound()

    def _snd(self, cmd):
        def inner():
            self._click()
            cmd()
        return inner

    def _card(self, parent, accent=False):
        return ctk.CTkFrame(parent, fg_color=BANNER if accent else PANEL, border_width=1,
                            border_color=ACCENT_DEEP if accent else BORDER, corner_radius=12)

    def _btn(self, parent, text, cmd, primary=False, width=None, height=34):
        kw = dict(text=text, command=self._snd(cmd), corner_radius=8, height=height)
        if width:
            kw["width"] = width
        if primary:
            return ctk.CTkButton(parent, fg_color=ACCENT, hover_color=ACCENT_HOT, text_color=ON_ACCENT,
                                 font=ctk.CTkFont(weight="bold"), **kw)
        return ctk.CTkButton(parent, fg_color=PANEL2, hover_color=ACCENT_DEEP, border_width=1,
                             border_color=BORDER, text_color=TEXT, **kw)

    def _label(self, parent, text, size=11, color=MUTED, bold=False):
        return ctk.CTkLabel(parent, text=text, text_color=color,
                            font=ctk.CTkFont(size=size, weight="bold" if bold else "normal"))

    def _checkbox(self, parent, text, var):
        def cmd():
            self._click()
            self._sync()
        return ctk.CTkCheckBox(parent, text=text, variable=var, text_color=TEXT, fg_color=ACCENT,
                               checkmark_color=ON_ACCENT, hover_color=ACCENT_HOT, border_color=BORDER, command=cmd)

    def _page(self, key, title):
        page = ctk.CTkFrame(self.content, fg_color=BG)
        page.grid(row=0, column=0, sticky="nsew")
        self.pages[key] = page
        page.grid_columnconfigure(0, weight=1)
        page.grid_rowconfigure(1, weight=1)
        self._label(page, title, 22, TEXT, True).grid(row=0, column=0, sticky="w", padx=26, pady=(22, 8))
        body = ctk.CTkFrame(page, fg_color=BG)
        body.grid(row=1, column=0, sticky="nsew", padx=26, pady=(0, 18))
        return body

    def show_page(self, name):
        self.page = name
        for k, pg in self.pages.items():
            if k == name:
                pg.grid()
            else:
                pg.grid_remove()
        for k, b in self.nav.items():
            b.configure(fg_color=PANEL2 if k == name else "transparent", text_color=TEXT if k == name else MUTED)
        if name == "stats":
            self.refresh_stats()

    def _build_ui(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ---- left sidebar
        sb = ctk.CTkFrame(self, fg_color=SIDEBAR, corner_radius=0, width=220)
        sb.grid(row=0, column=0, sticky="nsw")
        sb.grid_propagate(False)
        sb.grid_rowconfigure(10, weight=1)
        hdr = ctk.CTkFrame(sb, fg_color="transparent")
        hdr.grid(row=0, column=0, rowspan=3, sticky="ew", padx=16, pady=(20, 16))
        try:
            logo = Image.open(resource_path("icon.png"))
            self.logo_img = ctk.CTkImage(light_image=logo, dark_image=logo, size=(40, 40))
            ctk.CTkLabel(hdr, image=self.logo_img, text="").grid(row=0, column=0, rowspan=3, padx=(0, 10))
        except Exception:
            pass
        self._label(hdr, "SECRET HATCH", 13, TEXT, True).grid(row=0, column=1, sticky="w")
        self._label(hdr, "NOTIFER+", 13, TEXT, True).grid(row=1, column=1, sticky="w")
        self._label(hdr, "ALERTS MANAGER", 9, MUTED, True).grid(row=2, column=1, sticky="w")
        for i, (key, text) in enumerate((("workspace", "▣   Live workspace"), ("stats", "▤   Stats"),
                                         ("activity", "☰   Activity log"), ("settings", "⚙   Settings"))):
            b = ctk.CTkButton(sb, text=text, anchor="w", height=40, corner_radius=8, fg_color="transparent",
                              hover_color=PANEL2, text_color=MUTED, font=ctk.CTkFont(size=13),
                              command=self._snd(lambda k=key: self.show_page(k)))
            b.grid(row=3 + i, column=0, sticky="ew", padx=12, pady=2)
            self.nav[key] = b
        self.state_pill = ctk.CTkLabel(sb, text="●  STOPPED", text_color=MUTED, fg_color=PANEL2, corner_radius=10,
                                       height=34, font=ctk.CTkFont(size=12, weight="bold"))
        self.state_pill.grid(row=11, column=0, sticky="ew", padx=14, pady=(0, 8))
        self.update_btn = ctk.CTkButton(sb, text="", corner_radius=8, height=36, fg_color=AMBER, hover_color="#ffd25e",
                                        text_color="#1a1200", font=ctk.CTkFont(size=12, weight="bold"),
                                        command=self.on_update_click)
        self.update_btn.grid(row=12, column=0, sticky="ew", padx=14, pady=(0, 8))
        self.update_btn.grid_remove()
        self._label(sb, f"v{APP_VERSION}", 10, MUTED).grid(row=13, column=0, sticky="w", padx=20, pady=(0, 16))
        sb.grid_columnconfigure(0, weight=1)

        # ---- pages
        self.content = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)
        self._build_workspace(self._page("workspace", "Live workspace"))
        self._build_stats(self._page("stats", "Stats"))
        self._build_activity(self._page("activity", "Activity log"))
        self._build_settings(self._page("settings", "Settings"))

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT, rowheight=30,
                        borderwidth=0, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", background=PANEL2, foreground=MUTED, relief="flat",
                        font=("Segoe UI", 9, "bold"))
        style.map("Treeview", background=[("selected", ACCENT_DEEP)], foreground=[("selected", TEXT)])
        self.show_page("workspace")

    # ---- Live workspace: control row, counters, account cards with live previews, overview on the right
    def _build_workspace(self, body):
        body.grid_columnconfigure(0, weight=1)
        body.grid_columnconfigure(1, minsize=270)
        body.grid_rowconfigure(0, weight=1)
        main = ctk.CTkFrame(body, fg_color=BG)
        main.grid(row=0, column=0, sticky="nsew", padx=(0, 14))
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(3, weight=1)
        side = ctk.CTkFrame(body, fg_color=BG)
        side.grid(row=0, column=1, sticky="nsew")

        # control row
        ctl = self._card(main)
        ctl.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        ctl.grid_columnconfigure(0, weight=1)
        self._label(ctl, "YOUR DISCORD USER ID  (you get pinged when YOUR account hatches a secret)", 10, MUTED, True
                    ).grid(row=0, column=0, columnspan=3, sticky="w", padx=16, pady=(12, 4))
        self.id_var = ctk.StringVar(value=self.cfg["discord_id"])
        ctk.CTkEntry(ctl, textvariable=self.id_var, fg_color=PANEL2, border_color=BORDER, height=38,
                     placeholder_text="e.g. 123456789012345678").grid(row=1, column=0, sticky="ew", padx=(16, 8))
        self.start_btn = self._btn(ctl, "START", self.on_toggle, primary=True, width=120, height=38)
        self.start_btn.grid(row=1, column=1, padx=4)
        self._btn(ctl, "Send test alert", self.on_test_alert, width=130, height=38).grid(row=1, column=2, padx=(4, 16))
        self._label(ctl, "Discord → Settings → Advanced → Developer Mode ON, then right-click your name → Copy User ID.  "
                         "Alerts show only the Roblox window, never your desktop.", 10, MUTED
                    ).grid(row=2, column=0, columnspan=3, sticky="w", padx=16, pady=(6, 12))

        # counters
        cnt = ctk.CTkFrame(main, fg_color=BG)
        cnt.grid(row=1, column=0, sticky="ew", pady=(0, 14))
        cnt.grid_columnconfigure((0, 1, 2), weight=1, uniform="c")
        self.big = {}
        for i, (key, title) in enumerate((("today", "secrets today"), ("session", "this session"), ("total", "all time"))):
            self.big[key] = StatCard(cnt, title)
            self.big[key].grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else 6, 0 if i == 2 else 6))

        # workspace header
        hd = ctk.CTkFrame(main, fg_color=BG)
        hd.grid(row=2, column=0, sticky="ew", pady=(0, 8))
        hd.grid_columnconfigure(0, weight=1)
        self._label(hd, "Your workspace", 16, TEXT, True).grid(row=0, column=0, sticky="w")
        self._label(hd, "Click a card to select it  •  double-click to open its live view", 10, MUTED
                    ).grid(row=1, column=0, sticky="w")
        bar = ctk.CTkFrame(hd, fg_color=BG)
        bar.grid(row=0, column=1, rowspan=2, sticky="e")
        self._btn(bar, "Scan for windows", self.scan_windows).pack(side="left", padx=3)
        self._btn(bar, "Open live view", self.on_view).pack(side="left", padx=3)
        self._btn(bar, "Test detection", self.on_test_read).pack(side="left", padx=3)
        self._btn(bar, "Watch all", lambda: self._set_all(True)).pack(side="left", padx=3)
        self._btn(bar, "None", lambda: self._set_all(False), width=56).pack(side="left", padx=(3, 0))

        # cards grid
        self.grid_area = ctk.CTkScrollableFrame(main, fg_color=PANEL, border_width=1, border_color=BORDER, corner_radius=12)
        self.grid_area.grid(row=3, column=0, sticky="nsew")
        self.grid_area.grid_columnconfigure((0, 1, 2), weight=1)
        self.empty_lbl = ctk.CTkLabel(self.grid_area, text="No Roblox windows found yet.\nOpen Roblox, then press “Scan for windows”.",
                                      text_color=MUTED, font=ctk.CTkFont(size=13))
        self.empty_lbl.grid(row=0, column=0, columnspan=3, pady=60)

        # overview column
        top = self._card(side, accent=True)
        top.pack(fill="x", pady=(0, 10))
        self.ov_big = ctk.CTkLabel(top, text="0 / 0", text_color=TEXT, font=ctk.CTkFont(size=30, weight="bold"))
        self.ov_big.pack(anchor="w", padx=16, pady=(14, 0))
        self._label(top, "accounts being watched", 11, MUTED).pack(anchor="w", padx=16, pady=(0, 14))
        self._kv_block(side, "WINDOWS", (("w_watch", "Watching"), ("w_secret", "Secret on screen"),
                                         ("w_dc", "Disconnected?"), ("w_min", "Minimized"), ("w_off", "Not watching")))
        self._kv_block(side, "THIS PC", (("pc_rob", "Roblox RAM"), ("pc_free", "Free RAM"), ("pc_cpu", "CPU")))
        self._kv_block(side, "SINCE YOU OPENED THIS APP", (("s_secrets", "Secrets found"), ("s_dc", "Disconnect warnings"),
                                                           ("s_fail", "Failed alerts")))

    def _kv_block(self, parent, title, rows):
        c = self._card(parent)
        c.pack(fill="x", pady=(0, 10))
        self._label(c, title, 10, MUTED, True).pack(anchor="w", padx=16, pady=(12, 4))
        for key, text in rows:
            r = ctk.CTkFrame(c, fg_color="transparent")
            r.pack(fill="x", padx=16, pady=2)
            self._label(r, text, 11, MUTED).pack(side="left")
            v = self._label(r, "0", 11, TEXT, True)
            v.pack(side="right")
            self.kv[key] = v
        ctk.CTkLabel(c, text="", height=6).pack()

    def _build_activity(self, body):
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(0, weight=1)
        lg = self._card(body)
        lg.grid(row=0, column=0, sticky="nsew")
        self.logbox = ctk.CTkTextbox(lg, fg_color=PANEL2, text_color=TEXT, border_width=0,
                                     font=ctk.CTkFont(family="Consolas", size=12))
        self.logbox.pack(fill="both", expand=True, padx=14, pady=14)
        self.logbox.configure(state="disabled")

    # ---- Settings
    def _build_settings(self, body):
        body.grid_columnconfigure((0, 1), weight=1, uniform="s")
        self.cool_var = ctk.StringVar(value=str(self.cfg["rearm"]))
        self.int_var = ctk.StringVar(value=str(self.cfg["interval"]))
        self.peek_var = ctk.StringVar(value=str(self.cfg["peek"]))
        self.rev_var = ctk.StringVar(value=str(self.cfg["reveal_delay"]))
        self.min_var = ctk.BooleanVar(value=self.cfg["minimized"])
        self.full_var = ctk.BooleanVar(value=False)
        self.dc_var = ctk.BooleanVar(value=self.cfg["dc_warn"])
        self.rev_pic_var = ctk.BooleanVar(value=self.cfg["reveal_pic"])
        self.sound_ui_var = ctk.BooleanVar(value=self.cfg["sound_ui"])
        self.sound_alert_var = ctk.BooleanVar(value=self.cfg["sound_alert"])

        tm = self._card(body)
        tm.grid(row=0, column=0, sticky="nsew", padx=(0, 7), pady=(0, 14))
        self._label(tm, "TIMING", 10, MUTED, True).grid(row=0, column=0, sticky="w", padx=18, pady=(14, 0))
        for i, (txt, var) in enumerate((("RE-ARM AFTER SECRET IS GONE (SEC)", self.cool_var),
                                        ("SCAN EVERY (SEC)", self.int_var),
                                        ("CHECK MINIMIZED EVERY (SEC)", self.peek_var),
                                        ("2ND PICTURE AFTER (SEC)", self.rev_var))):
            self._label(tm, txt, 9, MUTED, True).grid(row=1 + i * 2, column=0, sticky="w", padx=18, pady=(10, 0))
            ctk.CTkEntry(tm, textvariable=var, fg_color=PANEL2, border_color=BORDER, height=32,
                         width=170).grid(row=2 + i * 2, column=0, sticky="w", padx=18)
        ctk.CTkLabel(tm, text="", height=8).grid(row=20, column=0)

        op = self._card(body)
        op.grid(row=0, column=1, sticky="nsew", padx=(7, 0), pady=(0, 14))
        self._label(op, "OPTIONS", 10, MUTED, True).grid(row=0, column=0, sticky="w", padx=18, pady=(14, 8))
        for i, (txt, var) in enumerate((("Scan minimized windows too", self.min_var),
                                        ("Warn me if an account disconnects", self.dc_var),
                                        ("Also send a 2nd picture after reveal", self.rev_pic_var),
                                        ("Play a sound when a secret is found", self.sound_alert_var),
                                        ("Click sounds on buttons", self.sound_ui_var))):
            self._checkbox(op, txt, var).grid(row=1 + i, column=0, sticky="w", padx=18, pady=7)
        self._btn(op, "Test sound", play_sound, width=110).grid(row=8, column=0, sticky="w", padx=18, pady=(6, 16))

        ab = self._card(body)
        ab.grid(row=1, column=0, columnspan=2, sticky="ew")
        self._label(ab, "ABOUT & UPDATES", 10, MUTED, True).grid(row=0, column=0, sticky="w", padx=18, pady=(14, 2))
        self._label(ab, f"Secret Hatch Notifer+  v{APP_VERSION}.  Checks for new versions on start and every 6 hours. "
                        "When one is out, an “Update” button appears bottom-left: click it and the app updates itself.",
                    11, TEXT).grid(row=1, column=0, sticky="w", padx=18)
        btns = ctk.CTkFrame(ab, fg_color="transparent")
        btns.grid(row=2, column=0, sticky="w", padx=18, pady=(10, 16))
        self._btn(btns, "Check for updates", lambda: self.check_updates(True), primary=True).pack(side="left", padx=(0, 6))
        self._btn(btns, "Open data folder", self.on_open_data).pack(side="left", padx=3)

    def on_open_data(self):
        try:
            os.startfile(APP_DIR)
        except Exception as e:
            self.log(f"Couldn't open the folder: {e}")

    # ------------------------------------------------------------- logging
    def log(self, msg):
        self.log_q.put(f"[{datetime.datetime.now().strftime('%H:%M:%S')}] {msg}")

    def _drain(self):
        lines = []
        try:
            while True:
                lines.append(self.log_q.get_nowait())
        except queue.Empty:
            pass
        if lines:
            self.logbox.configure(state="normal")
            self.logbox.insert("end", "\n".join(lines) + "\n")
            self.logbox.see("end")
            self.logbox.configure(state="disabled")

    # ------------------------------------------------------------ settings
    def _num(self, var, default, lo):
        try:
            v = max(lo, float(var.get()))
            return int(v) if v == int(v) else v
        except Exception:
            return default

    def _sync(self):
        snap = {"discord_id": self.id_var.get().strip(), "rearm": self._num(self.cool_var, 6, 3),
                "interval": self._num(self.int_var, 1.0, 0.2), "peek": self._num(self.peek_var, 5, 2),
                "minimized": bool(self.min_var.get()), "fullsize": bool(self.full_var.get()), "dc_warn": bool(self.dc_var.get()), "reveal_pic": bool(self.rev_pic_var.get()),
                "sound_ui": bool(self.sound_ui_var.get()), "sound_alert": bool(self.sound_alert_var.get()),
                "reveal_delay": self._num(self.rev_var, 8, 1)}
        self.settings = snap
        if snap != self._last_saved:
            self._last_saved = dict(snap)
            save_config(snap)

    def _valid_id(self):
        self._sync()
        if not ID_RE.match(self.settings["discord_id"]):
            self.log("Enter a valid Discord user ID first (17-20 digits).")
            return False
        return True

    def on_toggle(self):
        if not self.running and not self._valid_id():
            return
        self.running = not self.running
        for st in self.states.values():
            st.armed, st.streak, st.gone_since, st.hit = True, 0, None, False
        self.start_btn.configure(text="STOP" if self.running else "START",
                                 fg_color=DANGER if self.running else ACCENT,
                                 text_color="#ffffff" if self.running else ON_ACCENT)
        self.state_pill.configure(text="●  WATCHING" if self.running else "●  STOPPED",
                                  text_color=GREEN if self.running else MUTED)
        self.log("Watching started." if self.running else "Watching stopped.")

    # ------------------------------------------------------------- windows
    # ---------------------------------------------------------------- stats
    def _build_stats(self, tab):
        tab.grid_columnconfigure((0, 1), weight=1)
        tab.grid_rowconfigure(0, weight=1)

        def table(parent, cols, widths, title):
            card = self._card(parent)
            card.grid_columnconfigure(0, weight=1)
            card.grid_rowconfigure(1, weight=1)
            self._label(card, title, 10, MUTED, True).grid(row=0, column=0, sticky="w", padx=18, pady=(14, 6))
            tv = ttk.Treeview(card, columns=[c[0] for c in cols], show="headings", height=10)
            for (cid, name, anchor), w in zip(cols, widths):
                tv.heading(cid, text=name)
                tv.column(cid, width=w, anchor=anchor, stretch=(cid == cols[0][0]))
            tv.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))
            return card, tv

        c1, self.acct_tree = table(tab, (("a", "Account", "w"), ("t", "Today", "center"), ("s", "Session", "center"),
                                         ("all", "Total", "center"), ("l", "Last secret", "center")),
                                   (150, 60, 70, 60, 130), "PER ACCOUNT")
        c1.grid(row=0, column=0, sticky="nsew", padx=(0, 7))
        c2, self.recent_tree = table(tab, (("when", "When", "w"), ("acc", "Account", "w")), (160, 150), "RECENT SECRETS")
        c2.grid(row=0, column=1, sticky="nsew", padx=(7, 0))
        bar = ctk.CTkFrame(tab, fg_color=BG)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 4))
        self._btn(bar, "Export CSV", self.on_export_stats).pack(side="left", padx=(0, 6))
        self._btn(bar, "Reset session", self.on_reset_session).pack(side="left", padx=3)
        ctk.CTkButton(bar, text="Clear secret history", command=self.on_clear_stats, corner_radius=9, height=34,
                      fg_color=DANGER, hover_color="#ff6b6f", text_color="#fff",
                      font=ctk.CTkFont(weight="bold")).pack(side="left", padx=3)
        self._label(bar, "Counts real secret detections only (test alerts aren't counted).", 10).pack(side="right")

    def record_hatch(self, label):
        with self.stats_lock:
            self.stats["history"].append({"t": time.time(), "account": label})
            self.stats["history"] = self.stats["history"][-2000:]
            self.stats["total"] += 1
            self.stats["accounts"][label] = self.stats["accounts"].get(label, 0) + 1
            save_stats(self.stats)
            self.session[label] = self.session.get(label, 0) + 1
            today = datetime.date.today()
            tc = sum(1 for h in self.stats["history"] if datetime.datetime.fromtimestamp(h["t"]).date() == today)
            return {"today": tc, "total": self.stats["total"], "account_total": self.stats["accounts"][label],
                    "session": sum(self.session.values())}

    def _today_count(self):
        today = datetime.date.today()
        with self.stats_lock:
            return sum(1 for h in self.stats["history"] if datetime.datetime.fromtimestamp(h["t"]).date() == today)

    def refresh_stats(self):
        with self.stats_lock:
            hist, accts, total = list(self.stats["history"]), dict(self.stats["accounts"]), self.stats["total"]
        today = datetime.date.today()
        tcount, per_today, last = 0, {}, {}
        for h in hist:
            d = datetime.datetime.fromtimestamp(h["t"])
            last[h["account"]] = d
            if d.date() == today:
                tcount += 1
                per_today[h["account"]] = per_today.get(h["account"], 0) + 1
        self.big["today"].set(tcount)
        self.big["session"].set(sum(self.session.values()))
        self.big["total"].set(total)
        if self.page != "stats":
            return
        names = sorted(set(accts) | set(self.session) | {x.label for x in self.states.values()})
        self.acct_tree.delete(*self.acct_tree.get_children())
        for n in names:
            l = last.get(n)
            self.acct_tree.insert("", "end", values=(n, per_today.get(n, 0), self.session.get(n, 0), accts.get(n, 0),
                                                     l.strftime("%b %d %I:%M %p") if l else "-"))
        self.recent_tree.delete(*self.recent_tree.get_children())
        for h in reversed(hist[-60:]):
            self.recent_tree.insert("", "end", values=(datetime.datetime.fromtimestamp(h["t"]).strftime("%b %d  %I:%M:%S %p"),
                                                       h["account"]))

    def on_export_stats(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="secret_hatches.csv",
                                            filetypes=[("CSV", "*.csv")])
        if not path:
            return
        try:
            with self.stats_lock:
                hist = list(self.stats["history"])
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write("time,account\n")
                for h in hist:
                    f.write(f'{datetime.datetime.fromtimestamp(h["t"]).isoformat(sep=" ", timespec="seconds")},"{h["account"]}"\n')
            self.log(f"Exported {len(hist)} rows to {path}")
        except Exception as e:
            self.log(f"Export failed: {e}")

    def on_reset_session(self):
        self.session = {}
        self.refresh_stats()
        self.log("Session counter reset.")

    def on_clear_stats(self):
        if messagebox.askyesno("Clear secret history", "Delete your whole secret history and reset ALL counts (today, session and all-time)? This can't be undone."):
            with self.stats_lock:
                self.stats = {"total": 0, "accounts": {}, "history": []}
                save_stats(self.stats)
            self.session = {}
            self.refresh_stats()
            self.log("Secret history cleared.")

    # ---------------------------------------------------------------- windows
    def scan_windows(self):
        found = find_roblox_windows(self.name_cache)
        live = {h for h, _, _ in found}
        for hwnd, pid, _ in found:
            if hwnd not in self.states:
                self.counter += 1
                self.states[hwnd] = WinState(hwnd, pid, f"Account {self.counter}")
                self.log(f"Found Account {self.counter} (PID {pid}).")
        for hwnd in list(self.states):
            if hwnd not in live:
                gone = self.states[hwnd]
                self.log(f"{gone.label} closed.")
                if self.running and gone.watch and self.settings["dc_warn"]:
                    threading.Thread(target=self._send_warning,
                                     args=(gone.label, "Roblox window closed (crashed or was closed)", None, dict(self.settings)),
                                     daemon=True).start()
                del self.states[hwnd]
                card = self.cards.pop(hwnd, None)
                if card is not None:
                    card.destroy()
                if hwnd in self.card_order:
                    self.card_order.remove(hwnd)
                if self.selected == hwnd:
                    self.selected = None
                self._layout_cards()
        self._refresh_table()

    def _layout_cards(self):
        for i, hwnd in enumerate(self.card_order):
            c = self.cards.get(hwnd)
            if c is not None:
                c.grid(row=i // 3, column=i % 3, padx=7, pady=7, sticky="n")
        if self.card_order:
            self.empty_lbl.grid_remove()
        else:
            self.empty_lbl.grid()

    def _status_of(self, st):
        if not st.watch:
            return "Not watching", MUTED
        if st.hit:
            return "SECRET!", AMBER
        if st.dc_streak >= 2:
            return "Disconnected?", DANGER
        if not self.running:
            return "Ready", MUTED
        if st.status.startswith("(min)"):
            return "Minimized", GREEN
        if st.status.startswith("Can't") or st.status.startswith("Error"):
            return st.status[:22], DANGER
        return "Watching", GREEN

    def _refresh_table(self):
        n = secret = dc = mini = 0
        rob = 0
        for hwnd, st in list(self.states.items()):
            if hwnd not in self.cards:
                self.cards[hwnd] = AccountCard(self.grid_area, self, st)
                self.card_order.append(hwnd)
                self._layout_cards()
            mem = "-"
            if st.proc is not None:
                try:
                    rss = st.proc.memory_info().rss
                    rob += rss
                    mem = f"{rss / 1048576:.0f} MB"
                except Exception:
                    pass
            text, color = self._status_of(st)
            self.cards[hwnd].refresh(st, mem, text, color, hwnd == self.selected)
            if st.watch:
                n += 1
                if st.hit:
                    secret += 1
                if st.dc_streak >= 2:
                    dc += 1
                if st.status.startswith("(min)"):
                    mini += 1
        total = len(self.states)
        self.ov_big.configure(text=f"{n} / {total}")
        vals = {"w_watch": n - secret - dc, "w_secret": secret, "w_dc": dc, "w_min": mini, "w_off": total - n,
                "pc_rob": f"{rob / 1073741824:.1f} GB", "s_secrets": sum(self.session.values()),
                "s_dc": self.dc_count, "s_fail": self.fail_count}
        try:
            vm = psutil.virtual_memory()
            vals["pc_free"] = f"{vm.available / 1073741824:.1f} / {vm.total / 1073741824:.1f} GB"
            vals["pc_cpu"] = f"{psutil.cpu_percent(None):.0f}%"
        except Exception:
            pass
        for k, v in vals.items():
            if k in self.kv:
                self.kv[k].configure(text=str(v))
        self.title(f"Secret Hatch Notifer+ — watching {n} of {total}  |  secrets today: {self._today_count()}")

    def _pick(self):
        st = self.states.get(self.selected)
        if st is None and len(self.states) == 1:
            st = next(iter(self.states.values()))
        return st

    def _selected(self):
        st = self._pick()
        if st is None:
            self.log("Click an account card first.")
        return st

    def select(self, hwnd):
        self.selected = hwnd
        self._refresh_table()

    def set_watch(self, hwnd, on):
        st = self.states.get(hwnd)
        if st:
            st.watch = on
            st.armed, st.streak, st.gone_since, st.hit = True, 0, None, False
            self._refresh_table()

    def open_view(self, hwnd):
        self.selected = hwnd
        self.on_view()

    def _set_all(self, on):
        for st in self.states.values():
            st.watch = on
            st.armed, st.streak, st.gone_since, st.hit = True, 0, None, False
        self._refresh_table()

    def on_front(self):
        st = self._selected()
        if st:
            bring_to_front(st.hwnd)

    def on_rename(self):
        st = self._selected()
        if not st:
            return
        name = ctk.CTkInputDialog(text=f"New name for {st.label}:", title="Rename account").get_input()
        if name and name.strip():
            st.label = name.strip()[:40]
            self._refresh_table()

    def _preview_worker(self):
        """Keeps the card pictures fresh for windows the watcher isn't scanning right now."""
        while not self.stop.is_set():
            did = False
            for st in list(self.states.values()):
                if self.stop.is_set():
                    break
                if time.time() - st.thumb_t < 4.0:
                    continue
                try:
                    if not win32gui.IsWindow(st.hwnd) or win32gui.IsIconic(st.hwnd):
                        continue
                    frame = snap_window(st.hwnd, allow_peek=False, full=False)
                    if frame is not None and frame.size:
                        st.thumb, st.thumb_t = make_thumb(frame), time.time()
                        st.thumb_v += 1
                except Exception:
                    pass
                did = True
                time.sleep(0.4)
            time.sleep(0.3 if did else 1.0)

    # ----------------------------------------------------------- detection
    def _get_ocr(self):
        with self.ocr_lock:
            if self.ocr is None:
                self.log("Loading text reader (first time only)…")
                from rapidocr_onnxruntime import RapidOCR
                self.ocr = RapidOCR()
            return self.ocr

    def _ocr_text(self, img, target_w):
        if img.width != target_w:
            img = img.resize((target_w, max(1, int(img.height * target_w / img.width))), Image.LANCZOS)
        ocr = self._get_ocr()
        with self.ocr_lock:
            result, _ = ocr(np.asarray(img)[:, :, ::-1])
        return " ".join(r[1] for r in result).strip() if result else ""

    def analyze(self, frame):
        """Returns (hit, reason, text). Cheap black-egg check first, OCR only if that misses."""
        if find_black_egg(frame):
            return True, "secret", ""
        img = Image.fromarray(frame)
        text = self._ocr_text(img, 1600)
        if is_reveal_text(text):
            return True, "Hold to Reveal", text
        w, h = img.size
        text2 = self._ocr_text(img.crop((int(w * .15), int(h * .6), int(w * .85), h)), 1500)
        if is_reveal_text(text2):
            return True, "Hold to Reveal", text2
        return False, "", (text + " " + text2).strip()

    def _worker(self):
        grabber = Grabber()
        while not self.stop.is_set():
            watched = [s for s in list(self.states.values()) if s.watch]
            if not self.running or not watched:
                time.sleep(0.4)
                continue
            for st in watched:
                if self.stop.is_set() or not self.running:
                    break
                if not st.watch or st.hwnd not in self.states:
                    continue
                try:
                    self._check(st, grabber, self.settings)
                except Exception as e:
                    st.hit, st.status = False, "Error: " + str(e)[:40]
            time.sleep(self.settings["interval"])

    def _check(self, st, grabber, s):
        if not win32gui.IsWindow(st.hwnd):
            return
        minimized = bool(win32gui.IsIconic(st.hwnd))
        small = False  # small / half-size windows are scanned as they are, never resized
        if minimized and not s["minimized"]:
            st.hit, st.status = False, "Minimized (watching it is off)"
            return
        if (minimized or small) and time.time() - st.last_peek < s["peek"]:
            return
        if minimized or small:
            st.last_peek = time.time()
        frame = grabber.capture(st.hwnd, "Auto", allow_peek=s["minimized"], full=s["fullsize"])
        if frame is None or frame.size == 0:
            st.hit, st.status = False, "Can't capture this window"
            return
        tag = "(min) " if minimized else ("(big) " if small else "")
        peeked = minimized or small
        now = time.time()
        hit, why = False, ""
        if now - st.thumb_t >= 2.0:
            try:
                st.thumb, st.thumb_t = make_thumb(frame), now
                st.thumb_v += 1
            except Exception:
                pass

        # 1) fast check every scan: the black secret silhouette
        if find_black_egg(frame):
            hit, why = True, "secret"
            if not peeked:  # confirm on a fresh frame a moment later so one odd frame can't ping the channel
                time.sleep(0.35)
                f2 = grabber.capture(st.hwnd, "Auto", allow_peek=False, full=False)
                if f2 is not None and f2.size:
                    if find_black_egg(f2):
                        frame = f2
                    else:
                        hit = False

        # 2) cheap text check (bottom-middle only) every few seconds: the "Hold to Reveal!" button
        if not hit and now - st.last_txt >= 3.0:
            st.last_txt = now
            try:
                im = Image.fromarray(frame)
                w, h = im.size
                if is_reveal_text(self._ocr_text(im.crop((int(w * .2), int(h * .55), int(w * .8), h)), 1100)):
                    hit, why = True, "Hold to Reveal"
            except Exception:
                pass

        # 3) full-screen text read only every 20s, just to spot the Roblox disconnect screen
        dc_checked = dc = False
        if not hit and s["dc_warn"] and now - st.last_full >= 20.0:
            st.last_full = now
            try:
                dc = is_disconnect_text(self._ocr_text(Image.fromarray(frame), 1280))
                dc_checked = True
            except Exception:
                pass
        if dc_checked:
            if dc:
                st.dc_streak += 1
                st.dc_clear = 0
                if st.dc_streak >= 2 and not st.dc_sent and self.running:
                    st.dc_sent = True  # one warning per disconnect, re-arms once the error screen is gone
                    threading.Thread(target=self._send_warning,
                                     args=(st.label, "looks disconnected (Roblox error screen)", frame, dict(s)),
                                     daemon=True).start()
            else:
                st.dc_streak = 0
                st.dc_clear += 1
                if st.dc_clear >= 2:
                    st.dc_sent = False

        st.hit = hit
        if hit:
            st.status = tag + f"SECRET SCREEN! ({why})"
        elif st.dc_streak >= 2:
            st.status = tag + "DISCONNECTED? (Roblox error screen)"
        else:
            st.status = tag + "Watching"

        if hit:
            st.gone_since = None
            if st.armed:  # one alert per secret: fire once, then stay quiet until it has been gone for a while
                st.armed = False
                self.log(f"{st.label}: SECRET detected ({why}). Sending to Discord…")
                if s.get("sound_alert", True):
                    play_sound()
                counts = self.record_hatch(st.label)
                threading.Thread(target=self._send_alert, args=(st, frame, s, False, counts), daemon=True).start()
        else:
            if st.gone_since is None:
                st.gone_since = time.time()
            elif not st.armed and time.time() - st.gone_since >= s["rearm"]:
                st.armed = True  # gone long enough: the next one counts as a new secret
                self.log(f"{st.label}: ready for the next secret.")

    # ------------------------------------------------------- notifications
    def _send_alert(self, st, frame, s, is_test, counts=None):
        uid, label = s["discord_id"], st.label
        pre = "🧪 TEST — " if is_test else ""
        if st.hwnd:
            try:
                snap = snap_window(st.hwnd, allow_peek=s["minimized"], full=s["fullsize"])
                if snap is not None and snap.size and snap.mean() >= 2:
                    frame = snap
            except Exception:
                pass
        try:
            post_discord({"username": "Secret Hatch Notifer+",
                          "content": f"<@{uid}> {pre}🥚 **SECRET HATCH!**",
                          "embeds": [{"title": f"{pre}🔒 A secret is hatching!",
                                      "description": f"Account: **{label}**",
                                      "color": 0xFFA516, "image": {"url": "attachment://secret.jpg"},
                                      **({"footer": {"text": f"Secret #{counts['today']} today  •  #{counts['total']} all time  "
                                                             f"•  {label}: {counts['account_total']} total"}} if counts else {}),
                                      "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()}]},
                         to_jpeg_bytes(frame), ping_id=uid, test=is_test)
            self.log(f"{pre}Alert + picture sent for {label}." + (" (test channel)" if is_test else ""))
        except Exception as e:
            self.fail_count += 1
            self.log(f"Alert failed for {label}: {e}")
            return
        if is_test or st.hwnd == 0 or not s.get("reveal_pic"):
            return  # one picture per secret unless the 2nd (after-reveal) picture is switched on
        time.sleep(s["reveal_delay"])  # let the reveal finish, then send what actually hatched
        try:
            f2 = snap_window(st.hwnd, allow_peek=s["minimized"], full=s["fullsize"])
            if f2 is None or f2.size == 0:
                return
            post_discord({"username": "Secret Hatch Notifer+",
                          "embeds": [{"title": "✨ Secret revealed", "description": f"Account: **{label}**",
                                      "color": 0x2F6BFF, "image": {"url": "attachment://secret.jpg"}}]},
                         to_jpeg_bytes(f2))
            self.log(f"Reveal picture sent for {label}.")
        except Exception as e:
            self.log(f"Reveal picture failed for {label}: {e}")

    def _send_warning(self, label, reason, frame=None, s=None):
        s = s or self.settings
        uid = s["discord_id"]
        if not ID_RE.match(uid or ""):
            return
        embed = {"title": "⚠️ Account needs attention", "description": f"Account: **{label}**\n{reason}",
                 "color": 0xE5484D, "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()}
        img = None
        if frame is not None and getattr(frame, "size", 0):
            embed["image"] = {"url": "attachment://secret.jpg"}
            img = to_jpeg_bytes(frame)
        try:
            post_discord({"username": "Secret Hatch Notifer+", "content": f"<@{uid}> ⚠️ **{label}** {reason}",
                          "embeds": [embed]}, img, ping_id=uid)
            self.dc_count += 1
            self.log(f"Warning sent: {label} {reason}")
        except Exception as e:
            self.log(f"Warning failed for {label}: {e}")

    def on_test_alert(self):
        if not self._valid_id():
            return
        if time.time() - self.last_test < 30:
            self.log("Test alerts are limited to one every 30 seconds.")
            return
        self.last_test = time.time()
        st = self._pick()
        if st is None and len(self.states) == 1:
            st = next(iter(self.states.values()))
        if st is None:
            self.log("Click the Roblox account you want to test in the list first (the test sends only that window).")
            return
        s = dict(self.settings)

        def run():
            try:
                frame = snap_window(st.hwnd, allow_peek=True, full=s["fullsize"])
            except Exception as e:
                self.log(f"Couldn't capture {st.label}: {e}")
                return
            if frame is None or frame.size == 0:
                self.log(f"Couldn't capture {st.label}, so no test was sent.")
                return
            self.log(f"Test picture taken from {st.label} only.")
            self._send_alert(st, frame, s, True)
        threading.Thread(target=run, daemon=True).start()

    def on_view(self):
        """Live preview of what the watcher sees for the selected account. Local only, nothing is sent."""
        st = self._pick()
        if st is None and len(self.states) == 1:
            st = next(iter(self.states.values()))
        if st is None:
            self.log("Click a Roblox account in the list first, then press View screen.")
            return
        win = ctk.CTkToplevel(self)
        win.title(f"Live view: {st.label}")
        win.configure(fg_color=BG)
        win.geometry("860x600")
        img_lbl = ctk.CTkLabel(win, text="Loading…", text_color=MUTED)
        img_lbl.pack(pady=(14, 6), padx=14)
        info = ctk.CTkLabel(win, text="", text_color=TEXT, font=ctk.CTkFont(size=13, weight="bold"))
        info.pack()
        sub = ctk.CTkLabel(win, text="This preview stays on your PC. Nothing is sent to Discord.",
                           text_color=MUTED, font=ctk.CTkFont(size=11))
        sub.pack(pady=(2, 10))
        alive = {"on": True}
        last = {"t": 0.0, "f": None}

        def closed(_e=None):
            alive["on"] = False
        win.bind("<Destroy>", lambda e: closed() if e.widget is win else None)

        def push(frame, egg, note):
            if not alive["on"] or not win.winfo_exists():
                return
            if frame is not None:
                im = Image.fromarray(frame)
                sc = min(820 / im.width, 440 / im.height, 1)
                ci = ctk.CTkImage(light_image=im, dark_image=im,
                                  size=(max(1, int(im.width * sc)), max(1, int(im.height * sc))))
                img_lbl.configure(image=ci, text="")
                img_lbl.image = ci
            else:
                img_lbl.configure(image=None, text=note)
            if frame is not None:
                if egg:
                    info.configure(text="● SECRET DETECTED", text_color=AMBER)
                else:
                    info.configure(text="● Watching: no secret on screen", text_color=GREEN)
                if note == "minimized":
                    info.configure(text=info.cget("text") + "  (minimized, refreshed every few sec)")
                sub.configure(text=f"Status: {st.status}   |   Alerts {'armed' if st.armed else 'waiting for egg to clear'}"
                                   f"   |   {'WATCHING' if self.running else 'STOPPED (press START)'}")
            else:
                info.configure(text=note, text_color=MUTED)

        def loop():
            while alive["on"] and not self.stop.is_set():
                frame = egg = None
                note = ""
                try:
                    if not win32gui.IsWindow(st.hwnd):
                        note = "This Roblox window was closed."
                    elif win32gui.IsIconic(st.hwnd):
                        if not self.settings["minimized"]:
                            note = "Window is minimized and 'Scan minimized windows too' is off."
                        elif time.time() - last["t"] >= self.settings["peek"]:
                            last["t"] = time.time()
                            last["f"] = snap_window(st.hwnd, allow_peek=True, full=self.settings["fullsize"])
                        frame = last["f"]
                        if frame is not None and frame.size:
                            egg = find_black_egg(frame)
                            note = "minimized"
                        else:
                            frame, note = None, "Minimized: waiting for the next check…"
                    else:
                        frame = snap_window(st.hwnd, allow_peek=False, full=False)
                        if frame is not None and frame.size:
                            egg = find_black_egg(frame)
                        else:
                            frame, note = None, "Can't capture this window right now."
                except Exception as e:
                    frame, note = None, f"Capture error: {str(e)[:60]}"
                try:
                    self.after(0, push, frame, egg, note)
                except Exception:
                    break
                time.sleep(1.0)
        threading.Thread(target=loop, daemon=True).start()
        win.after(100, win.focus)

    def on_test_read(self):
        st = self._selected()
        if not st:
            return
        self._sync()

        def run():
            try:
                frame = Grabber().capture(st.hwnd, "Auto", allow_peek=True, full=self.settings["fullsize"])
                if frame is None or frame.size == 0:
                    self.log(f"Test: couldn't capture {st.label}.")
                    return
                hit, why, text = self.analyze(frame)
                self.after(0, lambda: self._show_test(st.label, frame, hit, why, text))
            except Exception as e:
                self.log(f"Test failed: {e}")
        threading.Thread(target=run, daemon=True).start()

    def _show_test(self, label, frame, hit, why, text):
        win = ctk.CTkToplevel(self)
        win.title(f"Detection test: {label}")
        win.configure(fg_color=BG)
        win.geometry("720x520")
        img = Image.fromarray(frame)
        sc = min(680 / img.width, 340 / img.height, 1)
        cimg = ctk.CTkImage(light_image=img, dark_image=img, size=(max(1, int(img.width * sc)), max(1, int(img.height * sc))))
        ctk.CTkLabel(win, image=cimg, text="").pack(pady=(16, 8))
        ctk.CTkLabel(win, text=f'Text read: "{(text or "(nothing)")[:240]}"', text_color=TEXT,
                     wraplength=680, justify="left").pack(padx=16)
        ctk.CTkLabel(win, text=f"SECRET SCREEN DETECTED ({why})" if hit else
                     "Nothing detected (normal if no secret is on screen). Nothing was sent.",
                     text_color=GREEN if hit else MUTED, font=ctk.CTkFont(weight="bold")).pack(pady=(8, 0))
        win.after(100, win.focus)

    def _tick(self):
        self._sync()
        self._tick_n += 1
        if self._tick_n % 4 == 0:
            self.scan_windows()
        else:
            self._refresh_table()
        if self._tick_n % 3 == 0:
            self.refresh_stats()
        self._drain()
        self.after(700, self._tick)

    # --------------------------------------------------------------- updates
    def check_updates(self, manual=False):
        def run():
            if not UPDATE_URL:
                if manual:
                    self.log("Update checking isn't set up in this build (UPDATE_URL is empty).")
                return
            try:
                ver, url, notes, asset = fetch_update_info()
                if ver and parse_version(ver) > parse_version(APP_VERSION):
                    self.after(0, self._show_update, ver, url, notes, asset)
                elif manual:
                    self.log(f"You're up to date (v{APP_VERSION}).")
            except Exception as e:
                if manual:
                    self.log(f"Couldn't check for updates: {str(e)[:80]}")
        threading.Thread(target=run, daemon=True).start()

    def _show_update(self, ver, url, notes, asset):
        self.update_info = (ver, url, notes, asset)
        label = ver if ver.lower().startswith("v") else "v" + ver
        self.update_btn.configure(text=f"⬆  Update to {label}", state="normal")
        self.update_btn.grid()
        if getattr(self, "_update_logged", None) != ver:
            self._update_logged = ver
            self.log(f"NEW UPDATE {label} is available (you have v{APP_VERSION}). Click the Update button at the bottom-left."
                     + (f" {notes[:120]}" if notes else ""))

    def on_update_click(self):
        if not self.update_info or self._updating:
            return
        ver, url, notes, asset = self.update_info
        label = ver if ver.lower().startswith("v") else "v" + ver
        installed = bool(getattr(sys, "frozen", False))
        if not (installed and asset.startswith("https://")):
            if url:  # running from source, or the release has no .exe attached: open the download page
                webbrowser.open(url)
            return
        msg = f"Install {label} now?\n\nThe app will download the update, close, replace itself and reopen."
        if notes.strip():
            msg += "\n\nWhat's new:\n" + notes.strip()[:400]
        if not messagebox.askyesno("Update Secret Hatch Notifer+", msg):
            return
        self._updating = True
        self.update_btn.configure(text="Downloading… 0%", state="disabled")
        self.log(f"Downloading {label}…")

        def fail(e):
            self._updating = False
            self.update_btn.configure(text="⚠  Update failed: click to retry", state="normal")
            self.log(f"Update failed: {str(e)[:120]}")

        def run():
            try:
                folder = os.path.join(tempfile.gettempdir(), "SecretHatchNotiferUpdate")
                os.makedirs(folder, exist_ok=True)
                newexe = os.path.join(folder, "new.exe")
                with requests.get(asset, stream=True, timeout=30, headers={"User-Agent": "SecretHatchNotifer"}) as r:
                    r.raise_for_status()
                    total, got, last = int(r.headers.get("content-length") or 0), 0, -1
                    with open(newexe, "wb") as f:
                        for chunk in r.iter_content(1 << 20):
                            f.write(chunk)
                            got += len(chunk)
                            pct = int(got * 100 / total) if total else 0
                            if pct != last:
                                last = pct
                                self.after(0, lambda p=pct: self.update_btn.configure(text=f"Downloading… {p}%"))
                with open(newexe, "rb") as f:
                    head = f.read(2)
                if got < 5 * 1024 * 1024 or head != b"MZ" or (total and got != total):
                    raise RuntimeError("the downloaded file looks incomplete")
                self.after(0, self._quit_for_update, newexe)
            except Exception as e:
                self.after(0, fail, e)
        threading.Thread(target=run, daemon=True).start()

    def _quit_for_update(self, newexe):
        target = sys.executable
        bat_path = os.path.join(os.path.dirname(newexe), "apply_update.bat")
        bat = (
            "@echo off\r\n"
            "chcp 65001 >nul\r\n"
            "set TRIES=0\r\n"
            ":wait\r\n"
            "ping -n 2 127.0.0.1 >nul\r\n"
            "set /a TRIES+=1\r\n"
            f'move /y "{newexe}" "{target}" >nul 2>&1\r\n'
            "if not errorlevel 1 goto done\r\n"
            "if %TRIES% GEQ 90 goto fail\r\n"
            "goto wait\r\n"
            ":done\r\n"
            "ping -n 3 127.0.0.1 >nul\r\n"
            f'start "" "{target}"\r\n'
            '(goto) 2>nul & del "%~f0"\r\n'
            ":fail\r\n"
            f'start "" "{target}"\r\n'
        )
        with open(bat_path, "w", encoding="utf-8", newline="") as f:
            f.write(bat)
        env = {k: v for k, v in os.environ.items() if not k.startswith(("_PYI", "_MEI"))}
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        subprocess.Popen(["cmd.exe", "/c", bat_path], creationflags=0x08000000 | 0x00000200, close_fds=True, env=env)
        self.log("Update downloaded. Restarting…")
        self.on_close()
        os._exit(0)

    def _periodic_update_check(self):
        self.check_updates(False)
        self.after(6 * 3600 * 1000, self._periodic_update_check)

    def on_close(self):
        self.stop.set()
        self._sync()
        self.destroy()


if __name__ == "__main__":
    App().mainloop()
