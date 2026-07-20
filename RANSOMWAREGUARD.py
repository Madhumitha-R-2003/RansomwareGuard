"""
╔══════════════════════════════════════════════════════════════════════╗
║   RansomwareGuard v5.3.4  —  Smart Backup Vault + Instant Restore   ║
║   Built on v5.3.3  ·  All existing features preserved               ║
║                                                                      ║
║  NEW IN v5.3.4:                                                      ║
║                                                                      ║
║  FEATURE 1 — SMART BACKUP LOCATION (BACKUP_DIR)                     ║
║    BACKUP_DIR is derived as a sibling of WATCH_PATH (one level up)  ║
║    with the suffix "_RG_Vault". This avoids the infinite-loop bug    ║
║    where the observer would re-trigger on its own backup writes.     ║
║                                                                      ║
║  FEATURE 2 — INITIAL FULL MIRROR (initial_sync)                     ║
║    initial_sync() is called on engine start. It uses                 ║
║    shutil.copytree to create a perfect mirror of WATCH_PATH into     ║
║    BACKUP_DIR. If BACKUP_DIR already exists it updates only files    ║
║    whose mtime or size differs — no full re-copy on every start.     ║
║                                                                      ║
║  FEATURE 3 — REAL-TIME BACKUP ON CREATED / MODIFIED                 ║
║    on_created / on_modified handlers immediately copy any new or     ║
║    changed file to the matching relative path inside BACKUP_DIR.     ║
║    All copies use shutil.copy2 (preserves metadata).                 ║
║                                                                      ║
║  FEATURE 4 — INSTANT RESTORATION ON DELETED                         ║
║    on_deleted identifies the relative path of the deleted file,      ║
║    pulls the vault copy from BACKUP_DIR, and restores it to          ║
║    WATCH_PATH immediately via shutil.copy2.                          ║
║    Logged as: [RESTORED] <filename> recovered from backup vault      ║
║                                                                      ║
║  FEATURE 5 — RECURSIVE SUPPORT                                       ║
║    monitor_folder already uses ReadDirectoryChangesW with            ║
║    bWatchSubtree=True (recursive). The real-time backup helpers      ║
║    also preserve the full sub-directory structure under BACKUP_DIR.  ║
║                                                                      ║
║  FEATURE 6 — ERROR HANDLING WITH RETRY                               ║
║    All file operations in backup/restore helpers are wrapped in      ║
║    try-except. On PermissionError / OSError the operation is         ║
║    retried once after a 0.5 s delay before logging a warning.        ║
║                                                                      ║
║  ALL v5.3.3 FEATURES PRESERVED:                                      ║
║    • shutil top-level import                                         ║
║    • Telegram polling with exponential backoff                       ║
║    • Alert deletion watchdog                                         ║
║    • _explicit_allow_pending guard                                   ║
║    • _connectivity_monitor + offline lock                            ║
║    • protect_content=True on all alert messages                      ║
╚══════════════════════════════════════════════════════════════════════╝

INSTALL:
    pip install pywin32 psutil pyTeleBot plyer customtkinter

BUILD EXE:
    pyinstaller --onefile --noconsole --name RansomwareGuard app_v534.py
"""

# ═══════════════════════════════════════════════════════════════════════
# ██  STANDARD LIBRARY
# ═══════════════════════════════════════════════════════════════════════
import os, sys, time, signal, socket, ctypes, threading, zipfile, shutil
import logging, hashlib, uuid, collections, subprocess, json, webbrowser
from logging.handlers import RotatingFileHandler
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, scrolledtext

# ═══════════════════════════════════════════════════════════════════════
# ██  THIRD-PARTY
# ═══════════════════════════════════════════════════════════════════════
try:
    import customtkinter as ctk
    ctk.set_appearance_mode("light")
    ctk.set_default_color_theme("blue")
    _HAS_CTK = True
except ImportError:
    _HAS_CTK = False

try:
    import win32file, win32con, win32event, pywintypes
    _HAS_WIN32 = True
except ImportError:
    _HAS_WIN32 = False

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False

try:
    import telebot
    from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
    _HAS_TELEBOT = True
except ImportError:
    _HAS_TELEBOT = False

# ═══════════════════════════════════════════════════════════════════════
# ██  DESIGN TOKENS  — Professional White & Blue Theme
# ═══════════════════════════════════════════════════════════════════════
C_BASE      = "#f4f6f9"   # neutral off-white background
C_SURFACE   = "#ffffff"   # pure white panels
C_CARD      = "#eef2f7"   # subtle blue-tinted card
C_ELEVATED  = "#e3eaf5"   # slightly elevated surface
C_INPUT     = "#f8fafd"   # crisp input field
C_HOVER     = "#d0dff0"   # clear hover feedback
C_BORDER    = "#c5d3e3"   # soft border
C_BORDER2   = "#9db5d0"   # medium border accent

C_CYAN      = "#1565c0"   # deep professional blue
C_BLUE      = "#1976d2"   # primary blue
C_GREEN     = "#2e7d32"   # accessible dark green
C_RED       = "#ff0000"   # bright red (ALERT color)
C_ORANGE    = "#bf360c"   # dark burnt orange
C_PURPLE    = "#4527a0"   # deep purple
C_GREY      = "#607d8b"   # blue-grey neutral

C_TEXT1     = "#0d1b2a"   # near-black primary text
C_TEXT2     = "#2c4a6e"   # mid-tone blue text
C_TEXT3     = "#7a95b0"   # muted label text

C_LIVE      = C_GREEN
C_STOPPED   = C_GREY
C_ALERT     = C_RED       # system alerts are always RED

_CTK_FG_BTN_GREEN  = ("#2e7d32", "#1b5e20")
_CTK_FG_BTN_RED    = ("#b71c1c", "#7f0000")
_CTK_FG_BTN_GHOST  = (C_CARD, C_ELEVATED)

F_TITLE     = ("Segoe UI Semibold", 15)
F_H1        = ("Segoe UI Semibold", 13)
F_H2        = ("Segoe UI Semibold", 11)
F_H3        = ("Segoe UI Semibold", 10)
F_BODY      = ("Segoe UI", 10)
F_SMALL     = ("Segoe UI", 9)
F_MONO      = ("Consolas", 10)
F_MONO_SM   = ("Consolas", 9)
F_BTN       = ("Segoe UI Semibold", 10)
F_BTN_LG    = ("Segoe UI Semibold", 12)
F_BADGE     = ("Segoe UI Black", 11)
F_METRIC    = ("Segoe UI Semibold", 20)
F_METRIC_LB = ("Segoe UI", 9)

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")

