"""
Secret Hatch Notifer+
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

import webbrowser
import io, os, re, json, time, queue, ctypes, base64, datetime, threading
import math, struct, wave, hashlib, subprocess

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
import customtkinter as ctk

# Change THEME to "red" for the old black / red look.
THEME = "neon"
if THEME == "red":
    BG, PANEL, PANEL2, BORDER = "#060606", "#0f0f10", "#171718", "#2e1418"
    TEXT, MUTED, BANNER, GREEN = "#f4f0f0", "#9b9091", "#1a0709", "#4ade80"
    ACCENT, ACCENT_HOT, ACCENT_DEEP = "#e11d2e", "#ff4455", "#7f1520"
    VIOLET, BLUE, ON_ACCENT, SELECT = "#7f1520", "#e11d2e", "#ffffff", "#2a0d11"
else:  # navy + orange + violet
    BG, PANEL, PANEL2, BORDER = "#050816", "#0a1030", "#111a40", "#1f2b66"
    TEXT, MUTED, BANNER, GREEN = "#eef1ff", "#8b93c4", "#0d1440", "#4ade80"
    ACCENT, ACCENT_HOT, ACCENT_DEEP = "#ff9f1c", "#ffb84d", "#7a4a0a"
    VIOLET, BLUE, ON_ACCENT, SELECT = "#7c4dff", "#2f6bff", "#0b0f26", "#1a2260"
RED, RED_HOT, RED_DEEP = ACCENT, ACCENT_HOT, ACCENT_DEEP  # names used by older code below

APP_VERSION = "1.1.0"
# Where the app looks for new versions. Use ONE of:
#   - a GitHub releases link:  "https://api.github.com/repos/YOUR-NAME/YOUR-REPO/releases/latest"
#   - a link to a small JSON file you host:
#       {"version": "1.2.0", "download": "https://direct-link-to.exe", "notes": "what's new", "sha256": "(optional)"}
# Leave it empty to turn update checking off.
UPDATE_URL = ""

ROBLOX_EXES = ("robloxplayerbeta.exe", "robloxplayer.exe", "windows10universal.exe")
ID_RE = re.compile(r"^\d{17,20}$")
FULL_W, FULL_H = 1280, 720

def resource_path(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


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
            "fullsize": True, "reveal_delay": 8, "dc_warn": True, "reveal_pic": False, "sounds": True}

# Shared community webhook, kept out of the UI and not stored in plain text.
# (Anyone determined can still extract it from a client; see README notes.)
_P = (
    "AANZExxXQloKAAcaQgRVRhRCDkAMHRxBHhEbRRle"
    "AwQCUlpbWE1aWUNAGkAHWk8eW1hUWVogMz0mRBFp"
    "LRZYEhUfCyI2Wg0aRSJIDj5MJAMkXgwZBkwNHixU"
    "OTV3Vx46KBsJLS4WXEVVJA5JFTc8IQY4Pg0pZBFj"
    "BQ=="
)
_K = b"hw-community-v1"


def _hook():
    raw = base64.b64decode("".join(_P))
    return bytes(c ^ _K[i % len(_K)] for i, c in enumerate(raw)).decode()


def is_reveal_text(text):
    t = re.sub(r"[^a-z0-9]", "", text.lower()).replace("0", "o").replace("1", "l")
    if "holdtoreve" in t or "holdtoreal" in t or "toreveal" in t:
        return True
    return "reveal" in t and "hold" in t


def find_black_egg(frame):
    """True if a big solid-black silhouette (the unrevealed egg/pet) sits near the middle of the frame."""
    if frame is None or frame.size == 0:
        return False
    h, w = frame.shape[:2]
    sw = 480
    small = cv2.resize(frame, (sw, max(1, int(h * sw / w))), interpolation=cv2.INTER_AREA)
    H, W = small.shape[:2]
    dark = (small.max(axis=2) < 16).astype(np.uint8)
    if dark.mean() > 0.55:  # mostly black = loading screen, not an egg
        return False
    dark = cv2.morphologyEx(dark, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    n, _, stats, cents = cv2.connectedComponentsWithStats(dark, connectivity=8)
    lum = small.mean(axis=2)
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        if not (0.05 <= area / float(W * H) <= 0.55):
            continue
        cx, cy = cents[i]
        if not (0.25 * W <= cx <= 0.75 * W and 0.2 * H <= cy <= 0.8 * H):
            continue
        if area / float(bw * bh) < 0.55 or not (0.6 <= bh / float(bw) <= 2.2):
            continue
        if x <= 1 or x + bw >= W - 1:
            continue
        pad = 6
        x0, y0, x1, y1 = max(0, x - pad), max(0, y - pad), min(W, x + bw + pad), min(H, y + bh + pad)
        ring = lum[y0:y1, x0:x1].copy()
        ring[(y - y0):(y - y0 + bh), (x - x0):(x - x0 + bw)] = np.nan
        if np.nanmean(ring) < 20:
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
    """Reads the update link. Works with a GitHub 'latest release' URL or your own small JSON file."""
    r = requests.get(UPDATE_URL, timeout=8, headers={"Accept": "application/json", "User-Agent": "SecretHatchNotifer"})
    r.raise_for_status()
    d = r.json()
    ver = d.get("tag_name") or d.get("version") or ""
    page = d.get("html_url") or d.get("page") or ""
    exe = d.get("download") or ""
    url = d.get("url") or ""
    if url and not exe and url.lower().split("?")[0].endswith(".exe"):
        exe = url
    elif url and not page:
        page = url
    for a in d.get("assets") or []:  # GitHub release: take the attached .exe
        if str(a.get("name", "")).lower().endswith(".exe"):
            exe = a.get("browser_download_url") or exe
            break
    return {"version": str(ver), "page": str(page), "exe": str(exe), "notes": str(d.get("body") or d.get("notes") or ""),
            "sha256": str(d.get("sha256") or "").strip().lower()}


def download_update_file(info, progress=None):
    """Downloads the new exe next to the app's settings and checks it is a real program."""
    url = info["exe"]
    if not url.lower().startswith("https://"):
        raise RuntimeError("the update link must be https")
    folder = os.path.join(APP_DIR, "update")
    os.makedirs(folder, exist_ok=True)
    dest = os.path.join(folder, "new.exe")
    h, done = hashlib.sha256(), 0
    with requests.get(url, stream=True, timeout=30, headers={"User-Agent": "SecretHatchNotifer"}) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length") or 0)
        with open(dest, "wb") as f:
            for chunk in r.iter_content(256 * 1024):
                if not chunk:
                    continue
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress and total:
                    progress(min(100, int(done * 100 / total)))
    with open(dest, "rb") as f:
        head = f.read(2)
    if head != b"MZ" or done < 1_000_000:
        raise RuntimeError("the downloaded file isn't a valid program")
    want = info.get("sha256", "")
    if want and h.hexdigest() != want:
        os.remove(dest)
        raise RuntimeError("the download didn't match its checksum")
    return dest


