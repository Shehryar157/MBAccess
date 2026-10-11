"""The installer's windows, built from Windows' own dialog parts through ctypes.

A dialog is described to Windows as a block of bytes (a dialog template: the window,
then each control with its position, kind and text), the way a program's built-in
dialogs are stored; Windows then runs it with its usual Tab, Enter and Escape keys, and
screen readers read it like any standard dialog.

- ask_update(): the "update found" dialog (what's new, Update / Skip).
- Progress: a window with a progress bar, a status line and Cancel, shown while a job
  runs in a background thread.
"""
import ctypes
import struct
import threading
import time
from ctypes import wintypes

user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32

WS_CHILD, WS_VISIBLE, WS_TABSTOP, WS_BORDER, WS_VSCROLL = 0x40000000, 0x10000000, 0x10000, 0x800000, 0x200000
BUTTON, EDIT, STATIC = 0x80, 0x81, 0x82
PROGRESS_BAR = "msctls_progress32"
ES_MULTILINE, ES_READONLY, ES_AUTOVSCROLL, BS_DEFPUSHBUTTON, PBS_SMOOTH = 0x4, 0x800, 0x40, 0x1, 0x1
IDOK, IDCANCEL, IDYES = 1, 2, 6
WM_SETFONT, WM_INITDIALOG, WM_COMMAND, WM_TIMER = 0x30, 0x110, 0x111, 0x113
PBM_SETPOS, PBM_SETRANGE32 = 0x402, 0x406
MB_YESNO, MB_ICONQUESTION, MB_ICONINFORMATION = 0x4, 0x20, 0x40

DLGPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
user32.DialogBoxIndirectParamW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, wintypes.HWND, DLGPROC, wintypes.LPARAM]
user32.DialogBoxIndirectParamW.restype = ctypes.c_ssize_t
user32.EndDialog.argtypes = [wintypes.HWND, ctypes.c_ssize_t]
user32.GetDlgItem.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetDlgItem.restype = wintypes.HWND
user32.SetDlgItemTextW.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LPCWSTR]
user32.SetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.SendMessageW.restype = wintypes.LPARAM
user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
user32.EnableWindow.argtypes = [wintypes.HWND, wintypes.BOOL]
user32.MessageBoxW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT]
user32.MessageBeep.argtypes = [wintypes.UINT]
gdi32.CreateFontW.restype = wintypes.HFONT
# Without these, ctypes passes a handle as a 32-bit int: a font handle with its top bit
# set ended a finished install with "int too long to convert" (a player, 2026-10-12).
gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
user32.GetDpiForWindow.argtypes = [wintypes.HWND]


def text(s):
    return (s + "\0").encode("utf-16-le")


def control(kind, style, x, y, w, h, ident, label=""):
    """One control. kind: a number for Windows' built-in kinds (BUTTON, EDIT, STATIC), or
    a class name such as PROGRESS_BAR. Positions are dialog units (about 1/4 of a
    letter's width and 1/8 of its height), so the layout scales with the font."""
    kind_bytes = struct.pack("<HH", 0xFFFF, kind) if isinstance(kind, int) else text(kind)
    return (struct.pack("<IIhhhhH", style | WS_CHILD | WS_VISIBLE, 0, x, y, w, h, ident)
            + kind_bytes + text(label) + b"\0\0")


def template(title, width, height, controls):
    # Window: font set, modal frame, centred, brought to the front; popup with a title bar
    # and a system menu (so Alt+F4 and the close button work).
    style = 0x40 | 0x80 | 0x800 | 0x200 | 0x80000000 | 0xC00000 | 0x80000
    data = (struct.pack("<IIHhhhh", style, 0x8, len(controls), 0, 0, width, height) + b"\0\0\0\0"
            + text(title) + struct.pack("<H", 9) + text("Segoe UI"))
    for item in controls:
        data += b"\0" * (-len(data) % 4) + item      # each control starts on a 4-byte line
    return ctypes.create_string_buffer(data)