# ═══════════════════════════════════════════════════════════════════════
# ██  ROUNDED BUTTON HELPER
# ═══════════════════════════════════════════════════════════════════════
def _rounded_btn(parent, text, font, bg, fg, active_bg, active_fg,
                 command=None, state="normal", pady=8, padx=0):
    """
    Canvas-based rounded-rectangle button with curved edges.
    Returns the canvas widget. Respects 'state' = 'disabled'.
    """
    radius = 8
    # Measure approximate width
    est_chars = max(len(text), 20)
    cv_w = est_chars * 8 + 40 + padx * 2
    cv_h = 16 + pady * 2

    cv = tk.Canvas(parent, height=cv_h, bg=parent.cget("bg"),
                   highlightthickness=0, cursor="hand2" if state == "normal" else "arrow")

    def _draw(fill_col):
        cv.delete("all")
        w = cv.winfo_width() or cv_w
        h = cv.winfo_height() or cv_h
        r = radius
        cv.create_arc(0, 0, r*2, r*2, start=90, extent=90, fill=fill_col, outline=fill_col)
        cv.create_arc(w-r*2, 0, w, r*2, start=0, extent=90, fill=fill_col, outline=fill_col)
        cv.create_arc(0, h-r*2, r*2, h, start=180, extent=90, fill=fill_col, outline=fill_col)
        cv.create_arc(w-r*2, h-r*2, w, h, start=270, extent=90, fill=fill_col, outline=fill_col)
        cv.create_rectangle(r, 0, w-r, h, fill=fill_col, outline=fill_col)
        cv.create_rectangle(0, r, w, h-r, fill=fill_col, outline=fill_col)
        txt_col = fg if state == "normal" else C_TEXT3
        cv.create_text(w//2, h//2, text=text, font=font, fill=txt_col, anchor="center")

    cv._current_bg = bg

    def _enter(e):
        if state == "normal":
            cv._current_bg = active_bg
            _draw(active_bg)
    def _leave(e):
        if state == "normal":
            cv._current_bg = bg
            _draw(bg)
    def _click(e):
        if state == "normal" and command:
            command()

    cv.bind("<Configure>", lambda e: _draw(cv._current_bg))
    cv.bind("<Enter>",     _enter)
    cv.bind("<Leave>",     _leave)
    cv.bind("<Button-1>",  _click)

    # Store disable/enable helpers
    def _set_state(s):
        nonlocal state
        state = s
        _draw(bg if s == "normal" else C_ELEVATED)
        cv.config(cursor="hand2" if s == "normal" else "arrow")
    cv.config_state = _set_state

    return cv

# ═══════════════════════════════════════════════════════════════════════
# ██  ENGINE CONSTANTS & SHARED STATE
# ═══════════════════════════════════════════════════════════════════════
BOT_TOKEN   = ""
CHAT_ID     = ""
WATCH_PATH  = os.getcwd()
LOG_FILE    = os.path.join(WATCH_PATH, "ransomware_guard.log")

# ── Backup vault — sibling of WATCH_PATH to avoid observer loops ──────
# Re-computed in engine_start() once the real WATCH_PATH is known.
BACKUP_DIR  = os.path.join(os.path.dirname(os.path.abspath(WATCH_PATH)),
                            os.path.basename(os.path.abspath(WATCH_PATH)) + "_RG_Vault")

VAULT_RETRY_DELAY = 0.5   # seconds to wait before retrying a locked file op

COALESCE_WINDOW      = 0.4
THROTTLE_SECONDS     = 8
RISK_WINDOW_SECONDS  = 10
RISK_THRESHOLD       = 8
MAX_SUSPEND_RETRIES  = 3
SUSPEND_RETRY_DELAY  = 0.3
TELEGRAM_RETRIES     = 3
TELEGRAM_RETRY_DELAY = 2.0
MAX_ALERT_THREADS    = 3
ONLINE_CHECK_HOST    = "8.8.8.8"
ONLINE_CHECK_PORT    = 53
ONLINE_CHECK_TIMEOUT = 3

# ── NEW: Connectivity monitor interval (Feature 2) ────────────────────
CONNECTIVITY_CHECK_INTERVAL  = 5   # seconds between each network check
OFFLINE_SHUTDOWN_DELAY       = 5   # seconds to wait after lock before auto-shutdown

# ── Telegram polling robustness (v5.3.3) ─────────────────────────────
POLLING_TIMEOUT          = 10   # long-poll timeout per get_updates call (s)
POLLING_BACKOFF_BASE     = 2    # initial retry wait on polling error (s)
POLLING_BACKOFF_MAX      = 60   # exponential backoff ceiling (s)

# ── Alert deletion watchdog (v5.3.3) ─────────────────────────────────
# How often to probe whether the Telegram alert message still exists.
# If the user deletes it before pressing ALLOW, it is automatically re-sent.
ALERT_WATCHDOG_INTERVAL  = 15   # seconds between existence probes

SYSTEM_PROCS = {
    "system","idle","smss.exe","csrss.exe","wininit.exe","winlogon.exe",
    "services.exe","lsass.exe","svchost.exe","explorer.exe","dwm.exe",
    "spoolsv.exe","taskhostw.exe","sihost.exe","fontdrvhost.exe",
    "runtimebroker.exe","msmpeng.exe","mssense.exe","nissrv.exe",
    "securityhealthservice.exe","code.exe","code - insiders.exe",
    "python.exe","python3.exe","pythonw.exe","cmd.exe","powershell.exe",
    "windowsterminal.exe","node.exe","git.exe","conhost.exe","taskmgr.exe",
}
EXCLUDED_DIRS = {
    "windows","program files","program files (x86)","programdata",
    "system32","syswow64","winsxs","$recycle.bin","appdata",
}
ACTION_MAP = {1:"CREATED",2:"DELETED",3:"MODIFIED",4:"RENAMED_OLD",5:"RENAMED_NEW"}

# ── Thread-safe engine state ──────────────────────────────────────────
_coalesce_lock       = threading.Lock()
_coalesce_buffer: dict = {}
_coalesce_event      = threading.Event()
_throttle_lock       = threading.Lock()
_last_alert: dict    = {}
_sent_ids_lock       = threading.Lock()
_sent_alert_ids: set = set()
_sent_ids_time: dict = {}
_risk_lock           = threading.Lock()
_change_times        = collections.deque()
_frozen_lock         = threading.Lock()
_frozen_pids: set    = set()
_alert_semaphore     = threading.Semaphore(MAX_ALERT_THREADS)
_shutdown_initiated  = threading.Event()
_backup_lock         = threading.Lock()
_backup_in_progress  = False
_lock_release_event  = threading.Event()
_overlay_ref         = None
_overlay_lock        = threading.Lock()

_monitoring_active   = False
_stop_monitor_event  = threading.Event()     # THE SINGLE STOP SIGNAL
_gui_log_queue: list = []
_gui_log_lock        = threading.Lock()
_bot                 = None
_risk_score_current  = 0

# ── NEW Feature 1: Persistent alert flag ─────────────────────────────
# Set when a ransomware lock alert fires.
# Cleared ONLY by _do_authorized_unlock() (the ALLOW callback path).
# While set, unlock_system() will refuse to unlock (guard against
# accidental or premature unlocks before the operator responds).
_explicit_allow_pending = threading.Event()

# Stores the Telegram message_id of the last alert so we can edit it
# to show a confirmed state after ALLOW is processed (Feature 1).
_pending_alert_message_id: int = 0
_pending_alert_message_lock    = threading.Lock()

# ── Alert watchdog state (v5.3.3) ────────────────────────────────────
# Stores enough info to rebuild + re-send the alert if the user deletes
# the Telegram message before pressing ALLOW.
_pending_alert_kwargs: dict = {}
_pending_alert_kwargs_lock  = threading.Lock()

# ── NEW Feature 2: Offline lock state ────────────────────────────────
# True while the system is locked DUE TO connectivity loss.
# Reset when connectivity is restored (allowing manual unlock after).
_offline_lock_active     = False
_offline_lock_lock       = threading.Lock()   # protects _offline_lock_active
_last_known_online       = True               # tracks previous connectivity state

# Guards against duplicate offline-triggered shutdowns.
# Set the moment the shutdown countdown thread is spawned; never cleared.
_offline_shutdown_pending = threading.Event()

# ═══════════════════════════════════════════════════════════════════════
# ██  LOGGING
# ═══════════════════════════════════════════════════════════════════════
logger = logging.getLogger("RansomwareGuard")
logger.setLevel(logging.DEBUG)
_ch = logging.StreamHandler(sys.stdout)
_ch.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(_ch)
_file_handler_added = False

def _ensure_file_handler():
    global _file_handler_added, LOG_FILE
    if _file_handler_added:
        return
    LOG_FILE = os.path.join(WATCH_PATH, "ransomware_guard.log")
    fh = RotatingFileHandler(LOG_FILE, maxBytes=2*1024*1024, backupCount=3, encoding="utf-8")
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(fh)
    _file_handler_added = True

class _GUILogHandler(logging.Handler):
    def emit(self, record):
        msg = self.format(record)
        with _gui_log_lock:
            _gui_log_queue.append((record.levelname, msg))

_gui_handler = _GUILogHandler()
_gui_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(_gui_handler)

def log(level: str, msg: str) -> None:
    getattr(logger, level.lower(), logger.info)(msg)

# ═══════════════════════════════════════════════════════════════════════
# ██  CONFIG
# ═══════════════════════════════════════════════════════════════════════
def load_config() -> dict:
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def save_config(token: str, chat_id: str, watch_path: str) -> None:
    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump({"token": token, "chat_id": chat_id, "watch_path": watch_path}, f, indent=2)
    except Exception as e:
        log("warning", f"Could not save config: {e}")

# ═══════════════════════════════════════════════════════════════════════
# ██  NETWORK
# ═══════════════════════════════════════════════════════════════════════
def _is_online() -> bool:
    try:
        socket.setdefaulttimeout(ONLINE_CHECK_TIMEOUT)
        with socket.create_connection((ONLINE_CHECK_HOST, ONLINE_CHECK_PORT)):
            return True
    except (OSError, socket.timeout):
        return False

# ═══════════════════════════════════════════════════════════════════════
# ██  SYSTEM LOCK  (BlockInput + LockOverlay)
# ═══════════════════════════════════════════════════════════════════════
class LockOverlay:
    """
    Full-screen red alert overlay.
    Polls _lock_release_event every 300 ms. Closes only when the event
    is set — which is now guarded by _explicit_allow_pending (Feature 1).
    """
    def __init__(self, action: str, file_name: str, risk_str: str):
        self.action    = action
        self.file_name = file_name
        self.risk_str  = risk_str
        self._root     = None
        self._thread   = threading.Thread(target=self._run, daemon=True, name="LockOverlay")
        self._thread.start()

    def _run(self) -> None:
        try:
            root = tk.Tk()
            self._root = root
            root.title("⚠️ SYSTEM LOCKED — RansomwareGuard")
            root.configure(bg="#8B0000")
            root.attributes("-fullscreen", True)
            root.attributes("-topmost", True)
            root.overrideredirect(True)
            root.lift()
            root.focus_force()
            tk.Label(root, text="⚠️  SYSTEM LOCKED  ⚠️",
                     font=("Arial Black", 36, "bold"), fg="white", bg="#8B0000").pack(pady=(100, 20))
            tk.Label(root,
                     text="Suspicious file activity detected.\nKeyboard and mouse have been disabled.",
                     font=("Arial", 18), fg="#FFD700", bg="#8B0000").pack(pady=(0, 40))
            container = tk.Frame(root, bg="#8B0000")
            container.pack(expand=True)
            detail = (f"Action  :  {self.action}\nFile    :  {self.file_name}\n"
                      f"Risk    :  {self.risk_str}\nTime    :  {datetime.now().strftime('%H:%M:%S')}")
            tk.Label(container, text=detail, font=("Courier New", 16), fg="white", bg="#4B0000",
                     justify="left", relief="sunken", padx=30, pady=20).pack(ipadx=20, ipady=10)
            def _poll():
                if _lock_release_event.is_set():
                    try: root.destroy()
                    except: pass
                else:
                    root.after(300, _poll)
            root.after(300, _poll)
            root.mainloop()
        except Exception as e:
            log("error", f"LockOverlay error: {e}")

    def close(self) -> None:
        try:
            if self._root:
                self._root.destroy()
        except: pass

def _block_input(block: bool) -> None:
    try:
        result = ctypes.windll.user32.BlockInput(ctypes.c_bool(block))
        if result:
            log("info", f"Input {'BLOCKED' if block else 'UNBLOCKED'}.")
        else:
            log("warning", f"BlockInput({block}) returned 0 — may lack desktop ownership.")
    except Exception as e:
        log("error", f"BlockInput error: {e}")

def lock_system(action: str, file_name: str, risk_str: str) -> None:
    global _overlay_ref
    with _overlay_lock:
        if _overlay_ref is not None and _overlay_ref._thread.is_alive():
            log("info", "Overlay already active — skipping."); return
        _lock_release_event.clear()
        _block_input(True)
        log("warning", f"SYSTEM LOCKED — input disabled. Reason: {action}")
        if _overlay_ref is not None:
            try: _overlay_ref.close()
            except: pass
        _overlay_ref = LockOverlay(action, file_name, risk_str)

def unlock_system() -> None:
    """
    FEATURE 1 GUARD: If a ransomware alert is still pending explicit
    ALLOW from Telegram, this function refuses to unlock and logs
    a warning. Only _do_authorized_unlock() bypasses this guard.
    """
    if _explicit_allow_pending.is_set():
        log("warning",
            "[UNLOCK BLOCKED] Ransomware alert is still pending ALLOW confirmation "
            "from Telegram. System will not unlock until the operator presses ALLOW.")
        return
    _perform_unlock()

def _perform_unlock() -> None:
    """Internal: actually performs the unlock without checking the pending flag."""
    global _overlay_ref
    _lock_release_event.set()
    _block_input(False)
    log("info", "SYSTEM UNLOCKED — input restored.")
    with _overlay_lock:
        if _overlay_ref is not None:
            try: _overlay_ref.close()
            except: pass
            _overlay_ref = None

def _do_authorized_unlock(pid: int, bot_instance) -> list:
    """
    FEATURE 1 — Authorized unlock path.
    Called exclusively from the ALLOW callback.
    1. Clears _explicit_allow_pending (removes the lock guard).
    2. Performs the actual system unlock.
    3. Resumes all frozen PIDs.
    Returns list of (ok_pids, fail_pids) for the Telegram response.
    """
    global _explicit_allow_pending

    # Clear the guard — this is the ONLY place it is cleared for ransomware alerts
    _explicit_allow_pending.clear()
    log("info", "[ALLOW] Explicit authorization received — clearing pending alert flag.")

    # Now perform the real unlock
    _perform_unlock()

    # Resume frozen PIDs
    with _frozen_lock:
        all_frozen = list(_frozen_pids)
        _frozen_pids.clear()
    if pid not in all_frozen and pid != 0:
        all_frozen.insert(0, pid)

    resumed_ok, resumed_fail = [], []
    for rpid in all_frozen:
        if _resume(rpid): resumed_ok.append(rpid)
        else:             resumed_fail.append(rpid)

    return resumed_ok, resumed_fail

# ═══════════════════════════════════════════════════════════════════════
# ██  NEW FEATURE 2 — CONNECTIVITY MONITOR
# ═══════════════════════════════════════════════════════════════════════
def _connectivity_monitor() -> None:
    """
    Background daemon thread (Feature 2).

    Behaviour:
    - Checks network connectivity every CONNECTIVITY_CHECK_INTERVAL seconds.
    - ONLINE → OFFLINE transition:
        • Sets _offline_lock_active = True
        • Calls lock_system() with action="OFFLINE_DETECTION"
        • Sends a Telegram alert IF a bot session was previously established
          (best-effort; we may be offline, so this is fire-and-forget).
    - OFFLINE → ONLINE transition:
        • Clears _offline_lock_active (allows manual unlock via STOP or ALLOW).
        • Attempts to send a Telegram "connectivity restored" message.
        • Does NOT automatically unlock — the operator must still confirm.
    - Exits cleanly when _stop_monitor_event is set.
    """
    global _last_known_online, _offline_lock_active, _overlay_ref

    log("info", "[ConnectivityMonitor] started.")

    while not _stop_monitor_event.is_set():
        # Interruptible sleep — exits quickly when engine stops
        _stop_monitor_event.wait(timeout=CONNECTIVITY_CHECK_INTERVAL)
        if _stop_monitor_event.is_set():
            break

        currently_online = _is_online()

        # ── ONLINE → OFFLINE ─────────────────────────────────────
        if _last_known_online and not currently_online:
            log("warning", "[ConnectivityMonitor] Network connectivity LOST — locking system.")
            with _offline_lock_lock:
                _offline_lock_active = True

            # Step 1: Fire the lock immediately.
            # lock_system() is idempotent if already locked.
            lock_system(
                action    = "OFFLINE_DETECTION",
                file_name = "Network connectivity lost",
                risk_str  = "🔴 HIGH — System offline"
            )

            # Step 2: Spawn a one-shot countdown thread that waits
            # OFFLINE_SHUTDOWN_DELAY seconds, then calls _do_shutdown().
            # _offline_shutdown_pending guards against duplicate spawns if
            # this branch is somehow re-entered within the same engine session.
            if not _offline_shutdown_pending.is_set():
                _offline_shutdown_pending.set()

                def _delayed_offline_shutdown():
                    log("warning",
                        f"[ConnectivityMonitor] Shutdown countdown started — "
                        f"system will power off in {OFFLINE_SHUTDOWN_DELAY}s.")
                    # Interruptible wait: if engine_stop() fires before the
                    # timer expires, _stop_monitor_event is set and we abort.
                    cancelled = _stop_monitor_event.wait(
                        timeout=OFFLINE_SHUTDOWN_DELAY)
                    if cancelled:
                        log("info",
                            "[ConnectivityMonitor] Shutdown countdown CANCELLED "
                            "(engine was stopped before the timer expired).")
                        return
                    log("warning",
                        "[ConnectivityMonitor] Offline shutdown timer elapsed — "
                        "executing _do_shutdown().")
                    _do_shutdown()

                threading.Thread(
                    target=_delayed_offline_shutdown,
                    daemon=True,
                    name="OfflineShutdownCountdown"
                ).start()

            # Best-effort Telegram notification (will fail if truly offline,
            # but may succeed on intermittent connections or cached routes).
            if _bot:
                try:
                    _bot.send_message(
                        CHAT_ID,
                        "🔴 *OFFLINE ALERT*\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        "⚠️ Network connectivity has been LOST.\n"
                        "🔒 System has been LOCKED automatically.\n"
                        f"🕐 Time : `{datetime.now().strftime('%H:%M:%S')}`\n"
                        f"⏳ Auto-shutdown in {OFFLINE_SHUTDOWN_DELAY} seconds.\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        "System will shut down unless engine is stopped first.",
                        parse_mode="Markdown"
                    )
                except Exception as e:
                    log("debug", f"[ConnectivityMonitor] Offline Telegram notify failed (expected): {e}")

            _show_notification(
                "⚠️ Network Lost — Shutting Down",
                f"Internet lost. System locked. Shutting down in {OFFLINE_SHUTDOWN_DELAY}s.")

        # ── OFFLINE → ONLINE ─────────────────────────────────────
        elif not _last_known_online and currently_online:
            log("info", "[ConnectivityMonitor] Network connectivity RESTORED.")
            with _offline_lock_lock:
                _offline_lock_active = False

            # Notify the operator. Do NOT auto-unlock — require explicit action.
            if _bot:
                try:
                    markup = InlineKeyboardMarkup()
                    markup.add(InlineKeyboardButton(
                        "✅ UNLOCK — Connection Restored",
                        callback_data="allow_offline_unlock"))
                    _bot.send_message(
                        CHAT_ID,
                        "🟢 *CONNECTIVITY RESTORED*\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        "✅ Internet connection has been restored.\n"
                        f"🕐 Time : `{datetime.now().strftime('%H:%M:%S')}`\n"
                        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        "⚠️ System is still locked.\n"
                        "Press the button below to unlock.",
                        parse_mode="Markdown",
                        reply_markup=markup
                    )
                except Exception as e:
                    log("warning", f"[ConnectivityMonitor] Restore notify failed: {e}")

        # ── Re-lock if overlay was somehow dismissed while offline ──
        # This prevents the lock being dismissed by stray events while
        # the network is still down.
        with _offline_lock_lock:
            still_offline_locked = _offline_lock_active

        if still_offline_locked:
            with _overlay_lock:
                overlay_alive = (_overlay_ref is not None and
                                 _overlay_ref._thread.is_alive())
            if not overlay_alive:
                log("warning", "[ConnectivityMonitor] Overlay was dismissed while "
                    "offline — re-locking.")
                lock_system(
                    action    = "OFFLINE_DETECTION",
                    file_name = "Network still offline — re-locked",
                    risk_str  = "🔴 HIGH — System still offline"
                )

        _last_known_online = currently_online

    log("info", "[ConnectivityMonitor] exited cleanly.")

# ═══════════════════════════════════════════════════════════════════════
# ██  GRACEFUL STOP  (non-blocking, event-driven — v5.1 fix)
# ═══════════════════════════════════════════════════════════════════════
def _graceful_stop(signum=None, frame=None) -> None:
    global _monitoring_active, _offline_lock_active
    log("info", "Graceful stop — resuming frozen processes and unlocking…")
    _stop_monitor_event.set()
    _monitoring_active = False

    # Clear both guards so the stop path can always unlock
    _explicit_allow_pending.clear()
    with _offline_lock_lock:
        _offline_lock_active = False

    try: _perform_unlock()
    except: pass

    with _frozen_lock:
        pids = list(_frozen_pids)
    for pid in pids:
        try:
            psutil.Process(pid).resume()
            log("info", f"Resumed PID {pid} on stop.")
        except Exception as e:
            log("warning", f"Could not resume PID {pid}: {e}")
    _coalesce_event.set()
    log("info", "RansomwareGuard — monitoring stopped.")

signal.signal(signal.SIGINT,  _graceful_stop)
signal.signal(signal.SIGTERM, _graceful_stop)

# ═══════════════════════════════════════════════════════════════════════
# ██  COALESCE DISPATCHER  (event-driven exit — v5.1 fix)
# ═══════════════════════════════════════════════════════════════════════
def enqueue_event(action: str, file_name: str) -> None:
    key = (action, file_name)
    with _coalesce_lock:
        if key not in _coalesce_buffer:
            _coalesce_buffer[key] = time.time()
    _coalesce_event.set()

def _coalesce_dispatcher() -> None:
    log("info", "[CoalesceDispatcher] started.")
    while not _stop_monitor_event.is_set():
        _coalesce_event.wait(timeout=0.5)
        if _stop_monitor_event.is_set(): break
        _coalesce_event.clear()
        time.sleep(COALESCE_WINDOW)
        with _coalesce_lock:
            snapshot = _coalesce_buffer.copy()
            _coalesce_buffer.clear()
        for (action, file_name) in snapshot:
            if _stop_monitor_event.is_set(): break
            if _is_throttled(action, file_name):
                log("debug", f"[THROTTLED] {action}: {file_name}"); continue
            log("info", f"[DISPATCHING] {action}: {file_name}")
            threading.Thread(target=_run_alert, args=(action, file_name),
                             daemon=True, name=f"AlertWorker-{action[:3]}").start()
    log("info", "[CoalesceDispatcher] exited cleanly.")

# ═══════════════════════════════════════════════════════════════════════
# ██  THROTTLE / DEDUP
# ═══════════════════════════════════════════════════════════════════════
def _throttle_key(action, file_name):
    return hashlib.md5(f"{action}:{file_name}".encode()).hexdigest()

def _is_throttled(action, file_name):
    key = _throttle_key(action, file_name)
    now = time.time()
    with _throttle_lock:
        if now - _last_alert.get(key, 0) < THROTTLE_SECONDS: return True
        _last_alert[key] = now
    return False

def _register_sent_id(uid):
    with _sent_ids_lock:
        _sent_alert_ids.add(uid)
        _sent_ids_time[uid] = time.time()

def _cleanup_sent_ids():
    cutoff = time.time() - THROTTLE_SECONDS * 4
    with _sent_ids_lock:
        old = [k for k, ts in _sent_ids_time.items() if ts < cutoff]
        for k in old:
            _sent_alert_ids.discard(k)
            del _sent_ids_time[k]

def _cleanup_throttle_cache():
    log("info", "[ThrottleCleanup] started.")
    while not _stop_monitor_event.is_set():
        _stop_monitor_event.wait(timeout=300)
        if _stop_monitor_event.is_set(): break
        cutoff = time.time() - THROTTLE_SECONDS * 2
        with _throttle_lock:
            stale = [k for k, ts in _last_alert.items() if ts < cutoff]
            for k in stale: del _last_alert[k]
        _cleanup_sent_ids()
    log("info", "[ThrottleCleanup] exited cleanly.")

# ═══════════════════════════════════════════════════════════════════════
# ██  RISK SCORING
# ═══════════════════════════════════════════════════════════════════════
def _record_and_score() -> int:
    global _risk_score_current
    now, cutoff = time.time(), time.time() - RISK_WINDOW_SECONDS
    with _risk_lock:
        _change_times.append(now)
        while _change_times and _change_times[0] < cutoff:
            _change_times.popleft()
        _risk_score_current = len(_change_times)
        return _risk_score_current

def _risk_label(score: int) -> str:
    if score >= RISK_THRESHOLD:
        return f"🔴 HIGH  ({score} events/{RISK_WINDOW_SECONDS}s)"
    elif score >= RISK_THRESHOLD // 2:
        return f"🟠 MEDIUM ({score} events/{RISK_WINDOW_SECONDS}s)"
    return f"🟢 LOW   ({score} events/{RISK_WINDOW_SECONDS}s)"

# ═══════════════════════════════════════════════════════════════════════
# ██  NOTIFICATIONS / BACKUP / SHUTDOWN
# ═══════════════════════════════════════════════════════════════════════
def _show_notification(title: str, message: str) -> None:
    try:
        from plyer import notification
        notification.notify(title=title, message=message, app_name="RansomwareGuard", timeout=10)
        return
    except: pass
    try:
        t = title.replace("'","").replace('"',"")
        m = message.replace("'","").replace('"',"")
        os.system(f'powershell -WindowStyle Hidden -Command "'
                  f"$w=New-Object -ComObject WScript.Shell;$w.Popup('{m}',8,'{t}',48)\"")
        return
    except: pass
    log("warning", f"[NOTIF] {title} | {message}")

def _create_backup_zip(label: str):
    global _backup_in_progress
    with _backup_lock:
        if _backup_in_progress:
            log("info", f"[{label}] Backup already in progress — skipping."); return None
        _backup_in_progress = True
    zip_name = None
    try:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_name = os.path.join(WATCH_PATH, f"backup_{ts}.zip")
        log("info", f"[{label}] Creating backup → {zip_name}")
        with zipfile.ZipFile(zip_name, "w", zipfile.ZIP_DEFLATED) as zipf:
            for root_dir, dirs, files in os.walk(WATCH_PATH):
                dirs[:] = [d for d in dirs if not d.startswith("backup_")
                           and d.lower() != "restored" and d.lower() not in EXCLUDED_DIRS]
                for fname in files:
                    if fname.endswith(".zip") or fname == os.path.basename(LOG_FILE): continue
                    fp = os.path.join(root_dir, fname)
                    try: zipf.write(fp, os.path.relpath(fp, WATCH_PATH))
                    except: pass
        log("info", f"[{label}] Backup complete: {zip_name}")
        return zip_name
    except Exception as e:
        log("error", f"[{label}] Backup failed: {e}"); return None
    finally:
        with _backup_lock: _backup_in_progress = False

def _perform_backup(label: str = "MANUAL-BACKUP") -> str | None:
    """
    Recursively copies every file from WATCH_PATH into a timestamped backup
    directory using shutil.copy2 (preserves metadata).

    Behaviour:
    - Copies ALL file types without filtering by extension.
    - Preserves the full directory structure relative to WATCH_PATH.
    - Skips files that are locked / in use and continues with the rest
      (PermissionError, OSError) — a warning is logged per skipped file.
    - Skips backup_* directories, the 'restored' folder, and EXCLUDED_DIRS
      to avoid backing up artefacts produced by this tool itself.
    - Logs final progress: total found / copied / skipped counts.

    Returns the backup directory path on success, or None on failure.
    """
    global _backup_in_progress

    with _backup_lock:
        if _backup_in_progress:
            log("info", f"[{label}] Backup already in progress — skipping.")
            return None
        _backup_in_progress = True

    backup_dir = None
    try:
        ts         = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = os.path.join(WATCH_PATH, f"backup_copy_{ts}")
        os.makedirs(backup_dir, exist_ok=True)
        log("info", f"[{label}] Starting file-copy backup → {backup_dir}")

        total_found  = 0
        total_copied = 0
        total_skipped = 0

        for root_dir, dirs, files in os.walk(WATCH_PATH):
            # Prune directories we should never back up
            dirs[:] = [
                d for d in dirs
                if not d.startswith("backup_")
                and d.lower() != "restored"
                and d.lower() not in EXCLUDED_DIRS
            ]

            for fname in files:
                src_path = os.path.join(root_dir, fname)
                # Skip our own log file
                if src_path == LOG_FILE:
                    continue

                total_found += 1

                # Compute destination path, mirroring directory structure
                rel_path = os.path.relpath(src_path, WATCH_PATH)
                dst_path = os.path.join(backup_dir, rel_path)

                try:
                    os.makedirs(os.path.dirname(dst_path), exist_ok=True)
                    shutil.copy2(src_path, dst_path)
                    total_copied += 1
                except (PermissionError, OSError) as e:
                    # File may be locked by another process — skip and continue
                    total_skipped += 1
                    log("warning",
                        f"[{label}] Skipped locked/inaccessible file "
                        f"'{rel_path}': {e}")
                except Exception as e:
                    total_skipped += 1
                    log("warning",
                        f"[{label}] Unexpected error copying '{rel_path}': {e}")

        summary = (
            f"[{label}] Backup complete — "
            f"{total_copied}/{total_found} files copied, "
            f"{total_skipped} skipped  →  {backup_dir}"
        )
        log("info", summary)

        # Push progress summary to the GUI log queue so it appears in the UI
        with _gui_log_lock:
            _gui_log_queue.append(("INFO", summary))

        return backup_dir

    except Exception as e:
        log("error", f"[{label}] Backup failed unexpectedly: {e}")
        return None
    finally:
        with _backup_lock:
            _backup_in_progress = False



# ═══════════════════════════════════════════════════════════════════════
# ██  BACKUP VAULT HELPERS  (v5.3.4)
# ═══════════════════════════════════════════════════════════════════════
def _vault_copy(src_path: str, label: str = "VAULT") -> bool:
    """
    Copy a single file from WATCH_PATH into the matching relative path
    under BACKUP_DIR, using shutil.copy2 (preserves metadata).

    Retries once after VAULT_RETRY_DELAY seconds on PermissionError /
    OSError so 'file in use' conditions are handled gracefully.
    Returns True on success, False if both attempts fail.
    """
    try:
        rel   = os.path.relpath(src_path, WATCH_PATH)
        dst   = os.path.join(BACKUP_DIR, rel)
        for attempt in range(1, 3):
            try:
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy2(src_path, dst)
                log("debug", f"[{label}] Backed up: {rel}")
                return True
            except (PermissionError, OSError) as e:
                if attempt == 1:
                    log("warning", f"[{label}] Retry ({rel}): {e}")
                    time.sleep(VAULT_RETRY_DELAY)
                else:
                    log("warning", f"[{label}] Skipped locked file '{rel}': {e}")
                    return False
    except Exception as e:
        log("error", f"[{label}] Unexpected error backing up '{src_path}': {e}")
        return False


def _vault_restore(rel_path: str) -> bool:
    """
    Restore a single deleted file from BACKUP_DIR back to WATCH_PATH.

    Finds the vault copy using the relative path, creates any missing
    parent directories, and copies it back via shutil.copy2.
    Retries once after VAULT_RETRY_DELAY on transient errors.
    Returns True on success, False if the vault copy is missing or
    both write attempts fail.
    """
    vault_src = os.path.join(BACKUP_DIR, rel_path)
    dst_path  = os.path.join(WATCH_PATH, rel_path)
    if not os.path.exists(vault_src):
        log("warning", f"[RESTORE] No vault copy for '{rel_path}' — cannot restore.")
        return False
    for attempt in range(1, 3):
        try:
            os.makedirs(os.path.dirname(dst_path), exist_ok=True)
            shutil.copy2(vault_src, dst_path)
            log("info",
                f"[RESTORED] {os.path.basename(rel_path)} recovered from backup vault")
            return True
        except (PermissionError, OSError) as e:
            if attempt == 1:
                log("warning", f"[RESTORE] Retry '{rel_path}': {e}")
                time.sleep(VAULT_RETRY_DELAY)
            else:
                log("error", f"[RESTORE] Failed to restore '{rel_path}': {e}")
                return False
    return False


def initial_sync() -> None:
    """
    Full mirror of WATCH_PATH → BACKUP_DIR using shutil.copytree logic.

    • If BACKUP_DIR does not exist, copies the entire tree via
      shutil.copytree (dirs_exist_ok=False fast path).
    • If BACKUP_DIR already exists, walks WATCH_PATH and updates only
      files whose size or mtime differs (incremental refresh).
    • Always skips BACKUP_DIR itself, backup_* ZIPs, the log file, and
      EXCLUDED_DIRS — preventing observer feedback loops.
    """
    log("info", f"[InitialSync] Starting full mirror: {WATCH_PATH} → {BACKUP_DIR}")
    try:
        if not os.path.exists(BACKUP_DIR):
            # Fresh copy — use copytree with an ignore filter
            def _ignore(directory, contents):
                skip = set()
                for name in contents:
                    full = os.path.join(directory, name)
                    if name.lower() in EXCLUDED_DIRS:
                        skip.add(name)
                    elif name.startswith("backup_") and name.endswith(".zip"):
                        skip.add(name)
                    elif full == LOG_FILE or full == BACKUP_DIR:
                        skip.add(name)
                    elif full == os.path.abspath(BACKUP_DIR):
                        skip.add(name)
                return skip

            shutil.copytree(WATCH_PATH, BACKUP_DIR, ignore=_ignore)
            log("info", "[InitialSync] Full mirror complete (fresh vault created).")
        else:
            # Incremental — update changed files only
            copied = skipped = 0
            for root_dir, dirs, files in os.walk(WATCH_PATH):
                abs_root = os.path.abspath(root_dir)
                if abs_root == os.path.abspath(BACKUP_DIR):
                    dirs[:] = []
                    continue
                dirs[:] = [
                    d for d in dirs
                    if d.lower() not in EXCLUDED_DIRS
                    and not d.startswith("backup_")
                    and os.path.abspath(os.path.join(root_dir, d)) !=
                        os.path.abspath(BACKUP_DIR)
                ]
                for fname in files:
                    src = os.path.join(root_dir, fname)
                    if src == LOG_FILE:
                        continue
                    if fname.startswith("backup_") and fname.endswith(".zip"):
                        continue
                    rel = os.path.relpath(src, WATCH_PATH)
                    dst = os.path.join(BACKUP_DIR, rel)
                    needs_copy = True
                    if os.path.exists(dst):
                        try:
                            ss = os.stat(src)
                            ds = os.stat(dst)
                            if ss.st_size == ds.st_size and ss.st_mtime == ds.st_mtime:
                                needs_copy = False
                        except OSError:
                            pass
                    if needs_copy:
                        for attempt in range(1, 3):
                            try:
                                os.makedirs(os.path.dirname(dst), exist_ok=True)
                                shutil.copy2(src, dst)
                                copied += 1
                                break
                            except (PermissionError, OSError) as e:
                                if attempt == 1:
                                    time.sleep(VAULT_RETRY_DELAY)
                                else:
                                    skipped += 1
                                    log("warning",
                                        f"[InitialSync] Skipped '{rel}': {e}")
                    else:
                        skipped += 1
            log("info",
                f"[InitialSync] Incremental sync complete — "
                f"{copied} updated, {skipped} unchanged/skipped.")
    except Exception as e:
        log("error", f"[InitialSync] Failed: {e}")


def _auto_backup_on_delete(file_name: str) -> None:
    log("warning", f"[DELETE-BACKUP] Immediate backup for deleted: {file_name}")
    zip_name = _create_backup_zip("DELETE-BACKUP")
    if zip_name:
        msg = (f"🗑️ *DELETE detected — Emergency backup created*\n"
               f"📄 Deleted file : `{file_name}`\n"
               f"💾 Backup saved : `{os.path.basename(zip_name)}`\n"
               f"🕐 Time         : `{datetime.now().strftime('%H:%M:%S')}`")
        if _is_online(): _send_telegram_message(msg)
    else: log("error", "[DELETE-BACKUP] Backup failed.")

def _trigger_backup_only() -> None:
    zip_name = _create_backup_zip("AUTO-BACKUP")
    if zip_name and _is_online():
        _send_telegram_message(f"💾 *Auto-backup created*: `{os.path.basename(zip_name)}`\n"
                               f"_(triggered by HIGH risk detection)_")

def full_backup_and_shutdown() -> None:
    zip_name = _create_backup_zip("KILL-BACKUP")
    if zip_name and _is_online():
        _send_telegram_message(f"✅ Backup saved: `{os.path.basename(zip_name)}`\n🔴 Shutting down now…")
    elif not zip_name and _is_online():
        _send_telegram_message("⚠️ Backup failed.\n🔴 Proceeding to shutdown anyway…")
    time.sleep(3)
    _do_shutdown()

def restore_latest_backup() -> None:
    try:
        backups = sorted([f for f in os.listdir(WATCH_PATH)
                          if f.startswith("backup_") and f.endswith(".zip")])
        if not backups:
            _send_telegram_message("⚠️ No backup found to restore."); return
        latest      = backups[-1]
        restore_dir = os.path.join(WATCH_PATH, "restored")
        os.makedirs(restore_dir, exist_ok=True)
        with zipfile.ZipFile(os.path.join(WATCH_PATH, latest), "r") as zf:
            zf.extractall(restore_dir)
        log("info", f"Restored from {latest}")
        _send_telegram_message(f"♻️ Restored from `{latest}` → `restored/`")
    except Exception as e:
        log("error", f"Restore failed: {e}")
        _send_telegram_message(f"❌ Restore failed: {e}")

def _do_shutdown() -> None:
    if _shutdown_initiated.is_set(): return
    _shutdown_initiated.set()
    log("info", "Executing system shutdown…")
    ret = os.system("shutdown /s /t 0")
    if ret == 0: return
    try:
        result = subprocess.run(["shutdown","/s","/t","0"], capture_output=True, timeout=10,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode == 0: return
        subprocess.run(["powershell","-Command","Stop-Computer -Force"],
                       capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
    except Exception as e:
        log("error", f"All shutdown attempts failed: {e}")

# ═══════════════════════════════════════════════════════════════════════
# ██  PROCESS DETECTION & FREEZE
# ═══════════════════════════════════════════════════════════════════════
def _get_suspicious_processes(top_n=3):
    primed = {}
    for proc in psutil.process_iter(["pid","name","status"]):
        try:
            name   = (proc.info["name"] or "").lower()
            pid    = proc.info["pid"]
            status = proc.info.get("status","")
            if name in SYSTEM_PROCS: continue
            with _frozen_lock:
                if pid in _frozen_pids: continue
            if status in (psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD): continue
            proc.cpu_percent(interval=None)
            primed[pid] = proc
        except (psutil.NoSuchProcess, psutil.AccessDenied): continue
    time.sleep(0.1)
    candidates = []
    for pid, proc in primed.items():
        try:
            cpu = proc.cpu_percent(interval=None)
            candidates.append((cpu, proc))
        except (psutil.NoSuchProcess, psutil.AccessDenied): continue
    candidates.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in candidates[:top_n]]

def _suspend(proc) -> bool:
    for attempt in range(1, MAX_SUSPEND_RETRIES + 1):
        try:
            if proc.status() in (psutil.STATUS_STOPPED, "stopped"):
                with _frozen_lock: _frozen_pids.add(proc.pid)
                return True
            proc.suspend()
            time.sleep(0.1)
            try:
                if proc.status() in (psutil.STATUS_STOPPED, "stopped"):
                    with _frozen_lock: _frozen_pids.add(proc.pid)
                    log("info", f"Suspended PID {proc.pid} ({proc.name()}) [attempt {attempt}].")
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                with _frozen_lock: _frozen_pids.discard(proc.pid)
                return True
        except psutil.NoSuchProcess:
            log("warning", f"PID {proc.pid} vanished before suspension."); return False
        except psutil.AccessDenied as e:
            log("warning", f"AccessDenied suspending PID {proc.pid} (attempt {attempt}): {e}")
            if attempt == MAX_SUSPEND_RETRIES: return False
        time.sleep(SUSPEND_RETRY_DELAY)
    return False

def _resume(pid: int) -> bool:
    try:
        proc = psutil.Process(pid)
        proc.resume()
        time.sleep(0.1)
        try:
            if proc.status() not in (psutil.STATUS_STOPPED, "stopped"):
                with _frozen_lock: _frozen_pids.discard(pid)
                log("info", f"Resumed PID {pid}.")
                return True
            else:
                proc.resume()
                time.sleep(0.1)
                with _frozen_lock: _frozen_pids.discard(pid)
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            with _frozen_lock: _frozen_pids.discard(pid)
            return True
    except psutil.NoSuchProcess:
        with _frozen_lock: _frozen_pids.discard(pid)
        return False
    except Exception as e:
        log("error", f"Unexpected error resuming PID {pid}: {e}")
        with _frozen_lock: _frozen_pids.discard(pid)
        return False

# ═══════════════════════════════════════════════════════════════════════
# ██  TELEGRAM SEND HELPERS
# ═══════════════════════════════════════════════════════════════════════
def _send_telegram_message(text: str, parse_mode: str = "Markdown") -> bool:
    if not _bot or not _is_online():
        log("warning", f"[OFFLINE/NO-BOT] Message not sent: {text[:60]}…"); return False
    for attempt in range(1, TELEGRAM_RETRIES + 1):
        try:
            _bot.send_message(CHAT_ID, text, parse_mode=parse_mode); return True
        except Exception as e:
            log("warning", f"Telegram send attempt {attempt} failed: {e}")
            if attempt < TELEGRAM_RETRIES: time.sleep(TELEGRAM_RETRY_DELAY)
    log("error", "All Telegram send attempts failed."); return False

def _send_telegram_alert(action, file_name, processes, risk, alert_uid):
    """
    Sends the ransomware alert with ALLOW / KILL buttons.

    v5.3.3 additions on top of v5.3.2:
    - Stores alert kwargs in _pending_alert_kwargs so _alert_watchdog can
      re-send the message if the user deletes it before pressing ALLOW.
    - Launches _alert_watchdog() as a daemon thread after a successful send.
    - Clears _pending_alert_kwargs if all send attempts fail.
    """
    global _pending_alert_message_id

    with _sent_ids_lock:
        if alert_uid in _sent_alert_ids:
            log("warning", f"[DEDUP] UID {alert_uid} already sent — suppressing."); return
    if not _is_online():
        log("warning", "[OFFLINE] Alert shown locally only. System LOCKED.")
        _show_notification("⚠️ OFFLINE — System Locked", "No internet. See overlay."); return
    if not _bot:
        log("warning", "[NO-BOT] Telegram bot not initialised — alert shown locally only."); return
    try:
        primary_pid = processes[0].pid if processes else 0
        proc_lines  = ("\n".join(f"  • `{p.name()}` (PID `{p.pid}`)" for p in processes)
                       if processes else "  • No active process detected")
        kill_cb  = f"kill_{primary_pid}"
        allow_cb = f"allow_{primary_pid}"
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("❌ KILL + SHUTDOWN", callback_data=kill_cb),
            InlineKeyboardButton("✅ ALLOW",           callback_data=allow_cb))
        markup.add(InlineKeyboardButton("♻️ RESTORE FILES", callback_data="restore"))
        msg = (f"🚨 *RANSOMWARE ALERT*\n{'─'*28}\n"
               f"🔴 Action  : `{action}`\n📄 File    : `{file_name}`\n"
               f"📊 Risk    : {_risk_label(risk)}\n🕐 Time    : `{datetime.now().strftime('%H:%M:%S')}`\n"
               f"🔒 Status  : System LOCKED\n{'─'*28}\n"
               f"⚙️ *Frozen processes:*\n{proc_lines}\n{'─'*28}\n"
               f"⏸ *Tap a button below to unlock — system stays locked until you do:*")

        # Store kwargs so the watchdog thread can re-send if this message is deleted
        with _pending_alert_kwargs_lock:
            _pending_alert_kwargs.update({
                "text":     msg,
                "kill_cb":  kill_cb,
                "allow_cb": allow_cb,
            })

        # Set the pending flag BEFORE sending — no window between send and flag set
        _explicit_allow_pending.set()
        log("info", "[ALERT] _explicit_allow_pending SET — system requires explicit ALLOW.")

        for attempt in range(1, TELEGRAM_RETRIES + 1):
            try:
                # protect_content=True prevents forwarding/saving the message
                sent_msg = _bot.send_message(
                    CHAT_ID, msg,
                    parse_mode="Markdown",
                    reply_markup=markup,
                    protect_content=True
                )
                _register_sent_id(alert_uid)
                with _pending_alert_message_lock:
                    _pending_alert_message_id = sent_msg.message_id
                log("info", f"Telegram alert sent → {action} | {file_name} | "
                    f"UID {alert_uid} | msg_id {sent_msg.message_id}")

                # Launch watchdog: re-sends alert if user deletes it before ALLOW
                threading.Thread(
                    target=_alert_watchdog,
                    daemon=True,
                    name=f"AlertWatchdog-{alert_uid[:8]}"
                ).start()
                return
            except Exception as e:
                log("warning", f"Telegram alert attempt {attempt} failed: {e}")
                if attempt < TELEGRAM_RETRIES: time.sleep(TELEGRAM_RETRY_DELAY)

        # All attempts failed — clear both guards, message was never delivered
        _explicit_allow_pending.clear()
        with _pending_alert_kwargs_lock:
            _pending_alert_kwargs.clear()
        log("error", "All Telegram alert attempts failed — clearing pending flag.")
    except Exception as e:
        _explicit_allow_pending.clear()
        with _pending_alert_kwargs_lock:
            _pending_alert_kwargs.clear()
        log("error", f"_send_telegram_alert error: {e}")

# ═══════════════════════════════════════════════════════════════════════
# ██  TELEGRAM CALLBACKS
# ═══════════════════════════════════════════════════════════════════════
def _register_callbacks(bot_instance):
    @bot_instance.callback_query_handler(func=lambda call: True)
    def handle_callback(call):
        data = call.data
        try:
            # ── KILL + SHUTDOWN ───────────────────────────────────
            if data.startswith("kill_"):
                try: pid = int(data.split("_")[1])
                except (IndexError, ValueError):
                    bot_instance.answer_callback_query(call.id, "❌ Invalid PID."); return
                bot_instance.answer_callback_query(call.id, "⚠️ Killing + Backup + Shutdown…")
                # Clear pending flag and watchdog kwargs before shutdown
                _explicit_allow_pending.clear()
                with _pending_alert_kwargs_lock:
                    _pending_alert_kwargs.clear()
                killed_pids, failed_pids = [], []
                targets = [pid] if pid != 0 else []
                with _frozen_lock: targets += [p for p in _frozen_pids if p != pid]
                for target_pid in targets:
                    try:
                        psutil.Process(target_pid).kill(); killed_pids.append(target_pid)
                        log("info", f"Killed PID {target_pid} via KILL button.")
                    except psutil.NoSuchProcess: killed_pids.append(target_pid)
                    except Exception as e:
                        failed_pids.append(target_pid)
                        log("error", f"Error killing PID {target_pid}: {e}")
                    finally:
                        with _frozen_lock: _frozen_pids.discard(target_pid)
                parts = []
                if killed_pids: parts.append(f"🔫 Killed PIDs: {killed_pids}")
                if failed_pids: parts.append(f"⚠️ Could not kill: {failed_pids}")
                parts.append("💾 Backup + shutdown starting…")
                _send_telegram_message("\n".join(parts))
                threading.Thread(target=full_backup_and_shutdown,
                                 daemon=False, name="KillBackupShutdown").start()

            # ── ALLOW (Feature 1: only path that authorizes unlock) ──
            elif data.startswith("allow_") or data == "allow_offline_unlock":
                bot_instance.answer_callback_query(call.id, "✅ Unlocking system…")

                # Parse PID (0 for offline unlock)
                pid = 0
                if data.startswith("allow_") and data != "allow_offline_unlock":
                    try: pid = int(data.split("_")[1])
                    except (IndexError, ValueError): pid = 0

                # Feature 1: Use the authorized unlock path
                resumed_ok, resumed_fail = _do_authorized_unlock(pid, bot_instance)

                # Clear watchdog state — alert is resolved
                with _pending_alert_kwargs_lock:
                    _pending_alert_kwargs.clear()

                # Also clear offline lock if it was the connectivity unlock button
                if data == "allow_offline_unlock":
                    with _offline_lock_lock:
                        global _offline_lock_active
                        _offline_lock_active = False

                parts = []
                if resumed_ok:   parts.append(f"✅ Resumed PIDs: {resumed_ok}")
                if resumed_fail: parts.append(f"⚠️ Could not resume: {resumed_fail}")
                if not resumed_ok and not resumed_fail: parts.append("ℹ️ No frozen processes found.")
                parts.append("🔓 System UNLOCKED — monitoring continues.")
                _send_telegram_message("\n".join(parts))

                # Feature 1: Edit the original alert message to show confirmed state.
                # This updates the message in Telegram so the user sees it was handled.
                with _pending_alert_message_lock:
                    msg_id = _pending_alert_message_id
                if msg_id:
                    try:
                        bot_instance.edit_message_text(
                            chat_id    = CHAT_ID,
                            message_id = msg_id,
                            text       = (f"✅ *ALERT RESOLVED*\n{'─'*28}\n"
                                          f"🔓 System has been UNLOCKED.\n"
                                          f"🕐 Time : `{datetime.now().strftime('%H:%M:%S')}`\n"
                                          f"👤 Action taken: ALLOW by operator.\n"
                                          f"{'─'*28}\n"
                                          f"_Monitoring continues normally._"),
                            parse_mode = "Markdown"
                        )
                    except Exception as e:
                        log("debug", f"Could not edit alert message (non-critical): {e}")

                log("info", "ALLOW executed — system unlocked, processes resumed.")

            # ── RESTORE ───────────────────────────────────────────
            elif data == "restore":
                bot_instance.answer_callback_query(call.id, "♻️ Restore started…")
                threading.Thread(target=restore_latest_backup,
                                 daemon=True, name="RestoreBackup").start()
            else:
                bot_instance.answer_callback_query(call.id, "❓ Unknown action.")
        except Exception as e:
            log("error", f"Callback handler error: {e}")
            try: bot_instance.answer_callback_query(call.id, "❌ Internal error.")
            except: pass

# ═══════════════════════════════════════════════════════════════════════
# ██  ALERT WATCHDOG  (v5.3.3 — re-send if message deleted before ALLOW)
# ═══════════════════════════════════════════════════════════════════════
def _alert_watchdog() -> None:
    """
    Daemon thread started alongside every ransomware alert send.

    Every ALERT_WATCHDOG_INTERVAL seconds it probes whether the Telegram
    alert message still exists by attempting to forward it to the same chat.
    If Telegram returns a "not found" / "invalid" error the message was
    deleted by the user.  _resend_pending_alert() is called to put it back.

    The thread exits cleanly when:
    - _explicit_allow_pending is cleared (ALLOW or KILL was pressed), OR
    - _stop_monitor_event is set (engine stopped).
    """
    log("info", "[AlertWatchdog] started.")

    while (not _stop_monitor_event.is_set()
           and _explicit_allow_pending.is_set()):

        _stop_monitor_event.wait(timeout=ALERT_WATCHDOG_INTERVAL)

        # Re-check after waking — ALLOW may have arrived during sleep
        if not _explicit_allow_pending.is_set() or _stop_monitor_event.is_set():
            break

        if not _bot or not _is_online():
            continue

        with _pending_alert_message_lock:
            msg_id = _pending_alert_message_id

        if not msg_id:
            continue

        # Probe existence by forwarding the message back to the same chat.
        # Success → message still exists; delete the probe copy.
        # "not found" / "invalid" error → message was deleted → re-send.
        try:
            probe = _bot.forward_message(
                chat_id=CHAT_ID, from_chat_id=CHAT_ID, message_id=msg_id)
            # Message still exists — silently delete the probe copy
            try:
                _bot.delete_message(CHAT_ID, probe.message_id)
            except Exception:
                pass
            log("debug", f"[AlertWatchdog] Message {msg_id} confirmed present.")

        except Exception as probe_err:
            err_str = str(probe_err).lower()
            if any(k in err_str for k in ("not found", "invalid", "message_id_invalid",
                                           "message to forward not found")):
                log("warning",
                    f"[AlertWatchdog] Message {msg_id} was DELETED — re-sending alert.")
                _resend_pending_alert()
            else:
                log("debug", f"[AlertWatchdog] Probe error (non-deletion): {probe_err}")

    log("info", "[AlertWatchdog] exited.")


def _resend_pending_alert() -> None:
    """
    Re-sends the stored alert with ALLOW / KILL buttons and updates
    _pending_alert_message_id with the new message_id.
    Called exclusively by _alert_watchdog on message-deleted detection.
    """
    global _pending_alert_message_id

    with _pending_alert_kwargs_lock:
        kwargs = dict(_pending_alert_kwargs)

    if not kwargs or not _bot:
        return

    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("❌ KILL + SHUTDOWN",
                             callback_data=kwargs.get("kill_cb", "kill_0")),
        InlineKeyboardButton("✅ ALLOW",
                             callback_data=kwargs.get("allow_cb", "allow_0")))
    markup.add(InlineKeyboardButton("♻️ RESTORE FILES", callback_data="restore"))

    resend_text = (
        "🔁 *ALERT RE-SENT* _(previous message was deleted)_\n\n"
        + kwargs.get("text", "⚠️ RANSOMWARE ALERT — System is still LOCKED.")
    )

    try:
        sent = _bot.send_message(
            CHAT_ID,
            resend_text,
            parse_mode="Markdown",
            reply_markup=markup,
            protect_content=True,
        )
        with _pending_alert_message_lock:
            _pending_alert_message_id = sent.message_id
        log("info", f"[AlertWatchdog] Alert re-sent → new msg_id={sent.message_id}")
    except Exception as e:
        log("error", f"[AlertWatchdog] Failed to re-send alert: {e}")


