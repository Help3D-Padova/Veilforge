from __future__ import annotations
import json
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any

@dataclass
class SessionData:
    map_path: str
    is_pdf: bool = False
    pdf_page: int = 0
    pdf_dpi: int = 150
    map_rotation_deg: int = 0
    mask_path: str = ""
    drawings: list[dict[str, Any]] = field(default_factory=list)
    grid: dict[str, Any] = field(default_factory=dict)

def save_session(path: str, data: SessionData) -> None:
    Path(path).write_text(json.dumps(asdict(data), indent=2), encoding="utf-8")

def load_session(path: str) -> SessionData:
    obj = json.loads(Path(path).read_text(encoding="utf-8"))
    obj.setdefault("drawings", [])
    obj.setdefault("grid", {})
    return SessionData(**obj)
