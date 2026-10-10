# MB Access

Screen reader support for **Mount & Blade: Warband** (Steam, PC). It speaks the launcher, menus, conversations, inventory, the world map and game messages, and adds sounds and keys for walking around scenes and fighting, through NVDA, JAWS or another screen reader, or Windows' built-in voice if none is running.

The mod is in development. Menus and the campaign's everyday screens are solid; scenes and battles are playable but new. Read [What may not work correctly](#what-may-not-work-correctly) before a long campaign.

## Contents

- [Installing and updating](#installing-and-updating)
- [Before you play](#before-you-play)
- [Keys](#keys)
- [The scanner](#the-scanner)
- [Navigation on foot](#navigation-on-foot)
- [Navigation on horseback](#navigation-on-horseback)
- [The world map](#the-world-map)
- [Combat](#combat)
- [The mod's sounds](#the-mods-sounds)
- [What works](#what-works)
- [What may not work correctly](#what-may-not-work-correctly)
- [Known bugs](#known-bugs)
- [What does not work yet](#what-does-not-work-yet)
- [How it works](#how-it-works)
- [Building from source](#building-from-source)
- [Credits](#credits)

## Installing and updating

1. Download `MBAccess-Setup.exe` from the [Releases](../../releases) page.
2. Run it and wait. Windows asks once for permission to make changes.
3. The setup first checks for a newer version of itself and, if there is one, downloads and runs that instead, so an old download still installs the newest mod.
4. It finds Warband through Steam. If it can't, it asks you to choose the game's folder: the one that contains `mb_warband.exe`.
5. When it says the mod is installed, start Warband from Steam as usual. The mod starts and stops with the game: it reads the launcher, and says "MB Access" and its version once the game itself is open.

**To update**, run `MBAccess-Setup.exe` again. Your settings are kept.

**To uninstall**, run `Uninstall MB Access.exe` in the game's `MBAccess` folder.

**Requirements:** Windows 10 or 11 (64-bit) and the Steam version of Warband (1.174) with the Native module. A screen reader is optional. For now the installer covers Warband only; With Fire & Sword is planned.

### If the mod doesn't start

- Look in the game's folder for `MBAccess_loader.log`, and in `MBAccess\logs` for `mbaccess.log`.
- If another mod already put a `dinput8.dll` in the game's folder, the setup keeps it as `dinput8.dll.before-mbaccess`; that other mod won't load while MB Access is installed.

## Before you play

**Keys.** Warband puts attack and defend on the mouse. On a first install the setup replaces the game's key bindings with a keyboard layout: **Up arrow** attacks, **Down arrow** defends, **Page Up** is next weapon and **Page Down** is next shield. Your previous bindings are kept and come back if you uninstall. Updating never touches your keys again, so you can change them on the game's Controls screen.

**Options.** These are the game's own settings, on its Options screen, that make fighting workable without sight. The setup does not change them:

- **Control Block Direction:** Automatic.
- **Control Attack Direction:** By movement keys is the easiest to control.
- **Damage to Player:** Reduced to 1/4 while you learn.

The mod never takes over a key the game uses. Its keys in scenes are letters the game leaves free.

Press **F9** anywhere for the mod's built-in help, which lists these keys by screen.

## Keys

### Anywhere

- **F9:** help. Up and Down read a line, Control+Up and Control+Down jump between groups, F9 or Escape closes it.
- **Control:** stop speech.
- **While the NVDA key is held**, keys go to NVDA and not to the mod.

### Game messages

New messages are spoken as they appear.

- **Left bracket, right bracket:** previous or next message buffer: All, then one per category such as Combat or Money and trade.
- **Comma, period:** previous or next message in the buffer.
- **Shift+Comma, Shift+Period:** oldest or newest message.

### Menus and screens

- **Up, Down:** previous or next item. **Home, End:** first or last. Hold an arrow to keep moving.
- **Enter or Space:** press the item.
- **Escape:** go back. It presses the screen's own way out (Go back, Leave, Resume travelling, Done). Where there is none, Escape is the game's own.
- **Tab, Shift+Tab** (or Control+Right, Control+Left): next or previous section, on screens that have them, such as the columns of the party and character screens.
- **Left, Right:** change a slider, spinner or drop-down, or raise a skill or attribute that has a plus button.
- **Letters and numbers:** jump to the next item starting with them.
- **In a name box:** type as usual; the letters are read back.

### Inventory and trading

The inventory is grids: your equipment, your bag, and the other side (Discard, a merchant, or loot).

- **Arrows:** move cell by cell. **Tab, Shift+Tab:** switch grid.
- **Enter:** pick up the item; Enter on another cell puts it down. This equips, unequips, discards, loots, buys and sells.
- **Control+Enter:** move the item to the other side at once: quick buy, sell or take.
- **Shift+Enter:** the item's special action, if it has one.

### Scenes: walking, riding and fighting

- **O, L:** scanner, ahead and behind. **K, Semicolon:** scanner, left and right.
- **Shift+K, Shift+L:** previous or next scanner category.
- **J:** where the thing you last heard is now. **Shift+J:** track it with a ping, or stop tracking.
- **Apostrophe:** compass.
- **Left, Right arrow (held, on foot):** turn on the spot.
- **Shift+A, Shift+D:** turn 45 degrees left or right. **Shift+S:** turn right round.
- **Control+A, Control+D:** turn to the next thing on your left or right in the scanner's category.
- **F:** the game's Action key. The mod reads the prompt (Talk, Mount, go through a door) and handles dismounting.
- **H:** your health, your horse's, what you hold, shield strength and ammunition.
- **B:** battle status. **N:** nearest enemy. **M:** read the open order list again.
- **1, 2, 3, 0, then a function key:** the game's troop orders; see [Combat](#combat).

### World map

- **Up, Down:** the list of places and visible parties, nearest first.
- **Enter:** travel there. **Shift+Enter:** the place's right-click menu.
- **F:** search the places. **Tab:** the map's buttons.
- **I, P, C, Q:** the game's own shortcuts: inventory, party, character, quests.

## The scanner

The scanner is how you find out what is around you in a scene. It lays everything out on two lines through you:

- **O** and **L** are the ahead and behind line. The first press of O gives the nearest thing ahead; each further press steps one thing further ahead. L does the same going back.
- **K** and **Semicolon** are the left and right line, in the same way.
- "Ahead" means within 45 degrees of straight ahead; the same for the other three sides.
- At the end of a line you hear "nothing further" and the side.

Each thing is read with its distance and direction.

**Categories** narrow the lists: Shift+K and Shift+L step through All, People, Exits, Items, Objects and Animals, and in a fight Enemies and Allies.

Once the scanner has read you something, three more keys work on it:

- **J** tells you where it is now: distance, direction, and how far above or below you.
- **Shift+J** tracks it. A soft ping plays from where it is, lower in pitch when it is behind you and quicker as you get close. Shift+J again stops.
- **Control+A** and **Control+D** turn you to face the next thing round on that side, so you can walk straight to it.

## Navigation on foot

W, A, S and D move you as usual. On foot they follow the camera, and the mod turns the camera for you.

- **Turning:** hold Left or Right arrow to turn on the spot; Apostrophe says the compass direction you now face. Shift+A and Shift+D turn exactly 45 degrees, Shift+S turns you round. The arrow turning speed is a setting.
- **Walls:** beeps warn you of walls in eight directions, one for each way the movement keys can take you. Each direction has its own sound and position around your head, and each step closer beeps a little higher. They start about 4 metres away.
- **Openings:** a soft whoosh from the left, ahead or right means a wall there falls away, like a side street or a doorway.
- **Stairs and drops:** a two-note slur, once, from its direction: rising for a way up, falling for a way down or a drop. After climbing, the mod says how far up or down you went.
- **What's in front:** coming close to something says what it is, like "crude fence" or "village house". This can be turned off.
- **Using things:** a rising two-note sound means F will do something: talk, mount, pick up, go through a door. The prompt is spoken too. With the setting "Use cue plays when" on Close enough, the cue plays when you are near something whichever way you face, and F turns you to it and uses it.
- **Leaving:** Tab leaves a town or village scene to the place's menu, as in the game. Doors and passages are in the scanner's Exits category, with the names the game's menu gives them.

## Navigation on horseback

- **Mounting:** walk up to a horse; the prompt says "Mount" and F mounts.
- **Steering:** A and D steer the horse. Shift+A and Shift+D still turn 45 degrees: the mod holds A or D for you and learns how far your horse swings. Holding the arrow keys does not turn a horse.
- **Walls:** the wall beeps reach further on horseback, about 6 metres, because you arrive faster.
- **Slowing down:** a horse keeps moving after you let go of W. A low hum starts when you release W on a moving horse and slides down in pitch until the horse has stopped.
- **Dismounting:** press F while looking at nothing. Warband only offers Dismount when you look straight down at the horse, so the mod looks down, presses F and looks ahead again.
- The scanner, tracking ping and compass work the same as on foot.

## The world map

The map opens on a list called Places: every town, castle and village, plus moving parties while you can see them, nearest first, each with its distance, direction and owner.

- **Enter** on a place travels there, exactly as clicking it would, and the place's menu opens when you arrive.
- **Shift+Enter** opens the place's right-click menu: Move here, View notes and, for a friendly party or a caravan, Accompany.
- **F** starts a search: type part of a name, Up and Down step through the matches, Enter travels, Escape ends the search.
- **Tab** reaches the map's buttons: Camp, Reports, Notes, Inventory, Character and Party.

To get to the map from a scene: Tab to leave the scene, then Leave in the place's menu.

## Combat

Combat is the newest part of the mod. You can fight, and you can command, but expect rough edges.

### Finding and hitting an enemy

- **Lock-on beeps.** Turn until you hear blips: silence means no enemy is in front of you. Lower, slower blips mean you face an enemy who is still too far; they quicken as you close in. Quick high blips mean your weapon reaches him: attack. The reach comes from the weapon in your hand, so a spear locks on from further than a dagger. With a bow or thrown weapon the quick blips mean you are lined up. Allies never cause blips.
- **N** speaks the nearest enemy; **Control+A** and **Control+D** turn you to one when the scanner is on Enemies.
- **B** says how many stand with you and against you, and where most of each side are.

### Defending

- A short rising **zip** from an enemy's direction means he is close and raising his weapon at you: hold your defend key. It is higher the closer he is.
- A low **creak** means an archer or thrower within 40 metres is aiming at you. It plays at most once every 4 seconds.
- **H** gives your health, your horse's, and your shield's remaining strength. The game's own "Received 3 damage" messages are spoken.

### Commanding

Press **1** for infantry, **2** for archers, **3** for cavalry or **0** for everyone. The game opens an order list, which the mod reads out. Either press the function key the list names (F1, F2 and so on: the row above the numbers, not the letter F), or move through the list with Up and Down and press Enter. A second list follows; choose the same way. While a list is open, Up and Down belong to it and don't attack or defend. **M** reads the open list again. Your troops start a battle already charging.

### Types of combat

- **Custom battle** (main menu): works, and is the best place to practise. Nothing is lost if you fall.
- **Field battles in the campaign:** the same as custom battles. If a friendly lord fights beside you, see the known bugs.
- **Arena melee:** works. The arena's counters are on B.
- **Street fights and bandit ambushes in scenes:** work like any fight on foot.
- **Mounted combat:** you can ride and attack, and the lock-on beeps play, but they don't allow for a horse's speed or a lance's sideways reach.
- **Auto-resolved fights** from the encounter menu, such as ordering your troops to attack without you: ordinary menus, which work.
- **Tournaments:** not tested.
- **Sieges:** not supported yet. Ladders, siege towers and gates are not announced.

## The mod's sounds

Every sound can be heard on its own: open the game's Options, go to the **Accessibility** tab after Controls, and use the Learn sound buttons at the bottom. The same tab holds the mod's settings: which message categories are spoken, how much of an inventory item is read, arrow turning speed, naming what's in front, lock-on beeps, and when the use cue plays.

## What works

- The launcher (Play, Configure and its options).
- Main menu, Load game, Options, Video and Controls, including sliders, drop-downs and checkboxes.
- Character creation, the character screen with skill descriptions, and the face editor.
- All game menus: towns, villages, castles, camp, encounters.
- Conversations and their replies.
- Inventory, looting and trading, with item names, prices and details.
- The party screen, including party skills, and the Notes pages with their links.
- The world map: places list, travel, search, right-click menu.
- Game messages, with history and categories.
- Scenes: scanner, wall beeps, turning, compass, tracking, prompts, mounting and dismounting, doors and passages.
- Fights: health and status keys, order lists, lock-on beeps, swing and aim warnings.
- Question boxes, loading screens and their hints.

## What may not work correctly

These are built but have had little or no testing in real play.

- **The installed program itself.** It was checked to start and wait for the game; a full session from the installed copy has not been played yet.
- **Lock-on reach.** The distance at which the quick blips start adds a guessed allowance to the weapon's length. You may get a lock and miss, or hit without one.
- **Order lists in a real battle.** Arrowing and Enter were tested on a made-up list only.
- **Fighting on horseback** and aiming ranged weapons at enemies above or below you.
- **Trading with merchants:** prices and Control+Enter quick buy and sell were checked against your own bag and the Discard pile, less at a merchant.
- **Load game with several saves,** and the Delete button there.
- **Notes pages** with long scrolling lists, such as Characters and Locations.
- **Party skill bonuses** above skill level 2.
- **Full screen.** The mod was developed with the game in a window. Full screen should behave the same but is untested.
- **Other modules.** Only Native was used. Other modules load their own text and should read, but nothing is promised.
- **Restarting NVDA while the game runs** can bring back speech being cut off while you hold W; restart the game to fix it.

## Known bugs

- The mod sometimes announces "Main menu" while the game is still loading at startup.
- **L** is both the game's Game Log key and the scanner's "behind" key in scenes, so the log can open while you scan.
- When a friendly lord's army fights beside you, his men are counted as enemies by B, N, the scanner and the lock-on beeps.
- The swing warning has no matching sound for the swing ending, and nothing tells you whether your own blow landed apart from the game's messages.

## What does not work yet

- **Mount & Blade: With Fire & Sword.** The mod's core is shared, but that game's memory layout has not been mapped.
- **Sieges:** ladders, siege towers, gates and sally doors.
- **Tournaments:** untested, including the betting screens.
- **Chests** in a castle you own.
- **Multiplayer.**
- **Non-Steam or older versions of Warband.** The mod knows version 1.174 only.
- **The tutorial.**

## How it works

Warband is a native program with no modding interface for this, so MB Access is a separate program that runs beside the game. It reads the game's memory to find out what is on screen and where everything in a scene is, speaks through the Tolk library, plays its sounds in 3D through OpenAL Soft, and presses keys and clicks the mouse where a sighted player would. It never changes the game's files or its memory during play.

A small loader, `dinput8.dll`, sits in the game's folder. The game loads it at startup as if it were the Windows file of that name; it passes everything on to the real one and starts the mod.

Game text is read from the game's own folder and memory at run time. None of the game's files are in this repository.

## Building from source

Python 3.11 (64-bit) on Windows.

```
pip install pymem numpy PyOpenAL pyinstaller pytest
python run.py                    # the mod; start it, then the game
python -m pytest tests           # tests against a fake game
python tools/build_loader.py build      # the 32-bit loader; needs Zig
python tools/build_release.py           # dist/MBAccess-Setup.exe
```

`docs/findings.md` is the index of the research diary: where everything lives in the game's memory and how it was found.

To release: raise `VERSION` in `mbaccess/__init__.py`, build, and publish a GitHub release tagged `v` plus that version with `MBAccess-Setup.exe` attached. The installer finds it by that file name.

## Credits

- [Tolk](https://github.com/dkager/tolk) by Davy Kager, for screen reader speech.
- [OpenAL Soft](https://openal-soft.org/), through PyOpenAL, for 3D sound.
- [Warband Script Enhancer](https://forums.taleworlds.com/index.php?threads/warband-script-enhancer.324890/) by cmpxchg8b, whose published engine headers were the starting map of the game's memory.
- TaleWorlds Entertainment for Mount & Blade and its Module System.
