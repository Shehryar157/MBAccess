## Auto-start loader (2026-10-05, installed; first real launch NOT yet tested)

- loader/dinput8.c (copied from CFCAccess, names changed) built 32-bit: zig cc -target x86-windows-gnu. In 32-bit the .def must name the stdcall-decorated functions (Proxy_DirectInput8Create@20, DllGetClassObject@12, the others @0). Verified with pefile: machine 0x14c, 6 plain export names.
- python tools/build_loader.py install|uninstall finds both games through Steam's libraryfolders.vdf and writes <game>\MBAccess.txt (pythonw run.py --with-game). It writes <game>\MBAccess_loader.log; the mod logs to logs\mbaccess.log. Mutex: MBAccess.SingleInstance.
- PowerShell 5 Set-Content -Encoding utf8 adds a BOM; strip it (Python copes, other tools may not).