def launch_updater(new_path):
    """Starts a tiny helper that waits for this app to close, swaps in the new exe, and reopens it."""
    old = sys.executable
    bat = os.path.join(APP_DIR, "update", "apply_update.bat")
    with open(bat, "w", encoding="utf-8") as f:
        f.write("@echo off\r\nset PYINSTALLER_RESET_ENVIRONMENT=1\r\nset N=0\r\n:wait\r\nset /a N+=1\r\n"
                "if %N% GTR 90 exit /b 1\r\nping -n 2 127.0.0.1 >nul\r\n"
                f'move /y "{new_path}" "{old}" >nul 2>&1\r\nif errorlevel 1 goto wait\r\n'
                f'start "" "{old}"\r\n(goto) 2>nul & del "%~f0"\r\n')
    env = os.environ.copy()
    env.pop("_MEIPASS2", None)
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    subprocess.Popen(["cmd", "/c", bat], env=env, creationflags=0x08000000 | 0x00000008, close_fds=True)


# --------------------------------------------------------------------------
# Button / click sounds (tiny tones generated on first run, played with winsound)
# --------------------------------------------------------------------------
SOUND_DIR = os.path.join(APP_DIR, "sounds")
_TONES = {"click": [(1450, 28)], "toggle": [(1000, 26), (1500, 34)],
          "start": [(660, 70), (990, 120)], "stop": [(990, 70), (520, 130)],
          "error": [(300, 110), (230, 150)], "update": [(880, 70), (1175, 70), (1568, 130)]}
_SOUND_PATHS, _SOUND_ON = {}, True


def _write_tone(path, notes, vol=0.28, rate=22050):
    frames = bytearray()
    for freq, ms in notes:
        n = int(rate * ms / 1000)
        for i in range(n):
            env = min(1.0, i / (rate * 0.004)) * (1 - i / n) ** 1.6
            frames += struct.pack("<h", int(32767 * vol * env * math.sin(2 * math.pi * freq * i / rate)))
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))


def init_sounds():
    try:
        os.makedirs(SOUND_DIR, exist_ok=True)
        for name, notes in _TONES.items():
            path = os.path.join(SOUND_DIR, f"{name}_v1.wav")
            if not os.path.exists(path) or os.path.getsize(path) < 100:
                _write_tone(path, notes)
            _SOUND_PATHS[name] = path
    except Exception:
        pass


def set_sounds(on):
    global _SOUND_ON
    _SOUND_ON = bool(on)


