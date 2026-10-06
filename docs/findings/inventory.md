## Inventory (Warband 1.174, VERIFIED 2026-10-05, session 4)

- Window 7 = inventory; its root is at +0xa7c (found by the root search). Cells are class **0x817964** ("slot"), 0.088 square (size at +0x1ac). Containers: "inv" = equipment (x 0.451: Head 0.605, Body 0.517, Feet 0.429; x 0.363: Hands 0.517, Horse 0.317; x 0.552: weapons 0.605 down to 0.341), "int" in "int_s" = the player's 3x10 grid (scrolls; int_s y 0.099 + height 0.598), "nt" in "nt_s" = the other side's 3x3 grid (Discard, or a merchant). A cell widget holds NO item number.
- **Tooltip**: one global, rgl::string lines 0x90 apart at **0x86d130** (exe .data, stable). All lines blank when nothing is hovered. It updates within a frame of the mouse moving, but: leaving an item blanks it for a frame first; it only updates on a real movement (nudge first if the mouse is already there); it doesn't show while the game window is in the background. Lines: name, (condition e.g. 29 / 29), Sell price, Weight, stats, requirements.
- **Moving items**: one click picks up, the next click puts down (a release at another cell after holding the button does NOT drop it). window+**0xbb0** = 1 while something is on the mouse, **+0xbb4** = its item kind number (-1 for none). A refused drop (fish on Head) leaves it held.
- **Item kinds**: global **0x8b8554** -> item 0's name (rgl::string at the record start), 0x8b8558 = count (620 in Native). Record size **0xc38**. 0 INVALID ITEM, 1 Spear, 82 Rhetorica ad Herennium, 110 Smoked Fish, 143 Saddle Horse, 555 Hunting Crossbow. Names are the base names (no "Swaybacked").
- Scroll boxes: any container named "*_s" or "*_vs" scrolls; visible range = its y to y + height (+0x1b0). Visibility is judged at the click spot, not the corner (a cell can poke in with its middle hidden).

## Item actions and F1 help (session 5, 2026-10-05, untested in game)

- Item actions, from ui.csv/hints.csv: left click picks up and puts down (equip, discard via the "Discard" 3x3 grid, loot, trade); Ctrl+click = quick buy/sell; right click = the item's ONE special action (books: read; livestock: "Slaughter this %s and eat it?"). Food and drink are never used by hand. Mod: Shift+Enter right-clicks a cell. Ctrl+click not mapped yet.
- F9 help (moved from F1, which is the battle order key) (mbaccess/help.py), like FFC's: groups by screen, starts on Inventory when the screen has slots. We can't hide keys from the game: Escape closes the help AND reaches the game. In battles F1 is the game's order key (conflict to solve later).

## Grid navigation and a faster way to name items (2026-10-06)

- Built (menu_watch sections, test_inventory_grid_arrows_and_sections): slot cells grouped by
  container are grids (arrows move by screen position, GRID_ROW 0.02); "columns" layouts make
  each column a section. Tab/Shift+Tab switch sections; the keyboard hook swallows Tab only
  while the screen has sections and never with Alt held. Not yet tried in the live game.
- DONE below ("Cells named from memory"): the WarbandLib idea that equipment is slots 0-9 of
  the bag turned out wrong; equipment is its own list.
- Tested live 2026-10-06 with real keys: grid arrows, Tab order (Details, Discard, Equipment,
  Inventory), Tab hidden from the game. Headings above grids (Discard, Outfit, Arms, the player's
  name) were becoming one-item sections: now they name their grid (HEADING_GAP 0.15) and
  everything else is one "Details" list (cost, armor, encumbrance, Return, money). Tooltip
  "(29 / 29)" = ammo left or shield durability; the user wants it left as the game writes it.

## Cells named from memory (VERIFIED live 2026-10-06, session 9)

