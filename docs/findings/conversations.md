## Conversations (Warband 1.174, NOT verified yet; written 2026-10-05 in a cloud session without the game)

- Window 12 = conversation (gwt_conversation in WSE game_window.h; numbers 4, 7, 8, 11, 13-18 and 29 already matched that enum).
- Data from the engine, not the widgets: wb::conversation_manager (WSE conversation.h) sits inside the global game_data, in the exe's .data, right before `int u15; skill skills[42]`. game_data is pack(4). Layout relative to `speaker_text` (the line said to you, an rgl::string):
  - in_meta_mission -4 (bool padded to 4)
  - partner_options[1024] -4 - 1024*156; speaker_options[1024] before that (option = sentence_no, repeat_object, flags, rgl::string text = 156 bytes)
  - num_options just before speaker_options; partner troop number 24 bytes before num_options.
- Anchor: skills[0] = description, name, id rgl::strings; its id is the module's first skill ("skl_trade" in Native). speaker_text = skills[0] - 4 - 0x90. mbaccess/conversation.py find() searches .data (0x85e000-0x2db4000) for it.
- The 1.174 WSE port (kumpuu/WSE) has the identical conversation_manager and the same fields around it. Still unknown: whether that holds in the live game, and which option array holds the player's replies (speaker or partner). The code defaults to partner.
- Clicking a reply: walk window 12's tree for a widget whose text equals the reply (any class), click the middle of its size with the fast menu click. Not tested.
- To verify: start a conversation (e.g. a tavern keeper), then run `python tools/probe_conversation.py`. It prints both option arrays and the window's texts and picks the matching array; `--save` records {"speaker_text", "options"} in profiles/warband.json screen.conversation. Without it, run.py searches for the address itself each time a campaign starts and uses partner.
