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
- NEXT (not verified): reference/wse/WarbandLib/item.h + troop.h + inventory_window.h. A troop
  has inventory.slots[96] (item_no, flags; equipment first: slots 0-3 weapons, 4 head, 5 body,
  6 feet, 7 hands, 8 horse, 9 food?) and the inventory window has inventory_slot_widgets[2*96]
  and equipment_slot_widgets[2*10] linking each cell widget to its slot. That would name a
  cell's item instantly, with no hover or tooltip wait (empty cells cost 0.4 s now).
- Tested live 2026-10-06 with real keys: grid arrows, Tab order (Details, Discard, Equipment,
  Inventory), Tab hidden from the game. Headings above grids (Discard, Outfit, Arms, the player's
  name) were becoming one-item sections: now they name their grid (HEADING_GAP 0.15) and
  everything else is one "Details" list (cost, armor, encumbrance, Return, money). Tooltip
  "(29 / 29)" = ammo left or shield durability; the user wants it left as the game writes it.
