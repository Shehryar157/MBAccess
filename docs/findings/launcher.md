## Launcher (both games, verified 2026-10-05)

- WFS launcher: #32770 'Mount&Blade With Fire and Sword', same control IDs as Warband except no 1202 (delete module). It can take 30+ s to appear on first start.
- The module combo box has no window text; read it with CB_GETCURSEL + CB_GETLBTEXT. WFS's combo showed 'Native' although the only module folder is 'Ogniem i Mieczem' (check this).
- GetGUIThreadInfo(launcher thread).hwndFocus gives the focused control without needing foreground; WM_NEXTDLGCTL (0x28) moves focus like Tab.
- mbaccess/launcher.py speaks the labels (run.py polls it). The user wants the launcher kept, just made accessible: no auto-skip.