# ═══════════════════════════════════════════════════════════════════════
# ██  ALERT PIPELINE
# ═══════════════════════════════════════════════════════════════════════
def _run_alert(action_type: str, file_name: str) -> None:
    if not _alert_semaphore.acquire(blocking=False):
        log("debug", f"Alert semaphore cap — dropped: {file_name}"); return
    alert_uid = str(uuid.uuid4())
    try:
        risk = _record_and_score()
        log("warning", f"FIRING ALERT [{action_type}] {file_name} | risk={risk} | uid={alert_uid}")
        if action_type == "DELETED":
            threading.Thread(target=_auto_backup_on_delete, args=(file_name,),
                             daemon=False, name="DeleteBackup").start()
        suspicious = _get_suspicious_processes(top_n=3)
        frozen_ok  = []
        for proc in suspicious:
            if _suspend(proc): frozen_ok.append(proc)
            else: log("warning", f"Could not freeze PID {proc.pid} — continuing.")
        log("info", f"Frozen: {[p.pid for p in frozen_ok]}")
        lock_system(action_type, file_name, _risk_label(risk))
        if risk >= RISK_THRESHOLD:
            log("warning", "HIGH risk — triggering auto-backup.")
            threading.Thread(target=_trigger_backup_only, daemon=True, name="AutoBackup").start()
        _show_notification(f"⚠️ {action_type} Detected! System LOCKED.",
                           f"File: {os.path.basename(file_name)} | {_risk_label(risk)} | "
                           f"{len(frozen_ok)} process(es) frozen")
        _send_telegram_alert(action_type, file_name, frozen_ok, risk, alert_uid)
    except Exception as e:
        log("error", f"_run_alert error: {e}")
    finally:
        _alert_semaphore.release()

