# MB Access

Screen reader (NVDA) support for Mount & Blade: Warband and With Fire & Sword.
An external Python program reads the game's memory and speaks through Tolk.

- `python run.py`: the mod. Start it, then start the game.
- `python -m tools.discover`: one-time setup per game version (see docs/research.md).
- `python -m pytest tests`: tests against a fake game; no game needed.

Game files are never copied into this repo; they're read from the game folder at runtime.
