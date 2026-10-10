## Widget tree and form screens (Warband 1.174, VERIFIED 2026-10-05)

- Every window's root widget is at **window+0x13c**. A container widget has its name (rgl::string) at **+0x2d0** and an stl::vector of child pointers (start, end, capacity) at **+0x364**. Treat an object as a container only when the name is non-empty: plain labels can have junk that looks like a vector there.
- Widget class = the vtable (first dword). Classes: 0x7c4bac label; 0x812904 button; 0x81bac4 tab; 0x819b7c checkbox; 0x8144ec spinner (looks like a drop-down: left/right arrow images + a label child holding the value); 0x812ae4 slider; 0x7c4d04 image (with text = a key-binding button on Controls); 0x8134ac a real drop-down (e.g. "Use Desktop Resolution", "Melee only"; read as a label for now, opening it not tried); 0x81b9bc tab bar; 0x8135c4 screen root; 0x81cfcc scroll area ("..._vs"), 0x7c510c its scrolling content ("..._t_c").
- Checkbox: **+0x2b0** = 1 when ticked; its label is a label child. Slider: **+0x2bc** float 0-1 (battle size 0.342 = 71 on 30-150). Hover highlight byte = widget+0x1f2.
- Clicks (tested reversibly): checkbox click at (x+0.05, y+0.01) toggles; spinner arrows at (arrow_x+0.01, y+0.015) step the value; slider ignores clicks on its track: DRAG the handle from x+f*0.205 (track width about 0.205) while holding the button.
- Scrolling: one wheel notch over the list moves it 0.062, and the positions in memory update (smooth animation: for a moment a label and its control can sit on different rows). Visible list area: from the "_vs" widget's y (0.05) to about 0.64.
- Windows: 13 = Options (General), 14 = Video options, 15 = Controls. Each tab is its own window. Controls: two-column key list (x 0.23 and 0.58), keys are image widgets with text; Map Controls keys are plain text (not rebindable).
- Code: mbaccess/form.py (TreeReader + rows pairing); a window with "tree": true in the profile uses it. Screen identity = sorted widget addresses (stable while a screen is open). Tools: tools/probe_tree.py <window>, tools/probe_widgets.py <window>.

## More screens (Warband 1.174, VERIFIED 2026-10-05)

- Screen numbers: 0 = tutorial message box, 1 = question box (save policy), 3 = loading screen (hint + progress), 11 = Character, 16 = Load game, 29 = Custom battle. Unlisted windows now default to the tree reader.
- Root widget isn't always at +0x13c (Load game: +0xbf0). Search the window for a pointer to an object of class 0x8135c4 (root).
- Flags bit 0x2 = disabled (greyed out), e.g. Load/Delete with no saves, Done on Character before a name.
- Slider: +0x2bc value, +0x2c0 minimum, +0x2c4 maximum (Options 0-1, Custom battle 0-100 and 1-75).
- Clicks: script-built screens (Custom battle) ignore a fast click; hover 0.1 s and hold 0.08 s. But game menus act on button DOWN and show the next menu at once, so a held click also presses the next menu's option under the mouse: menus need the fast click (hold 0.03). Buttons (0x812904) react from x+0 to x+0.14, y+0.01 to y+0.03.
- Custom battle: headings ("Faction", "Army Size") sit about 0.3 left of the control below them (centred text?); the army-mix sliders are labelled by unreadable icons (class 0x812d6c; Infantry, Archers, Cavalry top to bottom). Handled by the profile "layout" (names, heading_offset, sides).
- Character screen: skill names, attributes, proficiencies and "+" are image widgets with text; "+" sits right of its item on the same row (hidden when maxed). Name box = class 0x7c4eec (edit): click it, then key presses go to the game; its text is at the usual +0x1f8. Skill description container "characterskill_desc" shows the hovered skill's text (not spoken yet). "Reset Changes" button appears after spending a point.

## Drop-downs, Esc menu, party screen (Warband 1.174, VERIFIED 2026-10-05, session 4)

