# Contributing

Thanks for your interest in contributing!

## Ground rules
- Keep changes focused. One feature/bugfix per PR when possible.
- Avoid large refactors unless discussed first.
- Respect the **non-commercial** license: contributions must remain compatible with it.

## Development setup
1. Python 3.10+
2. Create venv and install deps:

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
```

3. Run:

```bash
python main.py
```

## Style
- Prefer clear names and small functions
- UI/layout: avoid “magic geometry”; use layouts (HBox/VBox/Grid) consistently
- Test common workflows:
  - Open Map
  - Paint fog + Undo/Redo
  - Player Screen ON/OFF
  - Save/Load session

## Reporting bugs
Open an issue with:
- OS + Python version
- Steps to reproduce
- Expected vs actual behavior
- Logs/tracebacks if any
