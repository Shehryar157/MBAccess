## Installer (2026-10-10, session 22; release v0.1.0 on the private repo)

- python tools/build_release.py -> dist/MBAccess-Setup.exe (20.5 MB; the one release asset,
  always that name). PyInstaller: run.py -> onedir MBAccess.exe, zipped (LZMA) as the
  installer's payload; installer/setup.py -> onefile, --uac-admin. Size is Python + numpy
  (OpenBLAS alone is 20 MB unpacked; walls.py needs numpy); ssl, tkinter etc. are excluded
  and the installer downloads with urlmon (URLDownloadToFileW), not Python's ssl.
- Installs to <game>\MBAccess, moves dinput8.dll beside the game, writes MBAccess.txt =
  "<game>\MBAccess\MBAccess.exe" --with-game. Keeps settings.json, learned.json, logs.
  First install only: copies installer/controls.dat (the user's key layout, 420 bytes) to
  %APPDATA%\Mount&Blade Warband\controls.dat, old one kept as controls.dat.before-mbaccess
  (uninstall restores it). Warband only for now.
- Update check on every run: GitHub releases/latest of Shehryar157/MBAccess, tag v<VERSION>
  newer than mbaccess.VERSION -> downloads that MBAccess-Setup.exe and starts it with
  --no-update. While the repo is PRIVATE the check gets 404 and is skipped silently.
- mbaccess/paths.py: DATA (packed files: profiles, message_categories.json) vs USER
  (settings, learned.json, logs: beside MBAccess.exe). multiprocessing.freeze_support() in
  run.py for the key-hook child.
- Tested: install / update / uninstall into pretend folders (--game, --keys, --silent); the
  packed MBAccess.exe starts and waits. NOT tested: the packed mod in a real game session
  (sound DLL, key hook child), the real elevated exe, a real update hand-over.
- On this dev PC the game still starts the source copy (MBAccess.txt -> pythonw run.py).
  Running the installer here switches it to the installed copy; tools/build_loader.py
  install switches back.

## Auto-start loader (2026-10-05, installed; first real launch NOT yet tested)

- loader/dinput8.c (copied from CFCAccess, names changed) built 32-bit: zig cc -target x86-windows-gnu. In 32-bit the .def must name the stdcall-decorated functions (Proxy_DirectInput8Create@20, DllGetClassObject@12, the others @0). Verified with pefile: machine 0x14c, 6 plain export names.
- python tools/build_loader.py install|uninstall finds both games through Steam's libraryfolders.vdf and writes <game>\MBAccess.txt (pythonw run.py --with-game). It writes <game>\MBAccess_loader.log; the mod logs to logs\mbaccess.log. Mutex: MBAccess.SingleInstance.
- PowerShell 5 Set-Content -Encoding utf8 adds a BOM; strip it (Python copes, other tools may not).

- Update dialog (same day): when a newer release exists, ask_update() shows a Win32 dialog built from an in-memory template (ctypes, DialogBoxIndirectParamW): heading with both versions, read-only multi-line edit with the release's description (focus starts there), Update (Enter) and Skip (Escape = install the carried version). Verified by reading the controls and posting both buttons; a real update hand-over is still untested (private repo). The v0.1.0 asset was replaced with this build.

## Installer 0.1.1-0.1.2 (2026-10-11, session 22; tested silently + hidden window, NOT yet run by the user)
- The repo answers unauthenticated now: the silent test fetched releases/latest (200) and found the update.
- 0.1.1: Browse for folder crashed (BROWSEINFO.pszDisplayName declared LPWSTR = c_wchar_p, which only takes a str; now POINTER(c_wchar)).
- 0.1.2: installer/ui.py = dialog templates, the update dialog (moved here), Progress window (bar 0-1000, status + time left, % in the title for NVDA+T, Cancel asks first; the job runs in a thread, a 100 ms timer redraws). Unpacks into <game>\MBAccess.new, then swaps (Cancel greyed out only for the swap). Downloads via WinINet in 64 KB pieces. Ends with MessageBeep(asterisk) + "Done. Updated MB Access from X to Y."
- <game>\MBAccess\version.txt records the installed version. The update check compares GitHub with max(installed, setup's own); an older setup over a newer install asks first (No is default); the same version asks to reinstall. 0.1.0/0.1.1 installs have no version.txt ("Updated MB Access to 0.1.2").
- Hidden window test: CreateDialogIndirectParamW with the same template (no WS_VISIBLE) + a PeekMessage loop; reads title, status and bar back.
- Release builds take ~4-8 min: start tools/build_release.py detached (Start-Process, logs in %TEMP%) and poll dist\MBAccess-Setup.exe's time.
- Desktop Commander (a local MCP server) gives a cloud chat PowerShell on the laptop; bridge calls over ~60 s time out but keep running.
- 0.1.4 (2026-10-12): a player's 0.1.3 update ended with "Setup failed: ArgumentError('argument 1:
  OverflowError: int too long to convert')" after choosing the folder. Cause: gdi32.DeleteObject
  had no argtypes, and Progress.run() deletes its fonts AFTER the dialog closes. CreateFontW's
  restype is a pointer, so a font handle with its top bit set comes back as a huge number that
  ctypes won't pass as a plain int. Luck of the handle value, so it never showed here. Fixed:
  argtypes for DeleteObject and GetDpiForWindow. RULE: every Windows call that takes a handle
  gets argtypes. If it happened in the install window, the files were already in place (only
  the Done message was lost); in the download window, nothing was installed. The bug is in the
  RUNNING setup, so an old setup's self-update can fail the same way: download the new one.