# ═══════════════════════════════════════════════════════════════════════
# ██  PATH FILTER
# ═══════════════════════════════════════════════════════════════════════
def _is_excluded(file_name: str) -> bool:
    norm = file_name.lower().replace("\\", "/")
    for part in norm.split("/"):
        if part in EXCLUDED_DIRS: return True
    base = os.path.basename(norm)
    if base == os.path.basename(LOG_FILE).lower(): return True
    if base.startswith("backup_") and base.endswith(".zip"): return True
    if "restored" in norm: return True
    # Skip vault directory itself to prevent observer feedback loops
    try:
        abs_file = os.path.abspath(os.path.join(WATCH_PATH, file_name))
        if abs_file.startswith(os.path.abspath(BACKUP_DIR) + os.sep):
            return True
    except Exception:
        pass
    return False

# ═══════════════════════════════════════════════════════════════════════
# ██  FOLDER MONITOR  (WaitForMultipleObjects — v5.1 fix)
# ═══════════════════════════════════════════════════════════════════════
def monitor_folder(path: str) -> None:
    path = os.path.abspath(path)
    log("info", f"Starting folder monitor: {path}")
    stop_handle = win32event.CreateEvent(None, True, False, None)

    def _signal_stop():
        _stop_monitor_event.wait()
        try: win32event.SetEvent(stop_handle)
        except: pass
    threading.Thread(target=_signal_stop, daemon=True, name="StopHandleSignaller").start()

    while not _stop_monitor_event.is_set():
        hDir = None
        try:
            hDir = win32file.CreateFile(
                path, win32con.GENERIC_READ,
                win32con.FILE_SHARE_READ | win32con.FILE_SHARE_WRITE | win32con.FILE_SHARE_DELETE,
                None, win32con.OPEN_EXISTING,
                win32con.FILE_FLAG_BACKUP_SEMANTICS | win32con.FILE_FLAG_OVERLAPPED, None)
            overlapped        = pywintypes.OVERLAPPED()
            overlapped.hEvent = win32event.CreateEvent(None, True, False, None)
            buf               = win32file.AllocateReadBuffer(65536)
            WATCH_FLAGS = (win32con.FILE_NOTIFY_CHANGE_FILE_NAME |
                           win32con.FILE_NOTIFY_CHANGE_DIR_NAME  |
                           win32con.FILE_NOTIFY_CHANGE_ATTRIBUTES|
                           win32con.FILE_NOTIFY_CHANGE_SIZE      |
                           win32con.FILE_NOTIFY_CHANGE_LAST_WRITE|
                           win32con.FILE_NOTIFY_CHANGE_SECURITY)
            log("info", "Folder handle open — watching ALL file types…")
            while not _stop_monitor_event.is_set():
                win32file.ReadDirectoryChangesW(hDir, buf, True, WATCH_FLAGS, overlapped)
                rc = win32event.WaitForMultipleObjects(
                    [overlapped.hEvent, stop_handle], False, win32event.INFINITE)
                if _stop_monitor_event.is_set(): break
                if rc == win32event.WAIT_OBJECT_0:
                    try:
                        nbytes  = win32file.GetOverlappedResult(hDir, overlapped, False)
                        results = win32file.FILE_NOTIFY_INFORMATION(buf, nbytes)
                    except Exception as e:
                        log("debug", f"GetOverlappedResult: {e}")
                        win32event.ResetEvent(overlapped.hEvent); continue
                    win32event.ResetEvent(overlapped.hEvent)
                    for action_code, file_name in results:
                        if _is_excluded(file_name): continue
                        action_str = ACTION_MAP.get(action_code, f"UNKNOWN({action_code})")
                        log("debug", f"[RAW] {action_str}: {file_name}")

                        # ── v5.3.4: Real-time vault operations ───────────
                        abs_file = os.path.join(WATCH_PATH, file_name)
                        if action_str in ("CREATED", "MODIFIED"):
                            if os.path.isfile(abs_file):
                                threading.Thread(
                                    target=_vault_copy,
                                    args=(abs_file, action_str[:3] + "-VAULT"),
                                    daemon=True,
                                    name="VaultCopy"
                                ).start()
                        elif action_str == "DELETED":
                            rel = os.path.relpath(abs_file, WATCH_PATH)
                            threading.Thread(
                                target=_vault_restore,
                                args=(rel,),
                                daemon=True,
                                name="VaultRestore"
                            ).start()
                        # ─────────────────────────────────────────────────

                        enqueue_event(action_str, file_name)
        except Exception as e:
            if not _stop_monitor_event.is_set():
                log("error", f"Monitor crashed: {e} — restarting in 3 s…")
                _stop_monitor_event.wait(timeout=3)
        finally:
            if hDir:
                try: win32file.CloseHandle(hDir)
                except: pass
    try: win32file.CloseHandle(stop_handle)
    except: pass
    log("info", "[FolderMonitor] exited cleanly.")