- The inventory window (7) matches WarbandLib's inventory_window.h field for field (game_window
  ends at +0x13c). **+0x174** = inventory_slot_widgets[2 x 96]: cell widget pointers in slot
  order, side 0 (you) then side 1 (the other side: Discard / merchant / loot); unused entries
  hold junk. **+0xa80** = equipment_slot_widgets[2 x 10]: Weapon 1-4, Head, Body, Feet, Hands,
  Horse (no Food cell, entry 9 = 0); side 1's half is junk when it has no equipment.
  +0x774 inventory_prices (77777 = no price, outside trade). +0xbb0 dragging, +0xbb4 item kind,
  +0xbb8 its flags. Found by dumping the header offsets and matching against the tree's cells.
- Troop (stride 0xfc8, layout = 1.153): **+0x2d0 bag**, 96 x (item_no, flags); bag cell N =
  slot N (-1 = empty). **+0xf68 equipment**, 10 x (item_no, flags) in the order above + Food.
  Found: the player's fish showed in slot 7 = "Inventory 8" by a tooltip sweep; the equipment
  by searching the troop for the Hunting Crossbow's kind (555).
- Flags: top byte = item modifier (2 Rusty, 5 Battered, 0x16 Ragged, 0x18 Sturdy, 0x1f
  Swaybacked); low bits = hit points for shields/horses (169, 100).
- Modifier names: fixed table at **0x1d9ade8** (rgl::string "Rusty %s"), records **0x128**
  apart, index = modifier; referenced by exe code (0x47ec9c), so static. 0 = "Plain %s", which
  the game shows bare, so 0 adds nothing. Found with find_text "Swaybacked".
- Side 1's troop: game **+0x14370** = cur_screen_troop_no (right after cur_menu_no, as in
  game.h). -1 with the inventory opened by the player (Discard pile: owner unknown, the tooltip
  is used). NOT verified for merchants, loot or a companion's gear (should be that troop).
- Side 0 is assumed to be the player (troop 0). NOT verified when the game shows a companion.
- Speech (menu_watch.name_cell): the name is said at once from memory (1-17 ms measured over
  all 48 cells; empty cells were 400-650 ms before); with Item details Full / price, the
  tooltip is still hovered and its other lines follow queued (interrupt=False), only if its
  first line equals the name (a leftover tooltip is never read as this item). Details came
  30-80 ms later; once (a timing fluke) not within 0.8 s, then only the name is heard.
- Tool: tools/probe_inventory.py [troop_no] prints a troop's bag and the cell tables.

## Discard pile, Ctrl+Enter, trade prices, slow tooltips (2026-10-06, session 9, later)

- **Discard pile = the temp troop** (VERIFIED live): Ctrl+clicking the fish into Discard put
  (110, 0) at troop 1's bag slot 0 (found by snapshotting every "110, flags" in memory before
  and after: set difference). game **+0x6e4** = 1 = temp_troop_no (by game.h's order; the
  field before it is 0, the player). Used when the screen troop is -1. All three sides are
  now named from memory with the inventory opened by the player.
- **Ctrl+Enter = Ctrl+click** (VERIFIED live, bag -> Discard and back): the mod presses Ctrl
  itself (scan code 0x1D, DirectInput) around the click, so a quick tap of Ctrl+Enter works.
  The item moves to the other side's first free cell; the mod compares the cell before and
  after: "X moved", "X stayed" (refused), "nothing there". Trading/looting: untested.
- **Trade prices** (NOT verified, needs a merchant): with Item details "Name and price", a bag
  cell whose window price (+0x774, 2 x 96 ints) isn't 77777 is read as "name, price N, cell"
  with no tooltip. Whether it is the buy or the sell price is unknown; equipment prices
  (+0xb20) looked like junk, so they're unused.
- **Slow tooltips**: if the tooltip hasn't matched the name after 0.2 s, the mouse is nudged
  once more; details are given up after 1.2 s (the name was already spoken).
