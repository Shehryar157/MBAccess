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
