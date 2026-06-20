import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "parser"))

from drawing_config_generator import build_drawing_config


def sample_part_with_hole(axis_direction, include_outer_cylinder=False, bbox=None):
    bbox = bbox or {
        "xmin": 0.0,
        "ymin": 0.0,
        "zmin": 0.0,
        "xmax": 100.0,
        "ymax": 50.0,
        "zmax": 10.0,
        "dx": 100.0,
        "dy": 50.0,
        "dz": 10.0,
    }

    center = [
        (bbox["xmin"] + bbox["xmax"]) / 2.0,
        (bbox["ymin"] + bbox["ymax"]) / 2.0,
        (bbox["zmin"] + bbox["zmax"]) / 2.0,
    ]
    faces = []
    if include_outer_cylinder:
        faces.append(
            {
                "face_id": 1,
                "type": "CYLINDER",
                "params": {
                    "radius": min(abs(bbox["dx"]), abs(bbox["dy"])) / 2.0,
                    "height": abs(bbox["dz"]),
                    "axis": {
                        "location": center,
                        "axis_direction": [0.0, 0.0, 1.0],
                    },
                    "orientation": "FORWARD",
                },
            }
        )

    faces.append(
        {
            "face_id": len(faces) + 1,
            "type": "CYLINDER",
            "params": {
                "radius": 5.0,
                "height": abs(bbox["dz"]),
                "axis": {
                    "location": center,
                    "axis_direction": axis_direction,
                },
                "orientation": "REVERSED",
            },
        }
    )

    return {"bbox": bbox, "faces": faces, "edges": []}


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


def feature_for_source(config, view_name, source_feature_id="hole_1"):
    features = [
        feature
        for feature in config["views"][view_name]["features"]
        if feature.get("source_feature_3d") == source_feature_id
    ]
    if len(features) != 1:
        raise AssertionError(
            f"Expected one feature for {source_feature_id} in {view_name}, got {features!r}"
        )
    return features[0]


def hole_diameter_views(config, source_feature_id="hole_1"):
    views = []
    for view_name, view in config["views"].items():
        for dimension in view["dimensions"]:
            if (
                dimension["type"] == "DIAMETER"
                and dimension["name"] == "HOLE_DIAMETER"
                and dimension["target_feature_id"] == source_feature_id
            ):
                views.append(view_name)
    return views


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
        front_view = config["views"]["FRONT"]
        left_view = config["views"]["LEFT"]
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

        self.assertEqual(feature_for_source(config, "TOP")["shape"], "CIRCLE")
        self.assertNotEqual(feature_for_source(config, "FRONT")["shape"], "CIRCLE")
        self.assertNotEqual(feature_for_source(config, "LEFT")["shape"], "CIRCLE")

        top_dimensions = {d["id"]: d for d in top_view["dimensions"]}
        self.assertEqual(top_dimensions["dim_length_top"]["value"], 20.0)
        self.assertEqual(top_dimensions["dim_width_top"]["value"], 20.0)
        self.assertEqual(top_dimensions["dim_hole_1_diameter_TOP"]["value"], 4.0)
        self.assertEqual(top_dimensions["center_mark_hole_1_TOP"]["type"], "CENTER_MARK")
        self.assertEqual(hole_diameter_views(config), ["TOP"])

        front_dimensions = {d["id"]: d for d in front_view["dimensions"]}
        left_dimensions = {d["id"]: d for d in left_view["dimensions"]}
        self.assertEqual(front_dimensions["dim_thickness_front"]["value"], 2.0)
        self.assertEqual(left_dimensions["dim_thickness_left"]["value"], 2.0)
        self.assertTrue(front_view["notes"])
        self.assertTrue(left_view["notes"])

        assert_no_tuples(self, config)

    def test_hole_along_x_is_circular_only_on_left(self):
        config = build_drawing_config(sample_part_with_hole([1.0, 0.0, 0.0]))

        self.assertNotEqual(feature_for_source(config, "TOP")["shape"], "CIRCLE")
        self.assertNotEqual(feature_for_source(config, "FRONT")["shape"], "CIRCLE")
        self.assertEqual(feature_for_source(config, "LEFT")["shape"], "CIRCLE")
        self.assertEqual(hole_diameter_views(config), ["LEFT"])

    def test_hole_along_y_is_circular_only_on_front(self):
        config = build_drawing_config(sample_part_with_hole([0.0, 1.0, 0.0]))

        self.assertNotEqual(feature_for_source(config, "TOP")["shape"], "CIRCLE")
        self.assertEqual(feature_for_source(config, "FRONT")["shape"], "CIRCLE")
        self.assertNotEqual(feature_for_source(config, "LEFT")["shape"], "CIRCLE")
        self.assertEqual(hole_diameter_views(config), ["FRONT"])

    def test_square_bbox_without_outer_cylinder_uses_rectangular_top_outline(self):
        config = build_drawing_config(
            sample_part_with_hole(
                [0.0, 0.0, 1.0],
                bbox={
                    "xmin": 0.0,
                    "ymin": 0.0,
                    "zmin": 0.0,
                    "xmax": 100.0,
                    "ymax": 100.0,
                    "zmax": 10.0,
                    "dx": 100.0,
                    "dy": 100.0,
                    "dz": 10.0,
                },
            )
        )

        self.assertEqual(config["views"]["TOP"]["outline"]["type"], "RECTANGLE")
        self.assertIn("round bbox alone", " ".join(config["views"]["TOP"]["notes"]))

    def test_round_plate_with_outer_cylinder_uses_circular_top_outline(self):
        config = build_drawing_config(
            sample_part_with_hole(
                [0.0, 0.0, 1.0],
                include_outer_cylinder=True,
                bbox={
                    "xmin": -50.0,
                    "ymin": -50.0,
                    "zmin": 0.0,
                    "xmax": 50.0,
                    "ymax": 50.0,
                    "zmax": 10.0,
                    "dx": 100.0,
                    "dy": 100.0,
                    "dz": 10.0,
                },
            )
        )

        self.assertEqual(config["views"]["TOP"]["outline"]["type"], "CIRCLE")

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
