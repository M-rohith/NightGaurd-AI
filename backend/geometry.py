from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np


def normalized_polygon(points: list[dict[str, float]], width: int, height: int) -> np.ndarray:
    """Convert normalized browser coordinates into an OpenCV polygon."""
    return np.asarray(
        [
            (
                int(round(min(1.0, max(0.0, point["x"])) * width)),
                int(round(min(1.0, max(0.0, point["y"])) * height)),
            )
            for point in points
        ],
        dtype=np.int32,
    )


def point_inside_polygon(polygon: np.ndarray, point: tuple[int, int]) -> bool:
    return cv2.pointPolygonTest(polygon, point, False) >= 0


@dataclass
class ZoneCrossingState:
    """Track outside/inside transitions independently for every ByteTrack ID."""

    previous_inside: dict[int, bool] = field(default_factory=dict)

    def update(self, track_id: int, inside: bool) -> bool:
        was_inside = self.previous_inside.get(track_id, False)
        self.previous_inside[track_id] = inside
        return not was_inside and inside
