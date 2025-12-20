# Veilforge — Fog of War (DM Tool)

Veilforge is a lightweight desktop tool for tabletop RPGs that lets a DM reveal a map progressively (“fog of war”), project it to a second screen for players, and add quick annotations on top.

> **Donate inside the app:** open **Help → README** to find the Donate panel (QR + button).

[![Youtube Video](https://github.com/user-attachments/assets/4ebbe18a-2930-40af-b22f-c4077cb5ab57)](https://youtu.be/GsCzD6jOgKM)


## Features

- **Fog of War** painting (reveal / hide)
- **Player Screen** output (second monitor / projector, fullscreen)
- **Grid overlay** with adjustable size, offset and alpha
- **Annotations** (draw on top) with brush size + alpha + color picker
- **FOV / Cone tools** (visual field templates)
- **Undo / Redo**, save/load sessions

## Quick Start

1. **Open Map** and pick an image (PNG/JPG).
2. Select the **Target screen** (your projector / second monitor) from the dropdown.
3. Click **Player Screen: ON** to enable the player view (use **Fullscreen** if desired).
4. Use **Fog brush** to reveal areas while you narrate.

## Projector / Second Screen calibration

### 1) Pick the right screen
- Use **Target screen** to choose the monitor/projector resolution you want.
- If the player view shows up on the wrong display, pick the other entry and toggle Player Screen OFF/ON once.

### 2) Fullscreen vs Windowed
- **Fullscreen** is ideal for projectors and TVs.
- Windowed can be useful while calibrating or if your OS fights fullscreen positioning.

## Grid alignment

The grid is meant to match the map’s grid (or your physical table grid).

- **Grid size** changes the cell size (pixels per square).
- **Grid offset X/Y** moves the grid to match the map lines.
- **Grid alpha** controls transparency (higher = more visible).

<img width="1478" height="946" alt="image" src="https://github.com/user-attachments/assets/8eead83b-0fef-471d-9f55-9824966289e4" />

**Workflow tip**
1. Set a rough grid size first.
2. Then fine-tune **offset X/Y** until the lines lock in perfectly.
3. Finally adjust **alpha** so it’s visible but not screaming.

## Fog brush

Fog is a mask over the map. The brush edits the mask.

- **Brush size**: radius of the fog tool.
- **Brush alpha/strength** (if present): how strongly you reveal/hide per stroke.
- Use **Undo Fog / Redo Fog** for quick corrections.
- **Reset Fog** returns the whole map to fully fogged (or default mask state).

## FOV (Field of View) tools

FOV tools are “templates” to quickly show what a character can see.

- Circle / cone / directional shapes (depending on the build)
- Great for stealth / dungeon corners / torchlight vibes
- Adjust parameters (radius/angle) and place on the map

## Annotations

Annotations are “ink” drawn on top of everything (map + fog).  
They are meant for quick, temporary markings during play:

- traps, doors, enemy positions
- arrows, circles, tactical notes
- reminders during combat or exploration

Controls:
- **Color**: pick the pen color
- **Size**: pen thickness
- **Alpha**: transparency (lower = subtle, higher = solid)

### Erasing annotations (important)

There are **two different ways** to erase annotations:

#### 1) Partial erase (brush-style)

- Hold **CTRL** and use **RIGHT mouse button** on the map
- This works like an eraser brush
- Only the area you paint over is removed

Use this when you want to clean or adjust a small part of a drawing.

#### 2) Delete annotation button

- Click **Delete annotation** → deletes the **last annotation stroke**
- **CTRL + click** on **Delete annotation** → deletes **ALL annotations** (with confirmation)

Use this when you want to quickly undo the last drawing or reset all annotations at once.

<img width="1532" height="895" alt="image" src="https://github.com/user-attachments/assets/5fc9bcc2-0e3b-4a8d-bbd5-1ebd40ad8538" />


### Delete annotation button

- Click **Delete annotation** button → deletes the **last stroke**
- **CTRL + click** → deletes **all** annotations (with confirmation)

## Sessions (Save / Load)

- **Save / Save As** stores your current state:
  - map path
  - fog mask
  - grid settings
  - annotations
  - other view settings

Use **Load Session** to resume later exactly where you left off.

## Keyboard / Shortcuts

- Standard OS shortcuts work where applicable.
- Some actions use **modifier keys** (example: **CTRL** with “Delete annotation”).

## Credits

- **Andrea Pirazzini** — main developer
- **Kai Vector** — AI co-dev (design + implementation support)

## Use License (Non-commercial)

You may use this software for personal (non-commercial) purposes.  
You may modify and redistribute the source code and/or binaries **as long as you clearly credit the original project and author(s)**.  
You may **not** monetize it (no selling, no paid bundles, no charging for access).

See **LICENSE.md** for the full text.