# ═══════════════════════════════════════════════════════════════════════
# ██  TELEGRAM POLLING  (v5.3.3 — exponential backoff, event-driven exit)
# ═══════════════════════════════════════════════════════════════════════
def _start_telegram_polling() -> None:
    """
    Robust long-polling loop with exponential backoff on errors.

    Improvements over v5.3.2:
    - POLLING_TIMEOUT (10 s) for get_updates — proper long-polling, no
      hammering the Telegram API every 3 s.
    - On exception: waits POLLING_BACKOFF_BASE * 2^fail_streak seconds,
      capped at POLLING_BACKOFF_MAX (60 s).  Resets to zero on success.
    - Sleeps via _stop_monitor_event.wait() — exits immediately on engine
      stop even while mid-backoff sleep.
    - fail_streak counter is logged with each retry for diagnostics.
    """
    log("info", "[TelegramPolling] started.")
    offset      = None
    backoff     = POLLING_BACKOFF_BASE
    fail_streak = 0

    while not _stop_monitor_event.is_set():
        if not _bot:
            _stop_monitor_event.wait(timeout=1)
            continue
        try:
            updates = _bot.get_updates(
                offset               = offset,
                timeout              = POLLING_TIMEOUT,
                long_polling_timeout = POLLING_TIMEOUT,
                allowed_updates      = ["callback_query", "message"],
            )
            # Successful response — reset backoff counter
            backoff     = POLLING_BACKOFF_BASE
            fail_streak = 0

            for update in updates:
                if _stop_monitor_event.is_set():
                    break
                offset = update.update_id + 1
                try:
                    _bot.process_new_updates([update])
                except Exception as e:
                    log("warning", f"[TelegramPolling] update processing error: {e}")

        except Exception as e:
            if _stop_monitor_event.is_set():
                break
            fail_streak += 1
            wait = min(backoff * (2 ** (fail_streak - 1)), POLLING_BACKOFF_MAX)
            log("error",
                f"[TelegramPolling] error (streak={fail_streak}): {e} "
                f"— retrying in {wait:.0f} s…")
            _stop_monitor_event.wait(timeout=wait)

    log("info", "[TelegramPolling] exited cleanly.")