def show(tmpl, handle):
    """Run a dialog until something calls EndDialog; its result. handle(window, message,
    wparam, lparam) is called for every message, like a tkinter event handler."""
    proc = DLGPROC(handle)          # keep a reference: Windows calls it until the end
    return user32.DialogBoxIndirectParamW(None, tmpl, None, proc, 0)


def alert():
    """The player's own Windows "Asterisk" sound (Sound settings), the information sound."""
    user32.MessageBeep(MB_ICONINFORMATION)


def ask_update(version, notes, have):
    """The "update found" dialog: the new version, what the player has (have: "You have
    0.1.2." or "This setup is 0.1.2."), what's new in a read-only multi-line box (focus
    starts there, so a screen reader can arrow through it), and Update and Skip buttons.
    Enter = Update, Escape = Skip. True to update."""
    ID_UPDATE, ID_SKIP, ID_NOTES = IDOK, IDCANCEL, 100
    heading = f"MB Access {version} is available. {have} What's new:"
    tmpl = template("MB Access update", 300, 177, [
        control(STATIC, 0, 7, 7, 286, 10, 101, heading),
        control(EDIT, ES_MULTILINE | ES_READONLY | ES_AUTOVSCROLL | WS_VSCROLL | WS_BORDER | WS_TABSTOP,
                7, 20, 286, 130, ID_NOTES),
        control(BUTTON, BS_DEFPUSHBUTTON | WS_TABSTOP, 180, 156, 54, 14, ID_UPDATE, "&Update"),
        control(BUTTON, WS_TABSTOP, 239, 156, 54, 14, ID_SKIP, "&Skip"),
    ])
    body = "\r\n".join((notes or "No notes were written for this version.").splitlines())

    def handle(window, what, wparam, lparam):
        if what == WM_INITDIALOG:
            user32.SetDlgItemTextW(window, ID_NOTES, body)
            return 1                        # let Windows focus the first control: the notes
        if what == WM_COMMAND and wparam & 0xFFFF in (ID_UPDATE, ID_SKIP):
            user32.EndDialog(window, wparam & 0xFFFF)
            return 1
        return 0

    return show(tmpl, handle) == ID_UPDATE


class Cancelled(Exception):
    """The player pressed Cancel and confirmed it."""


ID_HEADING, ID_STATUS, ID_BAR = 101, 102, 103
STEPS = 1000        # the bar's range: 1000 steps, smoother than 100


