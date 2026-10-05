## Game messages (Warband 1.174, VERIFIED live 2026-10-05, session 5)

- rgl::window_manager (WSE rgl_window_manager.h) holds `stl::vector<rgl::string> message_log`: EVERY message shown since the game started. It's at **0x87bda4** (exe .data, fixed; profile screen.message_log): start, end, max pointers, 0x90 per string. Found by scanning forward from the tooltip (tooltip_texts[0] = 0x86d130, same object) for a vector of readable strings.
- Just before it is `message_queue` at 0x87ab1c (size, head, texts[32], colors[32]): only holds messages while they're on screen (size 0 once faded), so the log is the source. The log has no colours, so categories come from keywords (mbaccess/message_categories.json).
- mbaccess/messages.py: speaks new messages with interrupt=False; buffers All + categories + Other; [ ] buffers, ; ' messages, Shift = oldest/newest. Ignored while the cursor is on an edit box.
- WFS: address not found yet (same method should work).