# ═══════════════════════════════════════════════════════════════════════
# ██  CPU WARMUP
# ═══════════════════════════════════════════════════════════════════════
def _warmup_cpu() -> None:
    log("info", "Warming up CPU monitor…")
    for p in psutil.process_iter():
        try: p.cpu_percent(interval=None)
        except: pass
    time.sleep(1)
    log("info", "CPU monitor ready.")

# ═══════════════════════════════════════════════════════════════════════
# ██  ENGINE START / STOP / RESET / TEST
# ═══════════════════════════════════════════════════════════════════════
def engine_start(token: str, chat_id: str, watch_path: str) -> str:
    global BOT_TOKEN, CHAT_ID, WATCH_PATH, LOG_FILE, _monitoring_active
    global _bot, _coalesce_buffer, _last_alert, _sent_alert_ids
    global _sent_ids_time, _frozen_pids, _risk_score_current
    global _shutdown_initiated, _backup_in_progress, _alert_semaphore
    global _offline_lock_active, _last_known_online, _pending_alert_message_id
    global BACKUP_DIR

    if not token.strip():            return "Bot Token cannot be empty."
    if not chat_id.strip():          return "Chat ID cannot be empty."
    if not os.path.isdir(watch_path):return f"Watch path does not exist: {watch_path}"
    if _monitoring_active:           return "Monitoring is already running."

    BOT_TOKEN  = token.strip()
    CHAT_ID    = chat_id.strip()
    WATCH_PATH = os.path.abspath(watch_path)

    # Compute vault path: sibling of WATCH_PATH → avoids observer feedback loops
    BACKUP_DIR = os.path.join(os.path.dirname(WATCH_PATH),
                              os.path.basename(WATCH_PATH) + "_RG_Vault")

    with _coalesce_lock:  _coalesce_buffer.clear()
    with _throttle_lock:  _last_alert.clear()
    with _sent_ids_lock:  _sent_alert_ids.clear(); _sent_ids_time.clear()
    with _risk_lock:      _change_times.clear()
    with _frozen_lock:    _frozen_pids.clear()
    _shutdown_initiated.clear()
    _stop_monitor_event.clear()
    _lock_release_event.clear()
    _coalesce_event.clear()
    _alert_semaphore     = threading.Semaphore(MAX_ALERT_THREADS)
    _risk_score_current  = 0
    _backup_in_progress  = False

    # Reset new Feature 1 & 2 state
    _explicit_allow_pending.clear()
    with _offline_lock_lock:
        _offline_lock_active = False
    _last_known_online = True  # Assume online at start; monitor will detect otherwise
    with _pending_alert_message_lock:
        _pending_alert_message_id = 0

    _ensure_file_handler()
    LOG_FILE = os.path.join(WATCH_PATH, "ransomware_guard.log")

    if not _HAS_TELEBOT: return "pyTeleBot not installed. Run: pip install pyTeleBot"
    try:
        _bot = telebot.TeleBot(BOT_TOKEN, threaded=False)
        _register_callbacks(_bot)
    except Exception as e:
        return f"Bot initialisation failed: {e}"

    _monitoring_active = True

    def _startup():
        _warmup_cpu()
        online = _is_online()
        log("info", f"Network status: {'ONLINE' if online else 'OFFLINE'}")
        if online:
            try:
                me = _bot.get_me()
                log("info", f"Telegram bot connected: @{me.username}")
                _bot.send_message(CHAT_ID,
                    f"🛡️ *RansomwareGuard v5.3.4 STARTED*\n"
                    f"📁 Watching : `{WATCH_PATH}`\n"
                    f"💾 Vault    : `{BACKUP_DIR}`\n"
                    f"🕐 Time     : `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n"
                    f"🔒 System Lock     : ENABLED\n"
                    f"📶 Offline Lock    : ENABLED (checks every {CONNECTIVITY_CHECK_INTERVAL}s)\n"
                    f"🔐 Persistent Lock : ENABLED (requires explicit ALLOW)\n"
                    f"🗑️ Delete restore  : ENABLED (instant vault recovery)\n"
                    f"📡 Mode            : ONLINE",
                    parse_mode="Markdown")
            except Exception as e:
                log("error", f"Startup Telegram check failed: {e}")
        else:
            log("warning", "Starting in OFFLINE mode — desktop notifications only.")

        # v5.3.4: Full mirror before threads go live
        threading.Thread(target=initial_sync, daemon=True, name="InitialSync").start()

        threading.Thread(target=_coalesce_dispatcher, daemon=True, name="CoalesceDispatcher").start()
        threading.Thread(target=_cleanup_throttle_cache, daemon=True, name="ThrottleCleanup").start()
        threading.Thread(target=_start_telegram_polling, daemon=True, name="TelegramPolling").start()
        threading.Thread(target=monitor_folder, args=(WATCH_PATH,), daemon=True, name="FolderMonitor").start()
        # Feature 2: Start connectivity monitor
        threading.Thread(target=_connectivity_monitor, daemon=True, name="ConnectivityMonitor").start()
        log("info", "✅ RansomwareGuard v5.3.4 — ALL THREADS LIVE")

    threading.Thread(target=_startup, daemon=True, name="Startup").start()
    return ""

def engine_stop() -> None:
    """Non-blocking stop. Clears both new feature flags before unlocking."""
    global _monitoring_active
    _graceful_stop()
    _monitoring_active = False

    def _stop_bot_async():
        if _bot:
            try:
                _bot.stop_polling()
                log("info", "[TelegramPolling] stop_polling() acknowledged.")
            except Exception as e:
                log("warning", f"stop_polling() raised (non-critical): {e}")
    threading.Thread(target=_stop_bot_async, daemon=True, name="BotStopAsync").start()

def engine_reset() -> None:
    global _risk_score_current
    with _coalesce_lock: _coalesce_buffer.clear()
    with _throttle_lock: _last_alert.clear()
    with _sent_ids_lock: _sent_alert_ids.clear(); _sent_ids_time.clear()
    with _risk_lock:     _change_times.clear(); _risk_score_current = 0
    with _gui_log_lock:  _gui_log_queue.clear()
    log("info", "🔄 State RESET — risk baseline cleared, log cleared.")

def engine_test_connection(token: str, chat_id: str) -> tuple:
    if not token.strip():    return False, "Bot Token is empty."
    if not chat_id.strip():  return False, "Chat ID is empty."
    if not _is_online():     return False, "No internet connection."
    try:
        test_bot = telebot.TeleBot(token.strip(), threaded=False)
        me       = test_bot.get_me()
        test_bot.send_message(chat_id.strip(),
            "✅ *RansomwareGuard* — Connection test successful!\n"
            "Your Bot Token and Chat ID are configured correctly.",
            parse_mode="Markdown")
        return True, f"Connected as @{me.username}"
    except Exception as e:
        return False, str(e)

# ═══════════════════════════════════════════════════════════════════════
# ██  HELP POPUP
# ═══════════════════════════════════════════════════════════════════════
class TelegramHelpPopup(tk.Toplevel):
    STEPS = [
        ("1", "Create a Bot → Get API Token",
         "Open @BotFather on Telegram, send /newbot,\n"
         "follow the prompts, then copy your API Token.",
         "Open @BotFather", "https://t.me/BotFather"),
        ("2", "Find Your Chat ID",
         "Open @userinfobot on Telegram, press START,\n"
         "and it will reply with your numeric Chat ID.",
         "Open @userinfobot", "https://t.me/userinfobot"),
        ("3", "Paste into the fields & Test",
         'Copy both values into the fields on the\n'
         'dashboard, then click "Test Telegram Connection".',
         None, None),
    ]

    def __init__(self, parent):
        super().__init__(parent)
        self.title("How to Get Your Telegram IDs")
        self.configure(bg=C_SURFACE)
        self.resizable(False, False)
        self.grab_set()
        W, H = 490, 430
        self.update_idletasks()
        try:
            px = parent.winfo_rootx(); py = parent.winfo_rooty()
            pw = parent.winfo_width(); ph = parent.winfo_height()
        except Exception:
            px, py, pw, ph = 200, 200, 800, 600
        self.geometry(f"{W}x{H}+{px+(pw-W)//2}+{py+(ph-H)//2}")
        self._build()

    def _build(self):
        hdr = tk.Frame(self, bg=C_ELEVATED)
        hdr.pack(fill="x")
        tk.Label(hdr, text="📋", font=("Segoe UI Emoji", 17),
                 bg=C_ELEVATED, fg=C_CYAN).pack(side="left", padx=(18, 8), pady=14)
        tk.Label(hdr, text="Setup Guide — Telegram Credentials",
                 font=F_H1, bg=C_ELEVATED, fg=C_TEXT1).pack(side="left", pady=14)
        tk.Frame(self, bg=C_BORDER2, height=1).pack(fill="x")
        body = tk.Frame(self, bg=C_SURFACE)
        body.pack(fill="both", expand=True, padx=16, pady=14)
        for num, title, desc, link_txt, link_url in self.STEPS:
            card = tk.Frame(body, bg=C_CARD, highlightbackground=C_BORDER2, highlightthickness=1)
            card.pack(fill="x", pady=(0, 10))
            tk.Label(card, text=num, font=F_BADGE,
                     bg=C_CYAN, fg=C_BASE, width=3, height=1).pack(side="left", padx=(12, 14), pady=14)
            right = tk.Frame(card, bg=C_CARD)
            right.pack(side="left", fill="both", expand=True, pady=10, padx=(0, 12))
            tk.Label(right, text=title, font=("Segoe UI Semibold", 10),
                     bg=C_CARD, fg=C_TEXT1, anchor="w").pack(anchor="w")
            tk.Label(right, text=desc, font=F_SMALL,
                     bg=C_CARD, fg=C_TEXT2, justify="left", anchor="w").pack(anchor="w")
            if link_txt and link_url:
                u = link_url
                lbl = tk.Label(right, text=link_txt, font=F_SMALL, bg=C_CARD, fg=C_CYAN, cursor="hand2")
                lbl.pack(anchor="w", pady=(3, 0))
                lbl.bind("<Button-1>", lambda e, url=u: webbrowser.open(url))
                lbl.bind("<Enter>",    lambda e, w=lbl: w.config(fg=C_BLUE))
                lbl.bind("<Leave>",    lambda e, w=lbl: w.config(fg=C_CYAN))
        tk.Frame(self, bg=C_BORDER, height=1).pack(fill="x")
        foot = tk.Frame(self, bg=C_SURFACE)
        foot.pack(fill="x", padx=16, pady=10)
        tk.Button(foot, text="  Close  ", font=F_BTN,
                  bg=C_CARD, fg=C_TEXT2,
                  activebackground=C_HOVER, activeforeground=C_TEXT1,
                  relief="flat", cursor="hand2", bd=0, pady=6,
                  command=self.destroy).pack(side="right")