class Progress:
    """A window with a heading, a status line, a progress bar and Cancel, shown while
    job(progress) runs in a background thread (the window must keep answering Windows,
    or it freezes). The job reports with progress.update(fraction, status), calls
    progress.check() between steps (it pauses while "Stop?" is being asked and raises
    Cancelled once Cancel is confirmed) and progress.finishing(status) before a last step
    that mustn't be interrupted: Cancel is greyed out from then on.

    The percentage is also in the window title, so NVDA+T reads it at any time, and NVDA
    beeps as the bar fills. silent=True runs the job here and prints instead (testing)."""

    def __init__(self, title, heading, stop_question, silent=False):
        self.title, self.heading, self.stop_question, self.silent = title, heading, stop_question, silent
        self.fraction, self.status = 0.0, ""
        self.cancellable, self.cancelled, self.asking, self.done = True, False, False, False
        self.result = self.error = None
        self._go = threading.Event()
        self._go.set()                  # set = carry on; cleared while asking "Stop?"
        self._started = time.monotonic()
        self._shown = (None, None, None)     # what the window shows now: skip unchanged redraws
        self._fonts = []

    # --- called by the job (worker thread) -----------------------------------------
    def update(self, fraction=None, status=None):
        if fraction is not None:
            self.fraction = min(max(fraction, 0.0), 1.0)
        if status is not None:
            if self.silent and status != self.status:
                print(status)
            self.status = status

    def check(self):
        self._go.wait()
        if self.cancelled:
            raise Cancelled()

    def finishing(self, status):
        self.check()
        self.cancellable = False
        self.update(None, status)

    # --- the window (main thread) --------------------------------------------------
    def run(self, job):
        """Show the window, run the job, close the window; the job's result. Raises
        Cancelled, or the job's own error."""
        if self.silent:
            return job(self)

        def work():
            try:
                self.result = job(self)
            except BaseException as e:      # handed over to the main thread below
                self.error = e
            self.done = True

        self._thread = threading.Thread(target=work, daemon=True)
        show(self._template(), self._handle)
        for font in self._fonts:
            gdi32.DeleteObject(font)
        if self.error is not None:
            raise self.error
        return self.result

    def _template(self):
        return template(self.title, 260, 80, [
            control(STATIC, 0, 10, 8, 240, 12, ID_HEADING, self.heading),
            control(STATIC, 0, 10, 24, 240, 10, ID_STATUS, "Starting"),
            control(PROGRESS_BAR, PBS_SMOOTH, 10, 38, 240, 11, ID_BAR),
            control(BUTTON, BS_DEFPUSHBUTTON | WS_TABSTOP, 200, 58, 50, 14, IDCANCEL, "Cancel"),
        ])

    def _font(self, window, points, weight):
        """Segoe UI at this size and weight, scaled for the screen's DPI (150% etc.)."""
        dpi = user32.GetDpiForWindow(window) or 96
        font = gdi32.CreateFontW(-round(points * dpi / 72), 0, 0, 0, weight, 0, 0, 0, 1, 0, 0, 5, 0, "Segoe UI")
        self._fonts.append(font)
        return font

    def _handle(self, window, what, wparam, lparam):
        if what == WM_INITDIALOG:
            heading = user32.GetDlgItem(window, ID_HEADING)
            user32.SendMessageW(heading, WM_SETFONT, self._font(window, 12, 600), 0)     # bold, larger
            user32.SendMessageW(user32.GetDlgItem(window, ID_BAR), PBM_SETRANGE32, 0, STEPS)
            user32.SetTimer(window, 1, 100, None)       # redraw ten times a second
            self._thread.start()
            return 1                    # Windows focuses the first tab stop: Cancel
        if what == WM_TIMER:
            self._refresh(window)
            return 1
        if what == WM_COMMAND and wparam & 0xFFFF == IDCANCEL:     # Cancel, Escape, Alt+F4
            self._ask_stop(window)
            return 1
        return 0

    def _ask_stop(self, window):
        if not self.cancellable or self.asking or self.cancelled:
            return
        self.asking = True
        self._go.clear()                # the job waits at its next check()
        answer = user32.MessageBoxW(window, self.stop_question, self.title, MB_YESNO | MB_ICONQUESTION)
        self.asking = False
        if answer == IDYES:
            self.cancelled = True
            self.update(None, "Cancelling")
        self._go.set()

    def _refresh(self, window):
        if self.asking:
            return
        if self.done:
            user32.KillTimer(window, 1)
            user32.EndDialog(window, 0)
            return
        percent = int(self.fraction * 100)
        status = self.status + self._time_left()
        shown = (percent, status, self.cancellable)
        if shown == self._shown:
            return
        old_percent, old_status, old_cancellable = self._shown
        self._shown = shown
        user32.SendMessageW(user32.GetDlgItem(window, ID_BAR), PBM_SETPOS, int(self.fraction * STEPS), 0)
        if status != old_status:
            user32.SetDlgItemTextW(window, ID_STATUS, status)
        if percent != old_percent:
            user32.SetWindowTextW(window, f"{percent}% - {self.title}")
        if not self.cancellable and old_cancellable is not False:
            user32.EnableWindow(user32.GetDlgItem(window, IDCANCEL), False)

    def _time_left(self):
        """", about 8 seconds left" once there's enough to go on, else ""."""
        elapsed = time.monotonic() - self._started
        if self.cancelled or not self.cancellable or elapsed < 1.5 or not 0.03 < self.fraction < 1:
            return ""
        left = elapsed * (1 - self.fraction) / self.fraction
        if left < 3:
            return ""
        if left < 60:
            return f", about {int(left / 5 + 1) * 5} seconds left"     # in steps of 5: calmer
        return f", about {round(left / 60)} minute{'s' if round(left / 60) != 1 else ''} left"
