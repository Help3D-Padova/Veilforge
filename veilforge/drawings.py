from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Any

@dataclass
class Stroke:
    id: int
    points: list[tuple[float, float]]  # map coords
    color: tuple[int, int, int, int]
    width: int
    dash: str  # Solid, Dashed, Dotted

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "points": [[float(x), float(y)] for x, y in self.points],
            "color": list(self.color),
            "width": int(self.width),
            "dash": self.dash,
        }

    @staticmethod
    def from_dict(d: Dict[str, Any]) -> "Stroke":
        pts = [(float(p[0]), float(p[1])) for p in d.get("points", [])]
        col = d.get("color", [255, 0, 0, 255])
        if len(col) == 3:
            col = [col[0], col[1], col[2], 255]
        return Stroke(
            id=int(d.get("id", 0)),
            points=pts,
            color=(int(col[0]), int(col[1]), int(col[2]), int(col[3])),
            width=int(d.get("width", 4)),
            dash=str(d.get("dash", "Solid")),
        )