# ═══════════════════════════════════════════════════════════════════════
# ██  MAIN GUI  — RansomGuardGUI v5.3.2
# ═══════════════════════════════════════════════════════════════════════
class RansomGuardGUI:

    def __init__(self):
        if _HAS_CTK:
            self.root = ctk.CTk()
        else:
            self.root = tk.Tk()

        self.root.title("🛡️  RansomwareGuard v5.3.2  —  Cybersecurity Dashboard")
        self.root.configure(bg=C_BASE)
        self.root.minsize(900, 600)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        try:
            self.root.state("zoomed")
        except Exception:
            try:
                self.root.attributes("-zoomed", True)
            except Exception:
                self.root.geometry("1280x800")

        self._led_blink_on   = False
        self._led_state      = "stopped"
        self._event_count    = 0
        self._token_vis      = False
        self._chatid_vis     = False
        self._sidebar_vis    = True
        self._save_var       = tk.BooleanVar(value=False)

        self._build_ui()
        self._load_saved_config()
        self._poll_log()
        self._poll_status()
        self.root.mainloop()

    # ── LAYOUT ───────────────────────────────────────────────────
    def _build_ui(self):
        r = self.root
        r.rowconfigure(0, weight=0)
        r.rowconfigure(1, weight=1)
        r.rowconfigure(2, weight=0)
        r.columnconfigure(0, weight=1)
        self._build_topbar(r)
        self._build_body(r)
        self._build_statusbar(r)

    def _build_topbar(self, parent):
        bar = tk.Frame(parent, bg=C_BLUE, height=56)
        bar.grid(row=0, column=0, sticky="ew")
        bar.grid_propagate(False)
        bar.columnconfigure(1, weight=1)

        logo_f = tk.Frame(bar, bg=C_BLUE)
        logo_f.grid(row=0, column=0, padx=(18, 0), sticky="w")
        tk.Label(logo_f, text="🛡️", font=("Segoe UI Emoji", 20),
                 bg=C_BLUE, fg="#ffffff").pack(side="left", pady=12)
        tk.Label(logo_f, text="  RansomwareGuard",
                 font=("Segoe UI Semibold", 14), bg=C_BLUE, fg="#ffffff").pack(side="left")
        tk.Label(logo_f, text="  v5.3.2  FULL LOCK + OFFLINE EDITION",
                 font=("Segoe UI", 9), bg=C_BLUE, fg="#b3d1f5").pack(side="left", pady=2)

        right_f = tk.Frame(bar, bg=C_BLUE)
        right_f.grid(row=0, column=2, padx=(0, 18), sticky="e")

        tk.Button(right_f, text="≡", font=("Segoe UI", 16),
                  bg=C_BLUE, fg="#ffffff",
                  activebackground=C_CYAN, activeforeground="#ffffff",
                  relief="flat", cursor="hand2", bd=0,
                  command=self._toggle_sidebar).pack(side="left", padx=(0, 18))

        self._status_lbl = tk.Label(right_f, text="STOPPED",
                                     font=("Segoe UI Semibold", 9),
                                     bg=C_BLUE, fg="#b3d1f5")
        self._status_lbl.pack(side="right", padx=(0, 6))

        self._led_cv = tk.Canvas(right_f, width=14, height=14, bg=C_BLUE, highlightthickness=0)
        self._led_cv.pack(side="right", pady=19)
        self._led_oval = self._led_cv.create_oval(1, 1, 13, 13, fill=C_STOPPED, outline="")

        tk.Frame(parent, bg=C_BORDER, height=1).grid(row=0, column=0, sticky="ew", pady=(56, 0))

    def _build_body(self, parent):
        body = tk.Frame(parent, bg=C_BASE)
        body.grid(row=1, column=0, sticky="nsew")
        body.columnconfigure(0, weight=0)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)

        self._sidebar = tk.Frame(body, bg=C_SURFACE, width=330)
        self._sidebar.grid(row=0, column=0, sticky="nsew")
        self._sidebar.grid_propagate(False)
        self._build_sidebar(self._sidebar)

        tk.Frame(body, bg=C_BORDER, width=1).grid(row=0, column=0, sticky="ns", padx=(330, 0))

        main = tk.Frame(body, bg=C_BASE)
        main.grid(row=0, column=1, sticky="nsew")
        main.rowconfigure(0, weight=0)
        main.rowconfigure(1, weight=0)
        main.rowconfigure(2, weight=1)
        main.columnconfigure(0, weight=1)

        self._build_metric_tiles(main)
        self._build_log_panel(main)

    def _build_sidebar(self, parent):
        cv = tk.Canvas(parent, bg=C_SURFACE, highlightthickness=0)
        sb = tk.Scrollbar(parent, orient="vertical", command=cv.yview)
        cv.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        cv.pack(side="left", fill="both", expand=True)
        inner = tk.Frame(cv, bg=C_SURFACE)
        win_id = cv.create_window((0, 0), window=inner, anchor="nw")

        def _on_cv_resize(e): cv.itemconfig(win_id, width=e.width)
        def _on_inner_resize(e): cv.configure(scrollregion=cv.bbox("all"))
        def _on_wheel(e): cv.yview_scroll(-1 * (e.delta // 120), "units")

        cv.bind("<Configure>", _on_cv_resize)
        inner.bind("<Configure>", _on_inner_resize)
        cv.bind_all("<MouseWheel>", _on_wheel)
        inner.columnconfigure(0, weight=1)

        self._build_telegram_section(inner)
        self._build_path_section(inner)
        self._build_controls_section(inner)
        self._build_stats_section(inner)

    def _section(self, parent, icon: str, title: str) -> tk.Frame:
        wrap = tk.Frame(parent, bg=C_SURFACE)
        wrap.pack(fill="x")
        wrap.columnconfigure(0, weight=1)
        title_row = tk.Frame(wrap, bg=C_SURFACE)
        title_row.pack(fill="x", padx=0)
        tk.Label(title_row, text=f"{icon}  {title}",
                 font=F_H2, bg=C_SURFACE, fg=C_CYAN).pack(anchor="w", padx=14, pady=(12, 6))
        tk.Frame(wrap, bg=C_BORDER, height=1).pack(fill="x")
        inner = tk.Frame(wrap, bg=C_SURFACE)
        inner.pack(fill="x", pady=(8, 4))
        inner.columnconfigure(0, weight=1)
        tk.Frame(parent, bg=C_BORDER2, height=1).pack(fill="x")
        return inner

    def _masked_field(self, parent, label_text, var_attr, vis_attr, eye_attr, toggle_cmd):
        tk.Label(parent, text=label_text, font=F_BODY,
                 bg=C_SURFACE, fg=C_TEXT2).pack(anchor="w", padx=14)
        row = tk.Frame(parent, bg=C_SURFACE)
        row.pack(fill="x", padx=14, pady=(3, 10))
        row.columnconfigure(0, weight=1)
        var = tk.StringVar()
        setattr(self, var_attr, var)
        entry = tk.Entry(row, textvariable=var, show="●", font=F_MONO,
                         bg=C_INPUT, fg=C_TEXT1, insertbackground=C_CYAN,
                         relief="flat", bd=0,
                         highlightbackground=C_BORDER2, highlightthickness=1)
        entry.grid(row=0, column=0, sticky="ew", ipady=7)
        eye_btn = tk.Button(row, text="👁", font=("Segoe UI", 10),
                            bg=C_INPUT, fg=C_TEXT3, relief="flat",
                            activebackground=C_INPUT, cursor="hand2", command=toggle_cmd)
        eye_btn.grid(row=0, column=1, padx=(4, 0), ipady=7, ipadx=6)
        setattr(self, eye_attr, eye_btn)
        return entry

    def _build_telegram_section(self, parent):
        inner = self._section(parent, "📡", "Telegram Setup")
        banner = tk.Frame(inner, bg=C_ELEVATED, highlightbackground=C_BLUE, highlightthickness=1)
        banner.pack(fill="x", padx=14, pady=(0, 10))
        banner.columnconfigure(0, weight=1)
        tk.Label(banner,
                 text="To connect Telegram:\n"
                      "  1.  Create a bot using @BotFather\n"
                      "  2.  Get your Chat ID using @userinfobot",
                 font=F_SMALL, bg=C_ELEVATED, fg=C_CYAN,
                 justify="left", anchor="w", wraplength=270).grid(
                     row=0, column=0, padx=10, pady=(8, 4), sticky="w")
        tk.Button(banner, text="📖  Step-by-step help  →", font=F_SMALL,
                  bg=C_ELEVATED, fg=C_BLUE, activebackground=C_ELEVATED,
                  activeforeground=C_CYAN, relief="flat", cursor="hand2", bd=0,
                  command=lambda: TelegramHelpPopup(self.root)).grid(
                      row=1, column=0, padx=10, pady=(0, 8), sticky="w")
        self._token_entry = self._masked_field(
            inner, "Bot Token", "_token_var", "_token_vis", "_eye_token", self._toggle_token)
        self._chatid_entry = self._masked_field(
            inner, "Chat ID", "_chatid_var", "_chatid_vis", "_eye_chatid", self._toggle_chatid)
        self._test_btn = _rounded_btn(
            inner, "🔌  Test Telegram Connection", F_BTN,
            bg=C_BLUE, fg="#ffffff", active_bg=C_CYAN, active_fg="#ffffff",
            command=self._on_test, pady=8)
        self._test_btn.pack(fill="x", padx=14, pady=(0, 4))
        self._test_var = tk.StringVar(value="")
        self._test_lbl = tk.Label(inner, textvariable=self._test_var,
                                   font=F_SMALL, bg=C_SURFACE, fg=C_GREEN,
                                   wraplength=280, justify="left")
        self._test_lbl.pack(anchor="w", padx=14, pady=(0, 4))
        tk.Checkbutton(inner, text="Remember configuration",
                       variable=self._save_var, font=F_SMALL,
                       bg=C_SURFACE, fg=C_TEXT2, selectcolor=C_INPUT,
                       activebackground=C_SURFACE, activeforeground=C_TEXT1,
                       command=self._on_save_toggle).pack(anchor="w", padx=14, pady=(0, 8))

    def _build_path_section(self, parent):
        inner = self._section(parent, "📁", "Watch Path")
        row = tk.Frame(inner, bg=C_SURFACE)
        row.pack(fill="x", padx=14, pady=(0, 10))
        row.columnconfigure(0, weight=1)
        self._path_var = tk.StringVar(value=WATCH_PATH)
        tk.Entry(row, textvariable=self._path_var, font=F_MONO,
                 bg=C_INPUT, fg=C_TEXT1, insertbackground=C_CYAN,
                 relief="flat", bd=0,
                 highlightbackground=C_BORDER2, highlightthickness=1).grid(
                     row=0, column=0, sticky="ew", ipady=7)
        tk.Button(row, text="📂", font=("Segoe UI", 11),
                  bg=C_INPUT, fg=C_CYAN, relief="flat",
                  activebackground=C_HOVER, cursor="hand2",
                  command=self._browse).grid(row=0, column=1, padx=(4, 0), ipady=6)

    def _build_controls_section(self, parent):
        inner = self._section(parent, "🎛️", "Controls")

        self._btn_start = _rounded_btn(
            inner, "▶   START MONITORING", F_BTN_LG,
            bg=C_GREEN, fg="#ffffff", active_bg="#1b5e20", active_fg="#ffffff",
            command=self._on_start, pady=11)
        self._btn_start.pack(fill="x", padx=14, pady=(0, 6))

        self._btn_stop = _rounded_btn(
            inner, "⏹   STOP MONITORING", F_BTN_LG,
            bg=C_RED, fg="#ffffff", active_bg="#7f0000", active_fg="#ffffff",
            command=self._on_stop, state="disabled", pady=11)
        self._btn_stop.pack(fill="x", padx=14, pady=(0, 6))

        _rounded_btn(
            inner, "🔄   RESET LOG & RISK", F_BTN,
            bg=C_BLUE, fg="#ffffff", active_bg="#0d47a1", active_fg="#ffffff",
            command=self._on_reset, pady=9).pack(fill="x", padx=14, pady=(0, 10))

    def _build_stats_section(self, parent):
        inner = self._section(parent, "📊", "Live Statistics")
        grid = tk.Frame(inner, bg=C_SURFACE)
        grid.pack(fill="x", padx=14, pady=(0, 10))
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)

        def _mini(row, col, lbl_text):
            tile = tk.Frame(grid, bg=C_CARD, highlightbackground=C_BORDER, highlightthickness=1)
            tile.grid(row=row, column=col, padx=(0, 4) if col == 0 else 0, pady=3, sticky="ew")
            tk.Label(tile, text=lbl_text, font=F_METRIC_LB,
                     bg=C_CARD, fg=C_TEXT3).pack(anchor="w", padx=8, pady=(6, 0))
            v = tk.StringVar(value="—")
            lbl = tk.Label(tile, textvariable=v, font=("Segoe UI Semibold", 11),
                           bg=C_CARD, fg=C_TEXT1)
            lbl.pack(anchor="w", padx=8, pady=(0, 6))
            return v, lbl

        self._sv_status,  self._sl_status  = _mini(0, 0, "Status")
        self._sv_risk,    self._sl_risk    = _mini(0, 1, "Risk")
        self._sv_events,  self._sl_events  = _mini(1, 0, "Events")
        self._sv_frozen,  self._sl_frozen  = _mini(1, 1, "Frozen PIDs")
        self._sv_backups, self._sl_backups = _mini(2, 0, "Backups")
        self._sv_network, self._sl_network = _mini(2, 1, "Network")

        # NEW: extra stat rows for Feature 1 & 2 visibility
        self._sv_pending,  self._sl_pending  = _mini(3, 0, "Alert Pending")
        self._sv_offline,  self._sl_offline  = _mini(3, 1, "Offline Lock")

    def _build_metric_tiles(self, parent):
        tiles_row = tk.Frame(parent, bg=C_BASE)
        tiles_row.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 6))
        for i in range(4):
            tiles_row.columnconfigure(i, weight=1)

        METRICS = [
            ("🛡️", "Protection",  "OFFLINE", C_STOPPED, "_mt_prot"),
            ("⚡",  "Risk Level",  "LOW",     C_GREEN,   "_mt_risk"),
            ("📋",  "Events",      "0",       C_TEXT1,   "_mt_evts"),
            ("🔒",  "Frozen PIDs", "0",       C_TEXT1,   "_mt_froz"),
        ]
        for col, (icon, lbl, init, clr, attr) in enumerate(METRICS):
            tile = tk.Frame(tiles_row, bg=C_CARD,
                            highlightbackground=C_BORDER2, highlightthickness=1)
            tile.grid(row=0, column=col, padx=(0, 10) if col < 3 else 0, sticky="ew")
            tile.columnconfigure(1, weight=1)
            tk.Label(tile, text=icon, font=("Segoe UI Emoji", 22),
                     bg=C_CARD, fg=clr).grid(row=0, column=0, rowspan=2, padx=(14, 10), pady=14)
            tk.Label(tile, text=lbl, font=F_METRIC_LB,
                     bg=C_CARD, fg=C_TEXT3, anchor="w").grid(row=0, column=1, sticky="w", pady=(10, 0))
            var = tk.StringVar(value=init)
            val_lbl = tk.Label(tile, textvariable=var, font=F_METRIC, bg=C_CARD, fg=clr, anchor="w")
            val_lbl.grid(row=1, column=1, sticky="w", pady=(0, 10))
            setattr(self, attr + "_var", var)
            setattr(self, attr + "_lbl", val_lbl)

    def _build_log_panel(self, parent):
        log_hdr = tk.Frame(parent, bg=C_CARD, highlightbackground=C_BORDER, highlightthickness=1)
        log_hdr.grid(row=1, column=0, sticky="ew", padx=16, pady=(0, 2))
        tk.Label(log_hdr, text="📟  Live Terminal Log",
                 font=F_H2, bg=C_CARD, fg=C_CYAN).pack(side="left", padx=14, pady=9)
        self._ts_var = tk.StringVar(value="")
        tk.Label(log_hdr, textvariable=self._ts_var, font=F_MONO_SM,
                 bg=C_CARD, fg=C_TEXT3).pack(side="right", padx=8)
        tk.Button(log_hdr, text="Clear", font=F_SMALL,
                  bg=C_INPUT, fg=C_TEXT2,
                  activebackground=C_HOVER, activeforeground=C_TEXT1,
                  relief="flat", cursor="hand2", bd=0, padx=10, pady=4,
                  command=self._clear_log).pack(side="right", padx=8, pady=7)
        log_wrap = tk.Frame(parent, bg=C_BASE, highlightbackground=C_BORDER, highlightthickness=1)
        log_wrap.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 12))
        self._log_text = scrolledtext.ScrolledText(
            log_wrap, bg=C_INPUT, fg=C_TEXT1, insertbackground=C_BLUE,
            font=F_MONO, relief="flat", bd=0, wrap="word",
            state="disabled", selectbackground=C_BORDER2)
        self._log_text.pack(fill="both", expand=True, padx=6, pady=6)
        self._log_text.tag_config("INFO",     foreground=C_TEXT1)
        self._log_text.tag_config("DEBUG",    foreground=C_TEXT3)
        self._log_text.tag_config("WARNING",  foreground=C_ORANGE)
        self._log_text.tag_config("ERROR",    foreground=C_RED)
        self._log_text.tag_config("CRITICAL", foreground=C_RED)
        self._log_text.tag_config("ALERT",    foreground=C_RED)
        self._log_text.tag_config("OK",       foreground=C_GREEN)
        self._log_text.tag_config("CYAN",     foreground=C_CYAN)

    def _build_statusbar(self, parent):
        tk.Frame(parent, bg=C_BORDER, height=1).grid(row=2, column=0, sticky="ew")
        bar = tk.Frame(parent, bg=C_ELEVATED, height=22)
        bar.grid(row=2, column=0, sticky="ew")
        bar.grid_propagate(False)
        bar.columnconfigure(0, weight=1)
        self._bar_var = tk.StringVar(
            value="Ready  ·  RansomwareGuard v5.3.2  ·  Persistent Lock + Offline Guard")
        tk.Label(bar, textvariable=self._bar_var, font=("Segoe UI", 8),
                 bg=C_ELEVATED, fg=C_TEXT2, anchor="w").pack(side="left", padx=12)
        tk.Label(bar, text="EXE-Ready via PyInstaller",
                 font=("Segoe UI", 8), bg=C_ELEVATED, fg=C_TEXT3).pack(side="right", padx=10)

    # ── POLLING ───────────────────────────────────────────────────
    def _poll_log(self):
        with _gui_log_lock:
            items = _gui_log_queue[:]
            _gui_log_queue.clear()
        if items:
            self._log_text.configure(state="normal")
            for level, msg in items:
                tag = level if level in ("INFO","DEBUG","WARNING","ERROR","CRITICAL") else "INFO"
                if any(w in msg for w in ("ALERT","LOCKED","FIRING","RANSOMWARE","OFFLINE")):
                    tag = "ALERT"
                elif any(w in msg for w in ("LIVE","UNLOCKED","Resumed","Backup complete",
                                             "exited cleanly","ALLOW","RESTORED")):
                    tag = "OK"
                self._log_text.insert("end", msg + "\n", tag)
                self._event_count += 1
            self._log_text.see("end")
            self._log_text.configure(state="disabled")
        self.root.after(100, self._poll_log)

    def _poll_status(self):
        with _frozen_lock:
            fp_count = len(_frozen_pids)

        # Determine LED state — also blink on offline lock
        with _offline_lock_lock:
            is_offline_locked = _offline_lock_active
        is_alert_pending = _explicit_allow_pending.is_set()

        if (fp_count > 0 or is_offline_locked or is_alert_pending) and _monitoring_active:
            self._led_state = "alert"
        elif _monitoring_active:
            self._led_state = "live"
        else:
            self._led_state = "stopped"

        if self._led_state == "live":
            led_col = C_LIVE; st_txt = "LIVE"; st_col = C_LIVE
        elif self._led_state == "alert":
            self._led_blink_on = not self._led_blink_on
            led_col = C_ALERT if self._led_blink_on else "#e57373"
            st_txt = "⚠ ALERT"; st_col = C_ALERT
        else:
            led_col = C_STOPPED; st_txt = "STOPPED"; st_col = C_STOPPED

        self._led_cv.itemconfig(self._led_oval, fill=led_col)
        self._status_lbl.config(text=st_txt, fg=st_col)

        # Metric tiles
        if _monitoring_active:
            self._mt_prot_var.set("ACTIVE")
            self._mt_prot_lbl.config(fg=C_LIVE)
        else:
            self._mt_prot_var.set("OFFLINE")
            self._mt_prot_lbl.config(fg=C_STOPPED)

        score = _risk_score_current
        if score >= RISK_THRESHOLD:   rv, rc = f"HIGH ({score})",  C_RED
        elif score >= RISK_THRESHOLD//2: rv, rc = f"MED ({score})", C_ORANGE
        else:                          rv, rc = f"LOW ({score})",  C_GREEN
        self._mt_risk_var.set(rv); self._mt_risk_lbl.config(fg=rc)
        self._mt_evts_var.set(str(self._event_count))
        self._mt_froz_var.set(str(fp_count))
        self._mt_froz_lbl.config(fg=C_RED if fp_count else C_TEXT1)

        # Mini stats
        self._sv_status.set("🟢 LIVE" if _monitoring_active else "🔴 STOPPED")
        self._sv_risk.set(f"{'🔴' if score>=RISK_THRESHOLD else '🟠' if score>=RISK_THRESHOLD//2 else '🟢'} {score}")
        self._sv_events.set(str(self._event_count))
        self._sv_frozen.set(str(fp_count))
        try:
            bc = len([f for f in os.listdir(WATCH_PATH)
                      if f.startswith("backup_") and f.endswith(".zip")])
            self._sv_backups.set(str(bc))
        except: pass

        online = _is_online()
        self._sv_network.set("🟢 Online" if online else "🔴 Offline")
        self._sl_network.config(fg=C_GREEN if online else C_RED)

        # Feature 1: show pending alert state
        if is_alert_pending:
            self._sv_pending.set("🔴 WAITING")
            self._sl_pending.config(fg=C_RED)
        else:
            self._sv_pending.set("🟢 None")
            self._sl_pending.config(fg=C_GREEN)

        # Feature 2: show offline lock state
        if is_offline_locked:
            self._sv_offline.set("🔴 LOCKED")
            self._sl_offline.config(fg=C_RED)
        else:
            self._sv_offline.set("🟢 Clear")
            self._sl_offline.config(fg=C_GREEN)

        self._ts_var.set(datetime.now().strftime("%Y-%m-%d  %H:%M:%S"))
        interval = 400 if self._led_state == "alert" else 900
        self.root.after(interval, self._poll_status)

    # ── HANDLERS ──────────────────────────────────────────────────
    def _on_start(self):
        token  = self._token_var.get().strip()
        chatid = self._chatid_var.get().strip()
        path   = self._path_var.get().strip()
        err    = engine_start(token, chatid, path)
        if err:
            self._log_gui(f"[ERROR] {err}", "ERROR")
            self._bar_var.set(f"⚠  {err}"); return
        if self._save_var.get():
            save_config(token, chatid, path)
        self._btn_start.config_state("disabled")
        self._btn_stop.config_state("normal")
        self._bar_var.set(f"Monitoring: {path}")
        self._log_gui("▶  Monitoring STARTED — all threads live.", "OK")

    def _on_stop(self):
        engine_stop()
        self._btn_start.config_state("normal")
        self._btn_stop.config_state("disabled")
        self._bar_var.set("Monitoring stopped.")
        self._log_gui("⏹  Monitoring STOPPED — system unlocked.", "WARNING")

    def _on_reset(self):
        engine_reset()
        self._event_count = 0
        self._log_gui("🔄  Log and risk score RESET.", "OK")
        self._bar_var.set("Reset complete.")

    def _on_test(self):
        token  = self._token_var.get().strip()
        chatid = self._chatid_var.get().strip()
        self._test_var.set("⏳  Testing connection…")
        self._test_lbl.config(fg=C_CYAN)
        self._test_btn.config_state("disabled")
        def _run():
            ok, msg = engine_test_connection(token, chatid)
            def _ui_update():
                self._test_btn.config_state("normal")
                if ok:
                    self._test_var.set(f"✅  {msg}")
                    self._test_lbl.config(fg=C_GREEN)
                    self._log_gui(f"[TEST] ✅ Connection OK: {msg}", "OK")
                else:
                    self._test_var.set(f"❌  {msg}")
                    self._test_lbl.config(fg=C_RED)
                    self._log_gui(f"[TEST] ❌ Connection FAILED: {msg}", "ERROR")
            self.root.after(0, _ui_update)
        threading.Thread(target=_run, daemon=True, name="TestConnection").start()

    def _on_save_toggle(self):
        if self._save_var.get():
            save_config(self._token_var.get().strip(),
                        self._chatid_var.get().strip(),
                        self._path_var.get().strip())
            self._log_gui("💾  Configuration saved to config.json", "CYAN")

    def _on_close(self):
        if _monitoring_active:
            engine_stop()
        self.root.destroy()

    def _toggle_sidebar(self):
        if self._sidebar_vis:
            self._sidebar.grid_remove()
            self._sidebar_vis = False
        else:
            self._sidebar.grid()
            self._sidebar_vis = True

    def _toggle_token(self):
        self._token_vis = not self._token_vis
        self._token_entry.config(show="" if self._token_vis else "●")
        self._eye_token.config(fg=C_CYAN if self._token_vis else C_TEXT3)

    def _toggle_chatid(self):
        self._chatid_vis = not self._chatid_vis
        self._chatid_entry.config(show="" if self._chatid_vis else "●")
        self._eye_chatid.config(fg=C_CYAN if self._chatid_vis else C_TEXT3)

    def _browse(self):
        folder = filedialog.askdirectory(title="Select folder to monitor",
                                          initialdir=self._path_var.get())
        if folder: self._path_var.set(folder)

    def _clear_log(self):
        self._log_text.configure(state="normal")
        self._log_text.delete("1.0", "end")
        self._log_text.configure(state="disabled")

    def _log_gui(self, msg: str, tag: str = "INFO"):
        ts   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"{ts} [{tag}] {msg}\n"
        self._log_text.configure(state="normal")
        self._log_text.insert("end", line, tag)
        self._log_text.see("end")
        self._log_text.configure(state="disabled")

    def _load_saved_config(self):
        cfg = load_config()
        if cfg:
            self._token_var.set(cfg.get("token", ""))
            self._chatid_var.set(cfg.get("chat_id", ""))
            self._path_var.set(cfg.get("watch_path", WATCH_PATH))
            self._save_var.set(True)
            self._log_gui("💾  Saved configuration loaded from config.json", "CYAN")

# ═══════════════════════════════════════════════════════════════════════
# ██  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()

    if not _HAS_WIN32:
        import tkinter.messagebox as mb
        root = tk.Tk(); root.withdraw()
        mb.showerror("Missing dependency",
                     "pywin32 is not installed.\n\nRun:\n  pip install pywin32")
        sys.exit(1)

    if not _HAS_PSUTIL:
        import tkinter.messagebox as mb
        root = tk.Tk(); root.withdraw()
        mb.showerror("Missing dependency",
                     "psutil is not installed.\n\nRun:\n  pip install psutil")
        sys.exit(1)

    RansomGuardGUI()
    

