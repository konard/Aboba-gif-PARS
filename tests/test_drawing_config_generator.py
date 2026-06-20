import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "parser"))

from drawing_config_generator import build_drawing_config


def sample_round_plate_with_hole():
    return {
        "bbox": {
            "xmin": -10.0,
            "ymin": -10.0,
            "zmin": 0.0,
            "xmax": 10.0,
            "ymax": 10.0,
            "zmax": 2.0,
            "dx": 20.0,
            "dy": 20.0,
            "dz": 2.0,
        },
        "faces": [
            {
                "face_id": 1,
                "type": "CYLINDER",
                "params": {
                    "radius": 10.0,
                    "height": 2.0,
                    "axis": {
                        "location": [0.0, 0.0, 0.0],
                        "axis_direction": [0.0, 0.0, 1.0],
                    },
                    "orientation": "FORWARD",
                },
            },
            {
                "face_id": 2,
                "type": "CYLINDER",
                "params": {
                    "radius": 2.0,
                    "height": 2.0,
                    "axis": {
                        "location": [5.0, -3.0, 0.0],
                        "axis_direction": [0.0, 0.0, 1.0],
                    },
                    "orientation": "REVERSED",
                },
            },
        ],
        "edges": [],
    }


def assert_no_tuples(testcase, value):
    testcase.assertNotIsInstance(value, tuple)
    if isinstance(value, list):
        for item in value:
            assert_no_tuples(testcase, item)
    if isinstance(value, dict):
        for item in value.values():
            assert_no_tuples(testcase, item)


class DrawingConfigGeneratorTests(unittest.TestCase):
    def test_generates_views_holes_anchors_and_dimensions(self):
        config = build_drawing_config(
            sample_round_plate_with_hole(),
            source="drafting_data.json",
        )

        self.assertEqual(config["schema_version"], "1.0")
        self.assertEqual(config["source"], "drafting_data.json")
        self.assertEqual(config["part_type"], "ROUND_PLATE_WITH_HOLES")
        self.assertEqual(set(config["views"]), {"TOP", "FRONT", "LEFT"})

        top_view = config["views"]["TOP"]
        self.assertEqual(top_view["projection_plane"], "XY")
        self.assertEqual(top_view["outline"]["type"], "CIRCLE")
        self.assertEqual(top_view["outline"]["center"], [0.0, 0.0])
        self.assertEqual(top_view["outline"]["radius"], 10.0)

        hole = next(f for f in config["features_3d"] if f["id"] == "hole_1")
        self.assertEqual(hole["type"], "HOLE")
        self.assertEqual(hole["diameter"], 4.0)
        self.assertEqual(hole["center_3d"], [5.0, -3.0, 0.0])
        self.assertEqual(
            hole["projections"]["TOP"]["anchor_points"],
            {
                "center": [5.0, -3.0],
                "left": [3.0, -3.0],
                "right": [7.0, -3.0],
                "top": [5.0, -1.0],
                "bottom": [5.0, -5.0],
            },
        )

        top_dimensions = {d["id"]: d for d in top_view["dimensions"]}
        self.assertEqual(top_dimensions["dim_length_top"]["value"], 20.0)
        self.assertEqual(top_dimensions["dim_width_top"]["value"], 20.0)
        self.assertEqual(top_dimensions["dim_hole_1_diameter"]["value"], 4.0)
        self.assertEqual(top_dimensions["dim_hole_1_center_mark"]["type"], "CENTER_MARK")

        front_dimensions = {d["id"]: d for d in config["views"]["FRONT"]["dimensions"]}
        left_dimensions = {d["id"]: d for d in config["views"]["LEFT"]["dimensions"]}
        self.assertEqual(front_dimensions["dim_thickness_front"]["value"], 2.0)
        self.assertEqual(left_dimensions["dim_thickness_left"]["value"], 2.0)

        assert_no_tuples(self, config)

    def test_missing_fields_are_handled_safely(self):
        config = build_drawing_config(
            {
                "bbox": {"xmin": 0.0, "ymin": 0.0, "zmin": 0.0},
                "faces": [
                    {
                        "face_id": 7,
                        "type": "CYLINDER",
                        "params": {"orientation": "REVERSED"},
                    }
                ],
            }
        )

        hole = next(f for f in config["features_3d"] if f["id"] == "hole_1")
        self.assertEqual(hole["radius"], 0.0)
        self.assertEqual(hole["center_3d"], [0.0, 0.0, 0.0])
        self.assertIn("TOP", config["views"])


if __name__ == "__main__":
    unittest.main()
