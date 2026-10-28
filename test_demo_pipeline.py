import unittest

import numpy as np

from backend.geometry import ZoneCrossingState, normalized_polygon, point_inside_polygon


class GeometryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.polygon = normalized_polygon(
            [
                {"x": 0.25, "y": 0.25},
                {"x": 0.75, "y": 0.25},
                {"x": 0.75, "y": 0.75},
                {"x": 0.25, "y": 0.75},
            ],
            640,
            360,
        )

    def test_normalized_polygon_uses_frame_dimensions(self) -> None:
        np.testing.assert_array_equal(self.polygon[0], np.asarray([160, 90]))

    def test_point_in_polygon(self) -> None:
        self.assertTrue(point_inside_polygon(self.polygon, (320, 180)))
        self.assertFalse(point_inside_polygon(self.polygon, (20, 20)))

    def test_zone_entry_only_fires_on_outside_to_inside_transition(self) -> None:
        state = ZoneCrossingState()
        self.assertFalse(state.update(7, False))
        self.assertTrue(state.update(7, True))
        self.assertFalse(state.update(7, True))
        self.assertFalse(state.update(7, False))
        self.assertTrue(state.update(7, True))


if __name__ == "__main__":
    unittest.main()