def play_sound(name):
    path = _SOUND_PATHS.get(name)
    if not _SOUND_ON or not path:
        return
    try:
        import winsound
        winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
    except Exception:
        pass


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
    if img.width > max_width:
        img = img.resize((max_width, int(img.height * max_width / img.width)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def post_discord(payload, image_bytes=None, ping_id=None):
    payload = dict(payload)
    payload["allowed_mentions"] = {"users": [ping_id]} if ping_id else {"parse": []}
    if image_bytes:
        r = requests.post(_hook(), data={"payload_json": json.dumps(payload)},
                          files={"files[0]": ("secret.jpg", image_bytes, "image/jpeg")}, timeout=20)
    else:
        r = requests.post(_hook(), json=payload, timeout=20)
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
    """True if the frame is missing or any quarter of it is pure black (a partial window capture)."""
    if frame is None or frame.size == 0:
        return True
    h, w = frame.shape[:2]
    if h < 20 or w < 20:
        return True
    for ys in (slice(0, h // 2), slice(h // 2, h)):
        for xs in (slice(0, w // 2), slice(w // 2, w)):
            if frame[ys, xs][::8, ::8].max() < 8:
                return True
    return False


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

    def grab_full(self, hwnd, mode, settle=0.8):
        """Briefly enlarge a small window to a normal size so the game draws its whole view, capture it,
        then put the window back exactly where it was. Never steals focus."""
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        w, h = right - left, bottom - top
        _, _, cw, ch = client_geometry(hwnd)
        new_w = max(w, FULL_W + (w - cw))
        new_h = max(h, FULL_H + (h - ch))
        flags = win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE
        try:
            win32gui.SetWindowPos(hwnd, 0, left, top, new_w, new_h, flags)
            time.sleep(settle)  # let the game redraw at the bigger size
            return self.grab(hwnd, mode)
        finally:
            try:
                win32gui.SetWindowPos(hwnd, 0, left, top, w, h, flags)
            except Exception:
                pass

    def peek(self, hwnd, mode, settle=1.2, full=False):
        """Briefly restore a minimized window WITHOUT taking focus, capture it, minimize it again."""
        try:
            win32gui.ShowWindow(hwnd, win32con.SW_SHOWNOACTIVATE)
            time.sleep(settle)  # give the game time to draw a fresh frame
            for attempt in range(2):
                if full and not win32gui.IsZoomed(hwnd):
                    frame = self.grab_full(hwnd, mode)
                else:
                    frame = self.grab(hwnd, mode)
                if frame is not None and frame.size and frame.mean() >= 2:
                    return frame
                time.sleep(0.8)  # still black: give it one more moment
            return frame
        finally:
            try:
                win32gui.ShowWindow(hwnd, win32con.SW_SHOWMINNOACTIVE)
            except Exception:
                pass

    def capture(self, hwnd, mode, allow_peek=True, full=False):
        if win32gui.IsIconic(hwnd):
            return self.peek(hwnd, mode, full=full) if allow_peek else None
        if full and is_small(hwnd):
            return self.grab_full(hwnd, mode)
        return self.grab(hwnd, mode)



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


class WinState:
    def __init__(self, hwnd, pid, label):
        self.hwnd, self.pid, self.label = hwnd, pid, label
        self.watch, self.armed = True, True
        self.streak = 0
        self.last_peek = 0.0
        self.gone_since = None
        self.dc_streak = self.dc_clear = 0
        self.last_txt = self.last_full = 0.0
        self.dc_sent = False
        self.hit = False
        self.status = "Starting…"
        try:
            self.proc = psutil.Process(pid)
            self.proc.cpu_percent(None)
        except Exception:
            self.proc = None


class RoundButton(ctk.CTkFrame):
    """A true circle button: a round frame with a centered label."""

    def __init__(self, parent, text, command, size=84):
        self._cmd, self._hover, self._base = command, ACCENT_HOT, ACCENT
        super().__init__(parent, width=size, height=size, corner_radius=size // 2, fg_color=ACCENT)
        self.pack_propagate(False)
        self.lbl = ctk.CTkLabel(self, text=text, text_color=ON_ACCENT, font=ctk.CTkFont(size=15, weight="bold"))
        self.lbl.place(relx=0.5, rely=0.5, anchor="center")
        for w in (self, self.lbl):
            w.bind("<Button-1>", lambda e: self._cmd())
            w.bind("<Enter>", lambda e: super(RoundButton, self).configure(fg_color=self._hover))
            w.bind("<Leave>", lambda e: super(RoundButton, self).configure(fg_color=self._base))
            w.configure(cursor="hand2")

    def configure(self, **kw):
        if "text" in kw:
            self.lbl.configure(text=kw.pop("text"))
        if "text_color" in kw:
            self.lbl.configure(text_color=kw.pop("text_color"))
        if "hover_color" in kw:
            self._hover = kw.pop("hover_color")
        if "fg_color" in kw:
            self._base = kw["fg_color"]
        if kw:
            super().configure(**kw)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.title("Secret Hatch Notifer+")
        try:  # size the window to the screen so the whole UI fits without going fullscreen
            sc = self._get_window_scaling()
        except Exception:
            sc = 1.0
        w = int(min(1060, self.winfo_screenwidth() / sc * 0.94))
        h = int(min(700, self.winfo_screenheight() / sc * 0.86))
        self.geometry(f"{w}x{h}+{max(0, int((self.winfo_screenwidth() / sc - w) / 2))}+{max(0, int((self.winfo_screenheight() / sc - h) / 2 - 20))}")
        self.minsize(min(880, w), min(520, h))
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
        self.update_info = None
        self.page = "Watcher"
        init_sounds()
        self._tick_n = 0
        self._last_saved = None
        self._build_ui()
        self._sync()
        self.show_page("Watcher", quiet=True)
        self.scan_windows()
        self.after(700, self._tick)
        self.after(4000, self._periodic_update_check)
        threading.Thread(target=self._worker, daemon=True).start()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.log("Ready. Enter your Discord ID, then press START.")

    # ------------------------------------------------------------------ UI
    def _card(self, parent, accent=False, glow=None):
        return ctk.CTkFrame(parent, fg_color=BANNER if accent else PANEL, corner_radius=14,
                            border_width=2 if (glow or accent) else 1,
                            border_color=glow or (ACCENT_DEEP if accent else BORDER))

    def _btn(self, parent, text, cmd, primary=False, width=None, height=34, kind=None):
        def run():
            play_sound("click")
            cmd()
        kw = dict(text=text, command=run, corner_radius=10, height=height)
        if width:
            kw["width"] = width
        if primary:
            return ctk.CTkButton(parent, fg_color=ACCENT, hover_color=ACCENT_HOT, text_color=ON_ACCENT,
                                 font=ctk.CTkFont(weight="bold"), **kw)
        if kind == "violet":
            return ctk.CTkButton(parent, fg_color=VIOLET, hover_color=BLUE, text_color="#ffffff",
                                 font=ctk.CTkFont(weight="bold"), **kw)
        return ctk.CTkButton(parent, fg_color=PANEL2, hover_color=SELECT, border_width=1,
                             border_color=BORDER, text_color=TEXT, **kw)

    def _label(self, parent, text, size=11, color=MUTED, bold=False, **kw):
        return ctk.CTkLabel(parent, text=text, text_color=color,
                            font=ctk.CTkFont(size=size, weight="bold" if bold else "normal"), **kw)

    def _switch(self, parent, text, var):
        return ctk.CTkSwitch(parent, text=text, variable=var, text_color=TEXT, progress_color=ACCENT,
                             button_color=TEXT, button_hover_color="#ffffff", fg_color=BORDER,
                             command=self._on_opt)

    def _on_opt(self):
        play_sound("toggle")
        self._sync()

    def _gauge(self, parent, key, title, color):
        box = ctk.CTkFrame(parent, fg_color=PANEL)
        ring = ctk.CTkFrame(box, width=92, height=92, corner_radius=46, fg_color=PANEL2,
                            border_width=4, border_color=color)
        ring.pack()
        ring.pack_propagate(False)
        self.big[key] = ctk.CTkLabel(ring, text="0", text_color=TEXT, font=ctk.CTkFont(size=28, weight="bold"))
        self.big[key].place(relx=0.5, rely=0.5, anchor="center")
        self._label(box, title, 10, MUTED, True).pack(pady=(6, 0))
        return box

    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.big = {}

        # ---- top navigation bar
        nav = ctk.CTkFrame(self, fg_color=PANEL, corner_radius=0, height=54)
        nav.grid(row=0, column=0, sticky="ew")
        nav.grid_columnconfigure(3, weight=1)
        ctk.CTkFrame(nav, width=22, height=22, corner_radius=11, fg_color=ACCENT).grid(
            row=0, column=0, padx=(20, 10), pady=16)
        self._label(nav, "SECRET HATCH NOTIFER+", 15, TEXT, True).grid(row=0, column=1, sticky="w")
        self._label(nav, f"v{APP_VERSION}", 10, MUTED).grid(row=0, column=2, sticky="w", padx=(8, 18))
        self.nav_btns = {}
        navbox = ctk.CTkFrame(nav, fg_color=PANEL)
        navbox.grid(row=0, column=4, padx=(0, 10))
        for i, name in enumerate(("Watcher", "Stats", "Settings")):
            b = ctk.CTkButton(navbox, text=name, width=88, height=32, corner_radius=16,
                              font=ctk.CTkFont(size=12, weight="bold"),
                              command=lambda n=name: self.show_page(n))
            b.grid(row=0, column=i, padx=3)
            self.nav_btns[name] = b
        self.update_btn = ctk.CTkButton(nav, text="", corner_radius=16, height=32, fg_color=VIOLET, hover_color=BLUE,
                                        text_color="#ffffff", font=ctk.CTkFont(size=12, weight="bold"))
        self.update_btn.grid(row=0, column=5, padx=(0, 10))
        self.update_btn.grid_remove()
        self.state_pill = ctk.CTkLabel(nav, text="  ● STOPPED  ", text_color=MUTED, fg_color=PANEL2,
                                       corner_radius=14, height=30, font=ctk.CTkFont(size=12, weight="bold"))
        self.state_pill.grid(row=0, column=6, padx=(0, 20))
        ctk.CTkFrame(self, height=2, corner_radius=0, fg_color=BORDER).grid(row=0, column=0, sticky="sew")

        # ---- pages (scrollable, so nothing is ever cut off in a small window)
        self.body = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self.body.grid(row=1, column=0, sticky="nsew")
        self.body.grid_columnconfigure(0, weight=1)
        self.body.grid_rowconfigure(0, weight=1)
        self.pages = {}
        for name in ("Watcher", "Stats", "Settings"):
            pg = ctk.CTkScrollableFrame(self.body, fg_color=BG, corner_radius=0, scrollbar_button_color=BORDER,
                                        scrollbar_button_hover_color=ACCENT_DEEP)
            pg.grid(row=0, column=0, sticky="nsew", padx=(14, 6), pady=(10, 8))
            self.pages[name] = pg
        self._build_watcher(self.pages["Watcher"])
        self._build_stats(self.pages["Stats"])
        self._build_settings(self.pages["Settings"])

    def show_page(self, name, quiet=False):
        if not quiet:
            play_sound("click")
        self.page = name
        for n, pg in self.pages.items():
            if n == name:
                pg.grid()
            else:
                pg.grid_remove()
        for n, b in self.nav_btns.items():
            on = n == name
            b.configure(fg_color=ACCENT if on else PANEL2, hover_color=ACCENT_HOT if on else SELECT,
                        text_color=ON_ACCENT if on else TEXT)
        if name == "Stats":
            self.refresh_stats(True)

    def _build_watcher(self, pg):
        pg.grid_columnconfigure(0, weight=0, minsize=330)
        pg.grid_columnconfigure(1, weight=1)
        left = ctk.CTkFrame(pg, fg_color=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        right = ctk.CTkFrame(pg, fg_color=BG)
        right.grid(row=0, column=1, sticky="nsew")
        right.grid_columnconfigure(0, weight=1)

        # ================= LEFT: control + counters =================
        ctl = self._card(left, glow=ACCENT)
        ctl.pack(fill="x", pady=(0, 10))
        self._label(ctl, "CONTROL CENTER", 10, ACCENT, True).pack(anchor="w", padx=16, pady=(12, 0))
        self._label(ctl, "Your Discord user ID", 14, TEXT, True).pack(anchor="w", padx=16)
        self.id_var = ctk.StringVar(value=self.cfg["discord_id"])
        ctk.CTkEntry(ctl, textvariable=self.id_var, fg_color=PANEL2, border_color=BORDER, height=36, corner_radius=10,
                     placeholder_text="e.g. 123456789012345678").pack(fill="x", padx=16, pady=(6, 0))
        self._label(ctl, "Discord → Settings → Advanced → Developer Mode ON, then right-click your name → Copy User ID.",
                    9, wraplength=290, justify="left").pack(anchor="w", padx=16, pady=(5, 8))
        row = ctk.CTkFrame(ctl, fg_color=BANNER)
        row.pack(fill="x", padx=16, pady=(0, 6))
        self.start_btn = RoundButton(row, "START", self.on_toggle, size=84)
        self.start_btn.pack(side="left")
        col = ctk.CTkFrame(row, fg_color=BANNER)
        col.pack(side="left", fill="x", expand=True, padx=(14, 0))
        self._btn(col, "Send test alert", self.on_test_alert, height=36).pack(fill="x")
        self._btn(col, "View screen", self.on_view, kind="violet", height=32).pack(fill="x", pady=(8, 0))
        self._label(ctl, "Only a picture of the Roblox window goes to the shared channel, and only when a secret is "
                         "detected or you press a test button.",
                    9, wraplength=290, justify="left").pack(anchor="w", padx=16, pady=(4, 12))

        gc = self._card(left)
        gc.pack(fill="x")
        gc.grid_columnconfigure((0, 1, 2), weight=1, uniform="g")
        self._gauge(gc, "today", "TODAY", ACCENT).grid(row=0, column=0, pady=12)
        self._gauge(gc, "session", "SESSION", VIOLET).grid(row=0, column=1, pady=12)
        self._gauge(gc, "total", "ALL TIME", BLUE).grid(row=0, column=2, pady=12)

        # ================= RIGHT: windows + activity =================
        mid = self._card(right)
        mid.grid(row=0, column=0, sticky="nsew", pady=(0, 10))
        mid.grid_columnconfigure(0, weight=1)
        self._label(mid, "Roblox windows", 14, TEXT, True).grid(row=0, column=0, sticky="w", padx=16, pady=(12, 0))
        self._label(mid, "Click ☑ to pick windows to watch. Double-click a name to rename it.",
                    10).grid(row=1, column=0, sticky="w", padx=16, pady=(0, 6))
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT, rowheight=28,
                        borderwidth=0, bordercolor=PANEL, lightcolor=PANEL, darkcolor=PANEL, font=("Segoe UI", 10))
        style.configure("Treeview.Heading", background=PANEL2, foreground=ACCENT, relief="flat",
                        font=("Segoe UI", 9, "bold"))
        style.map("Treeview", background=[("selected", SELECT)], foreground=[("selected", TEXT)])
        wrap = ctk.CTkFrame(mid, fg_color=PANEL, corner_radius=0)
        wrap.grid(row=2, column=0, sticky="nsew", padx=14)
        wrap.grid_columnconfigure(0, weight=1)
        cols = ("watch", "name", "pid", "mem", "cpu", "up", "status")
        self.tree = ttk.Treeview(wrap, columns=cols, show="headings", selectmode="browse", height=5)
        for c, t, w, a in (("watch", "Watch", 58, "center"), ("name", "Account", 105, "w"),
                           ("pid", "PID", 55, "center"), ("mem", "Memory", 70, "center"),
                           ("cpu", "CPU", 50, "center"), ("up", "Uptime", 68, "center"),
                           ("status", "Status", 150, "w")):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor=a, stretch=(c == "status"), minwidth=40)
        self.tree.tag_configure("hit", foreground=ACCENT_HOT)
        self.tree.tag_configure("off", foreground=MUTED)
        self.tree.grid(row=0, column=0, sticky="nsew")
        self.tree.bind("<Button-1>", self._on_tree_click)
        self.tree.bind("<Double-1>", lambda e: self.on_rename())
        bar = ctk.CTkFrame(mid, fg_color=PANEL)
        bar.grid(row=3, column=0, sticky="ew", padx=14, pady=(10, 12))
        self._btn(bar, "Scan now", self.scan_windows, primary=True, width=90).pack(side="left", padx=(0, 5))
        self._btn(bar, "Test detection", self.on_test_read, width=116).pack(side="left", padx=3)
        self._btn(bar, "Rename", self.on_rename, width=74).pack(side="left", padx=3)
        self._btn(bar, "To front", self.on_front, width=76).pack(side="left", padx=3)
        self._btn(bar, "All", lambda: self._set_all(True), width=44).pack(side="left", padx=3)
        self._btn(bar, "None", lambda: self._set_all(False), width=52).pack(side="left", padx=3)

        lg = self._card(right)
        lg.grid(row=1, column=0, sticky="nsew")
        self._label(lg, "Activity", 14, TEXT, True).pack(anchor="w", padx=16, pady=(10, 0))
        self.logbox = ctk.CTkTextbox(lg, height=96, fg_color=PANEL2, text_color=TEXT, border_width=0, corner_radius=10,
                                     font=ctk.CTkFont(family="Consolas", size=11), wrap="word")
        self.logbox.pack(fill="both", expand=True, padx=12, pady=(4, 12))
        self.logbox.configure(state="disabled")

    def _build_settings(self, pg):
        pg.grid_columnconfigure((0, 1), weight=1, uniform="s")

        # ---- detection
        d = self._card(pg)
        d.grid(row=0, column=0, sticky="nsew", padx=(0, 6), pady=(0, 10))
        self._label(d, "Detection", 15, TEXT, True).pack(anchor="w", padx=18, pady=(14, 0))
        self._label(d, "How often and how carefully your Roblox windows are checked.", 10
                    ).pack(anchor="w", padx=18, pady=(0, 8))
        grid = ctk.CTkFrame(d, fg_color=PANEL)
        grid.pack(fill="x", padx=18)
        grid.grid_columnconfigure((0, 1), weight=1)
        self.cool_var = ctk.StringVar(value=str(self.cfg["rearm"]))
        self.int_var = ctk.StringVar(value=str(self.cfg["interval"]))
        self.rev_var = ctk.StringVar(value=str(self.cfg["reveal_delay"]))
        self.peek_var = ctk.StringVar(value=str(self.cfg["peek"]))
        fields = (("RE-ARM AFTER EGG GONE (S)", self.cool_var), ("SCAN EVERY (S)", self.int_var),
                  ("REVEAL PIC AFTER (S)", self.rev_var), ("CHECK MINIMIZED EVERY (S)", self.peek_var))
        for i, (txt, var) in enumerate(fields):
            r, c = divmod(i, 2)
            self._label(grid, txt, 9, MUTED, True).grid(row=r * 2, column=c, sticky="w",
                                                         padx=(0, 8) if c == 0 else (8, 0), pady=(0 if r == 0 else 10, 0))
            ctk.CTkEntry(grid, textvariable=var, fg_color=PANEL2, border_color=BORDER, height=32, corner_radius=8
                         ).grid(row=r * 2 + 1, column=c, sticky="ew", padx=(0, 8) if c == 0 else (8, 0))
        self.min_var = ctk.BooleanVar(value=self.cfg["minimized"])
        self.full_var = ctk.BooleanVar(value=self.cfg["fullsize"])
        self.dc_var = ctk.BooleanVar(value=self.cfg["dc_warn"])
        self.rev_pic_var = ctk.BooleanVar(value=self.cfg["reveal_pic"])
        sw = ctk.CTkFrame(d, fg_color=PANEL)
        sw.pack(fill="x", padx=18, pady=(16, 16))
        for txt, var in (("Scan minimized windows too", self.min_var), ("Scan small windows at full size", self.full_var),
                         ("Warn me if an account disconnects", self.dc_var),
                         ("Also send a 2nd picture after reveal", self.rev_pic_var)):
            self._switch(sw, txt, var).pack(anchor="w", pady=5)

        # ---- app
        a = self._card(pg)
        a.grid(row=0, column=1, sticky="nsew", padx=(6, 0), pady=(0, 10))
        self._label(a, "App", 15, TEXT, True).pack(anchor="w", padx=18, pady=(14, 8))
        self.sound_var = ctk.BooleanVar(value=self.cfg["sounds"])
        sw2 = ctk.CTkFrame(a, fg_color=PANEL)
        sw2.pack(fill="x", padx=18)
        self._switch(sw2, "UI button sounds", self.sound_var).pack(anchor="w", pady=4)
        self._label(a, "UPDATES", 9, MUTED, True).pack(anchor="w", padx=18, pady=(16, 2))
        self._label(a, f"You have v{APP_VERSION}.", 12, TEXT).pack(anchor="w", padx=18)
        self.update_note = self._label(a, "Updates install from inside the app: when one is out, a purple "
                                          "button appears at the top. Click it, then Yes.",
                                       10, wraplength=330, justify="left")
        self.update_note.pack(anchor="w", padx=18, pady=(2, 8))
        self._btn(a, "Check for updates", lambda: self.check_updates(True), primary=True).pack(anchor="w", padx=18, pady=(0, 16))

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
                "reveal_delay": self._num(self.rev_var, 8, 1), "sounds": bool(self.sound_var.get())}
        self.settings = snap
        set_sounds(snap["sounds"])
        if snap != self._last_saved:
            self._last_saved = dict(snap)
            save_config(snap)

    def _valid_id(self):
        self._sync()
        if not ID_RE.match(self.settings["discord_id"]):
            self.log("Enter a valid Discord user ID first (17-20 digits).")
            play_sound("error")
            return False
        return True

    def on_toggle(self):
        if not self.running and not self._valid_id():
            return
        self.running = not self.running
        play_sound("start" if self.running else "stop")
        for st in self.states.values():
            st.armed, st.streak, st.gone_since, st.hit = True, 0, None, False
        if self.running:
            self.start_btn.configure(text="STOP", fg_color=VIOLET, hover_color=BLUE, text_color="#ffffff")
        else:
            self.start_btn.configure(text="START", fg_color=ACCENT, hover_color=ACCENT_HOT, text_color=ON_ACCENT)
        self.state_pill.configure(text="  ● WATCHING  " if self.running else "  ● STOPPED  ",
                                  text_color=GREEN if self.running else MUTED)
        self.log("Watching started." if self.running else "Watching stopped.")

    # ---------------------------------------------------------------- stats
    def _build_stats(self, pg):
        pg.grid_columnconfigure((0, 1), weight=1, uniform="s")

        def table(col, cols, widths, title):
            card = self._card(pg)
            card.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 6, 6 if col == 0 else 0), pady=(0, 10))
            card.grid_columnconfigure(0, weight=1)
            self._label(card, title, 15, TEXT, True).grid(row=0, column=0, sticky="w", padx=18, pady=(14, 6))
            tv = ttk.Treeview(card, columns=[c[0] for c in cols], show="headings", height=12)
            for (cid, name, anchor), w in zip(cols, widths):
                tv.heading(cid, text=name)
                tv.column(cid, width=w, anchor=anchor, stretch=(cid == cols[0][0]), minwidth=40)
            tv.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 14))
            return tv

        self.acct_tree = table(0, (("a", "Account", "w"), ("t", "Today", "center"), ("s", "Session", "center"),
                                   ("all", "Total", "center"), ("l", "Last secret", "center")),
                               (130, 55, 65, 55, 120), "Per account")
        self.recent_tree = table(1, (("when", "When", "w"), ("acc", "Account", "w")), (160, 140), "Recent secrets")
        bar = self._card(pg)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew")
        inner = ctk.CTkFrame(bar, fg_color=PANEL)
        inner.pack(fill="x", padx=14, pady=12)
        self._btn(inner, "Export CSV", self.on_export_stats).pack(side="left", padx=(0, 6))
        self._btn(inner, "Reset session", self.on_reset_session).pack(side="left", padx=3)
        self._btn(inner, "Clear secret history", self.on_clear_stats, primary=True).pack(side="left", padx=3)
        self._label(inner, "Real secret detections only (tests aren't counted).", 10).pack(side="right")

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

    def refresh_stats(self, tables=True):
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
        self.big["today"].configure(text=str(tcount))
        self.big["session"].configure(text=str(sum(self.session.values())))
        self.big["total"].configure(text=str(total))
        if not tables:
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
                if self.tree.exists(str(hwnd)):
                    self.tree.delete(str(hwnd))
        self._refresh_table()

    def _refresh_table(self):
        n = 0
        for hwnd, st in list(self.states.items()):
            mem = cpu = up = "-"
            if st.proc is not None:
                try:
                    mem = f"{st.proc.memory_info().rss / 1048576:.0f} MB"
                    cpu = f"{st.proc.cpu_percent(None) / max(1, psutil.cpu_count()):.1f}%"
                    up = fmt_uptime(time.time() - st.proc.create_time())
                except Exception:
                    pass
            status = st.status if st.watch else "Not watching"
            tags = ("hit",) if (st.hit and st.watch) else (() if st.watch else ("off",))
            vals = ("☑" if st.watch else "☐", st.label, st.pid, mem, cpu, up, status)
            if self.tree.exists(str(hwnd)):
                self.tree.item(str(hwnd), values=vals, tags=tags)
            else:
                self.tree.insert("", "end", iid=str(hwnd), values=vals, tags=tags)
            n += 1 if st.watch else 0
        self.title(f"Secret Hatch Notifer+ — watching {n} of {len(self.states)}  |  secrets today: {self._today_count()}")

    def _selected(self):
        sel = self.tree.selection()
        if not sel:
            self.log("Select a window in the list first.")
            return None
        return self.states.get(int(sel[0]))

    def _on_tree_click(self, event):
        if self.tree.identify_region(event.x, event.y) == "cell" and self.tree.identify_column(event.x) == "#1":
            iid = self.tree.identify_row(event.y)
            if iid and int(iid) in self.states:
                st = self.states[int(iid)]
                st.watch = not st.watch
                st.armed, st.streak, st.gone_since, st.hit = True, 0, None, False
                self._refresh_table()

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
        small = (not minimized) and s["fullsize"] and is_small(st.hwnd)
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
                                      "color": 0xE11D2E, "image": {"url": "attachment://secret.jpg"},
                                      **({"footer": {"text": f"Secret #{counts['today']} today  •  #{counts['total']} all time  "
                                                             f"•  {label}: {counts['account_total']} total"}} if counts else {}),
                                      "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()}]},
                         to_jpeg_bytes(frame), ping_id=uid)
            self.log(f"{pre}Alert + picture sent for {label}.")
        except Exception as e:
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
                                      "color": 0x7F1520, "image": {"url": "attachment://secret.jpg"}}]},
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
                 "color": 0xF59E0B, "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()}
        img = None
        if frame is not None and getattr(frame, "size", 0):
            embed["image"] = {"url": "attachment://secret.jpg"}
            img = to_jpeg_bytes(frame)
        try:
            post_discord({"username": "Secret Hatch Notifer+", "content": f"<@{uid}> ⚠️ **{label}** {reason}",
                          "embeds": [embed]}, img, ping_id=uid)
            self.log(f"Warning sent: {label} {reason}")
        except Exception as e:
            self.log(f"Warning failed for {label}: {e}")

    def on_test_alert(self):
        if not self._valid_id():
            return
        if time.time() - self.last_test < 20:
            self.log("Test alerts are limited to one every 20 seconds (it posts to the shared channel).")
            return
        self.last_test = time.time()
        sel = self.tree.selection()
        st = self.states.get(int(sel[0])) if sel else None
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
        sel = self.tree.selection()
        st = self.states.get(int(sel[0])) if sel else None
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
                    info.configure(text="● SECRET DETECTED", text_color=RED_HOT)
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
            self.refresh_stats(tables=(self.page == "Stats"))
        self._drain()
        self.after(700, self._tick)

    # --------------------------------------------------------------- updates
    def check_updates(self, manual=False):
        def run():
            if not UPDATE_URL:
                if manual:
                    self.log("Updates aren't set up in this build yet (UPDATE_URL is empty).")
                return
            try:
                info = fetch_update_info()
                if info["version"] and parse_version(info["version"]) > parse_version(APP_VERSION):
                    self.after(0, self._show_update, info)
                elif manual:
                    self.log(f"You're up to date (v{APP_VERSION}).")
            except Exception as e:
                if manual:
                    self.log(f"Couldn't check for updates: {str(e)[:80]}")
        threading.Thread(target=run, daemon=True).start()

    def _show_update(self, info):
        self.update_info = info
        ver = info["version"]
        label = ver if ver.lower().startswith("v") else "v" + ver
        self.update_btn.configure(text=f"⬆  Update {label}: click to install", state="normal",
                                  command=self.on_update_click)
        self.update_btn.grid()
        if getattr(self, "_update_logged", None) != ver:
            self._update_logged = ver
            play_sound("update")
            self.log(f"NEW UPDATE {label} is available (you have v{APP_VERSION})."
                     + (f" {info['notes'][:120]}" if info["notes"] else ""))

    def on_update_click(self):
        info = self.update_info
        if not info:
            return
        play_sound("click")
        can_self = bool(getattr(sys, "frozen", False)) and info["exe"].lower().startswith("https://")
        text = (f"Version {info['version']} is available (you have v{APP_VERSION}).\n\n"
                + (info["notes"][:600] + "\n\n" if info["notes"] else "")
                + ("Install it now? The app closes and reopens by itself." if can_self
                   else "Open the download page?"))
        if not messagebox.askyesno("Update available", text):
            return
        if can_self:
            self._download_update(info)
        else:
            webbrowser.open(info["page"] or info["exe"])

    def _download_update(self, info):
        self.update_btn.configure(state="disabled", text="Downloading update… 0%")

        def progress(p):
            self.after(0, lambda: self.update_btn.configure(text=f"Downloading update… {p}%"))

        def run():
            try:
                path = download_update_file(info, progress)
                launch_updater(path)
            except Exception as e:
                self.log(f"Update failed: {str(e)[:120]}")
                play_sound("error")
                self.after(0, lambda: self.update_btn.configure(state="normal", text="⬆  Update failed: click to retry"))
                return
            self.log("Update downloaded. Restarting…")
            self.after(300, self._quit_for_update)
        threading.Thread(target=run, daemon=True).start()

    def _quit_for_update(self):
        self.stop.set()
        self.destroy()
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
