## Conversations and the skills list (Warband 1.174, VERIFIED 2026-10-06)

- The conversation screen is game_windows[12] (gwt_conversation).
- Engine data object (game_data.h, held for 1.174): conversation manager (319676 bytes), one int
  of padding, then skills[42]. The conversation manager is at a FIXED address, **0x2d55320**
  (inside the exe's .data), so no search is needed at runtime; skills follow at 0x2da33e0.
- Conversation manager fields, all verified in the merchant intro: num_sentences +0 (Native
  2773), sentences* +4 (sentence 0 id "dlga_start:close_window"), active token +8, partner
  troop +12 (920 = the merchant), cur_sentence_no **+28**, num_options **+36** (0 while the game
  says "Press left mouse button to continue..."), speaker options at +40 (156 bytes each:
  sentence_no, repeat_object, flags, text), partner options after, then **speaker_text at
  +319532**: the line on screen, whoever says it (the player's own lines too).
- Window 12 widgets (pointers in the window object): +0x288 speaker name label ("Merchant of
  Tulga:", or the player's name when they speak), +0x290 the "Press left mouse button to
  continue..." label (flag 0x1 while there are replies), **+0x2a4 reply button table**: live
  buttons have flag 0x1 clear and are in option order; spares say "hello" and are hidden. First
  reply at (0.020, 0.239), then 0.041 lower each. Buttons span the width; clicking at
  (x+0.45, y+0.02) works with a quick click.
- Not verified: scrolling when there are more replies than fit (choices_s area, about y 0.01 to
  0.28; profile "scroll"), and whether +0x2a4 stays right for every conversation.
- Skills in memory (verified): 42 entries of 452 bytes (description, name, id rgl::strings, then
  u1, max_level, u2, u3, flags). Names already translated. Flags: 0x100 = reserved/hidden,
  0x2 bit = party skill? (Trade 0x13, Leadership 0x3, Engineer 0x12), check against skills.txt.
- Finding them file-free (tools/probe_conv.py): search for "skl_", walk back to skill 0, step
  back 4 + 319676 bytes.
- Reaching a conversation: in the merchant's house the merchant waits for F. Turning with
  relative mouse_event moves (about 1 pixel of screen per unit) and walking with W worked in 4
  short bursts. The street scene timer ($merchant_sign_count) is a different scene.
- Goal (the user asked 2026-10-06): depend less on game text files. Skills (skills.txt/.csv)
  and the menus.txt fallback can move to memory; the mod's own JSON files stay.