- Drop-down (class 0x8134ac): choices = stl::vector of rgl::strings (0x90 bytes each) at **+0x2e8** (start, end, cap); chosen index **+0x2b0**; row height of the open list **+0x320** (0.029); its own text (+0x1f8) is the current choice. Options has 1 (Turn Camera with Horse: Never, Ranged only, Melee only, Always), Video has 4 (Screen Resolution 18 choices, Number of Corpses, Number of Rag Dolls, Overall Quality).
- Clicking the box opens a list that hangs BELOW the box with the LAST choice at the top: choice i's row centre = box_y - (count - 1 - i + 0.5) * row. Verified by screenshot (1920x1080 at y 0.067). Near the screen's bottom the list runs off-screen (Never was unclickable), so scroll the page first. Tested: Left/Right through all 4 camera choices, Corpses 20 -> 40 -> 20.
- Widget size (width, height floats) at **+0x1ac**, next to absolute position +0x19c. Esc-menu buttons are 0.25 wide with centred text and only react near the text: click the size's middle.
- Window 5 = Esc (pause) menu: Return to Game, Options, Save & Exit, Save, Save As, Quit without Saving (image widgets with text). The Save buttons don't highlight inside the start scene.
- Window 8 = party screen. Three panels: columns at x 0.34 and 0.66 (profile layout). Troop entries are image widgets with text "name (90%)" inside party_members0_0. The left "party skills" lines (Surgery (1), Path-finding (2)(+1)...) are NOT anywhere in memory as text (searched ASCII and UTF-16): the engine draws them and drops the string. Rebuilt from troop skills: see "Party skills rebuilt" below.
- Window 10 = scene/battle HUD (tactical). Window 31 = face editor: see "Face editor" below.
- Character creation: Done stays disabled until all attribute AND skill points are spent (a name alone isn't enough). Worth saying why when it's unavailable.
- tools/find_text.py "text": Ctrl+F over the game's memory (ASCII + UTF-16). tools/shot.py: screenshot. tools/drive.py "item" key count: press any key on an item.
- The auto-started mod (pythonw run.py --with-game) runs alongside test tools; it only reacts to real key presses while the game is in front.

## Party skills rebuilt (Warband 1.174, VERIFIED 2026-10-05, session 7)

- Troops array: pointer at **game+0x140f0**, count at +0x140f4 (1072 in Native). Troop size **0xfc8**. Fields are 4 bytes later than WarbandLib 1.153: flags (u64) **+0x248** (0x10 = hero), attributes[4] +0x270, skills **+0x280** (6 ints, 4 bits a skill, 8 skills an int; skill numbers as in skills.txt), proficiencies (floats) +0x298. Name rgl::string +0x4, id ("trp_player") +0x1b4. Found by scanning the game object for a pointer+count whose target has id "trp_player"; the game object is readable only to about +0x21000.
- Parties: stl::vector of party pointers at **game+0x140b8** (only 29 items in a new game, NOT in id order: p_main_party, p_collective_ally, p_town_12...; so look p_main_party up by id). Party id rgl::string **+0xa0**; troop stacks: pointer at **+0x244** (capacity 32), used count **+0x250**; stack = 32 bytes (count, troop_no, flags, spawned, wounded, upgradeable, xp float, ?). Found with tools/find_text.py "p_main_party" then a full-memory search for pointers to just before it.
- Rule used: party skill = best level among heroes in the party (wounded count: the knocked-out player's Path-finding still showed); leader bonus +1 at 2-4, +2 at 5-7, +3 at 8-9, +4 at 10 (only 1 -> 0 and 2 -> +1 VERIFIED; the rest is the commonly cited rule). Native's script game_get_skill_modifier_for_troop adds +1 for reference books (Wound Treatment, Trainer, Surgery), NOT included yet. Checked live: Surgery 1, Wound Treatment 1, Path-finding 2 +1, as the screen shows.
- Code: mbaccess/party_skills.py, profile screen["party_skills"] offsets, window 8 "party_skills": true puts the lines after the "Party Skills" heading. Names from Modules/<module>/skills.txt (flag 0x10 = party skill). tools/probe_troops.py [troop_no...] prints a troop's attributes and skills.
- To verify later with companions: does the bonus come from the leader's own level when a companion is best? Do wounded companions count?

## Load game save tiles (session 11, 2026-10-07)

- With a save present, Load game (16) shows each save as a tile (top-left first: character name, then 'Day 1 (6:00)'). The tree reader does NOT read the tiles: only Delete, Cancel, Load (the last two 'unavailable' until a tile is clicked). A held click at the tile (x 0.18, y 0.615 for the first) selects it; then Load works. TODO: find the tile widget class (probe_tree on window 16 with a save present) and read tiles as items.

## Load game save tiles: DONE (session 13, 2026-10-07; VERIFIED live with one save)

- The save records live INSIDE the window 16 object (that's why its root is at +0xbf0, not
  +0x13c): 9 records from window+0x13c, stride 0x130. Record: +0 character name (rgl::string),
  +0x90 day ("Day 4 (7:10)"), +0x120 has-a-save flag (1) then the game version (1174).
  Found with find_text.py "Day 4 (7:10)", then reading every rgl::string in the window.
- Selected save: window+0xc28 (-1 = none, else the record number; with one save, record and
  tile numbers can't be told apart: UNVERIFIED with several saves). Delete and Load lose their
  disabled flag when a save is selected.
- Tiles: textless image widgets, direct children of the root, 0.31 x 0.2 (size +0x1ac); first at
  (0.015, 0.51). menu_watch.save_tiles pairs records holding a save with tiles, top-left first
  (UNVERIFIED order with several saves); if the counts differ it says "Save 1..n" (self-check).
  Items: "Shehryar, Day 4 (7:10), selected, button"; Enter = held click on the tile's middle,
  "selected" is spoken as a value change. Load via the mod verified. Delete NOT tested (only
  one save): it should ask a question box (window 1).
- Profile window 16 "saves": first, stride, count, day, exists, selected (hard-coded offsets,
  checked by the flag and the tile count).

## Notes screen (window 21) (2026-10-10, session 19; read live, clicking topics UNTESTED)
- Root "notes". Tabs along the bottom are image buttons (Game Log, Recent Messages, Notes,
  Game Concepts, Characters, Locations, Factions, Return); Back/Forward/Show On Map at y 0.70.
  Labels: page title (0.74, 0.71, "Game Concepts") and entry heading (0.03, 0.67, "Morale").
- Class **0x819984 = multi-line text box** (profile kind "textbox"). Topic list = one box in
  notes_key_collection(_s): text '<ip=4>Character Backgrounds</>\n...' (link tag per line; the
  current entry has none). Article = one box in notes_data_collection(_s), paragraphs split by
  "\n\n". Line height = box height / lines (0.109/6 = 0.018). Box +0x2e4 vector = per link
  (width, top y relative), +0x304 ints = link ids in order: not used, kept as backup.
- form.textbox(): link lines = buttons (click 0.02 in, middle of the line), other lines
  "X, current"; paragraphs spread down the box. Layout "by_group" = Tab sections Buttons /
  Topics / Page; opens on Page. Box text is hashed into the screen key, so a new page re-announces.
- Tool: tools/probe_textbox.py <window> dumps these boxes.
- LINKS (2026-10-10, verified read-only on the Khergit Khanate page): text box +0x2d4 = vector of
  lower-left corners (x, y floats, 16-byte entries), +0x2e4 = upper-right corners, +0x314 = ints,
  which link (0.. in text order) each piece belongs to (a wrapped name has 2 pieces), +0x304 =
  link target id (trp/p/fac number), +0x2f4 = link type. All relative to the box position.
  form.link_boxes(); articles give "Name, link" items after their line; rows() keeps a box's
  own order (Item.order). Clicking a link through the mod UNTESTED.
- Character screen (11): profile "skill_info" speaks modfiles Skill.description after a skill.
- NVDA key (Insert/Caps Lock) held: keys hook passes everything through (keys.NVDA_KEYS).
- Party screen (8), 2026-10-10 verified read-only with a Rhodok Tribesman selected: party_info panel
  holds troop name label, Move Up/Down, "Class of troop" + class button, "Upgrade to X (10d)" image
  buttons (one per upgrade path; flags 0x2 = disabled until the troop has the XP, 0x3 = hidden),
  wage/morale label, Talk, Disband (reads "Release one" while hidden). Columns named in the profile.

## Face editor (window 31) (2026-10-10, session 20; read live, picker clicks UNTESTED)
- Root "face_gen". Right: scroll area face_gen_deform_s with 27 label + slider rows (Face Width
  top .. Chin Size bottom; y grows UPWARD, so the stored order is reversed; rows() already
  sorts it right). Left (face_gen_buttons): Age and Hair Color sliders; Randomize, Reset, Done
  (image buttons with text).
- Skin / Beard / Hair = a label with TWO textless image buttons just under it (previous /
  next style), all three labels on one row: that's why they read "Skin Beard" + "Hair". The
  game shows no style name or number. form.TreeReader.pickers(): a label with one blank image
  under-left and one under-right (within PICKER_GAP / PICKER_REACH) becomes a spinner item;
  Left/Right click the arrow's middle (Item.arrow_click).
- Skill descriptions: Prisoner Management's "%d" is filled from scripts.txt
  game_get_party_prisoner_limit's store_mul number (Native 5; modfiles.fill_skill_numbers).
- Face words (mbaccess/face.py, profile window 31 "face": true): sliders read "Nose Size,
  large, 73%" (5 bands); a "Portrait" item first (age + man/woman from troop 0 flags & 0xf,
  hair shade, up to 6 features furthest from average, face order); read again after
  Randomize/Reset. skins.txt: the Skin picker steps through 8 face textures, each with its own
  hair colour list (ARGB, light -> dark: Hair Color slider left = light). Slider direction for
  the shape keys (left = less) is ASSUMED: some skins.txt key ranges run backwards; check by
  screenshot.
- PICKER VALUES (2026-10-10, VERIFIED live: Beard Right 18 -> 19 of 23 and back): the face_gen
  window keeps beard_no, hair_no, (hair texture: junk 20091 in 1.174), face_texture_no, age
  float, hair colour float right after its Done, Reset, Randomize button pointers (WarbandLib
  face_gen_window.h order; here at window+0x448). MenuWatcher.face_styles finds the 3 pointers
  in a row (no fixed offset) and trusts the numbers only if age and hair colour match the
  sliders. Counts from skins.txt (modfiles.parse_skins: man 20 hairs, 23 beards, 8 faces;
  woman 7, 0, 5); skin tone word from the face texture's colour brightness (face.tone).
- Slider direction: Nose Size 12% -> 100% made the nose visibly longer (screenshot, head
  moving, so weak evidence): right = more, as assumed. Others still unchecked.
