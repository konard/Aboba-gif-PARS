# .\parser\drawing_config_generator.py
from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

try:
    from .drawing_schema import (
        BBox3D,
        Dimension,
        DimensionType,
        DrawingView,
        Feature3D,
        FeatureType,
        Orientation,
        PartType,
        ShapeType,
        SurfaceType,
        VIEW_SPECS,
        ViewName,
        to_jsonable,
    )
except ImportError:  # pragma: no cover - used when running as a script from parser/
    from drawing_schema import (
        BBox3D,
        Dimension,
        DimensionType,
        DrawingView,
        Feature3D,
        FeatureType,
        Orientation,
        PartType,
        ShapeType,
        SurfaceType,
        VIEW_SPECS,
        ViewName,
        to_jsonable,
    )


SCHEMA_VERSION = "1.0"
DEFAULT_UNITS = "mm"
ROUND_BBOX_TOLERANCE = 0.15
THIN_PLATE_RATIO = 0.2


@dataclass(frozen=True)
class CylinderData:
    face_id: int | None
    radius: float
    height: float
    center: list[float]
    axis_direction: list[float]
    orientation: Orientation

    @property
    def diameter(self) -> float:
        return 2.0 * self.radius


def _as_mapping(value: Any) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    return {}


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_point(value: Any, default: Sequence[float], length: int) -> list[float]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return [float(item) for item in default[:length]]

    result = [_as_float(item) for item in list(value)[:length]]
    while len(result) < length:
        result.append(float(default[len(result)]))
    return result


def _normalize_orientation(value: Any) -> Orientation:
    try:
        return Orientation(str(value).upper())
    except ValueError:
        return Orientation.FORWARD


def _normalize_surface_type(value: Any) -> str:
    if value is None:
        return SurfaceType.UNKNOWN.value
    return str(value).upper()


def project_point(point_3d: Sequence[float], view: ViewName) -> list[float]:
    point = _as_point(point_3d, [0.0, 0.0, 0.0], 3)
    first, second = VIEW_SPECS[view].coordinate_indices
    return [point[first], point[second]]


def circle_anchor_points(center: Sequence[float], radius: float) -> dict[str, list[float]]:
    center_2d = _as_point(center, [0.0, 0.0], 2)
    x, y = center_2d
    return {
        "center": [x, y],
        "left": [x - radius, y],
        "right": [x + radius, y],
        "top": [x, y + radius],
        "bottom": [x, y - radius],
    }


class DraftingPartClassifier:
    def __init__(self, bbox: BBox3D, faces: Sequence[Mapping[str, Any]]):
        self.bbox = bbox
        self.faces = faces

    def extract_features(self) -> dict[str, Any]:
        surface_counts = Counter(
            _normalize_surface_type(face.get("type")) for face in self.faces
        )
        cylinders = [
            cylinder
            for face in self.faces
            if (cylinder := cylinder_from_face(face, self.bbox)) is not None
        ]
        holes = [
            cylinder
            for cylinder in cylinders
            if cylinder.orientation == Orientation.REVERSED
        ]
        outer_cylinders = [
            cylinder
            for cylinder in cylinders
            if cylinder.orientation == Orientation.FORWARD
        ]

        return {
            "planes": surface_counts[SurfaceType.PLANE.value],
            "cylinders": len(cylinders),
            "cones": surface_counts[SurfaceType.CONE.value],
            "holes": holes,
            "outer_cylinders": outer_cylinders,
            "all_cylinders": cylinders,
        }

    def is_round_plate(self) -> bool:
        dx = abs(self.bbox.dx)
        dy = abs(self.bbox.dy)
        max_xy = max(dx, dy)
        if max_xy <= 0.0:
            return False
        return abs(dx - dy) / max_xy < ROUND_BBOX_TOLERANCE

    def is_thin_plate(self) -> bool:
        dx = abs(self.bbox.dx)
        dy = abs(self.bbox.dy)
        dz = abs(self.bbox.dz)
        min_xy = min(dx, dy)
        if min_xy <= 0.0:
            return False
        return dz < THIN_PLATE_RATIO * min_xy

    def classify(self) -> PartType:
        features = self.extract_features()

        planes = features["planes"]
        holes_count = len(features["holes"])
        outer_count = len(features["outer_cylinders"])
        cones = features["cones"]

        if outer_count == 1 and holes_count == 0 and planes <= 3:
            return PartType.CYLINDER

        if outer_count >= 2:
            radii = sorted(
                (cylinder.radius for cylinder in features["outer_cylinders"]),
                reverse=True,
            )
            if len(radii) >= 2 and radii[1] > 0.3 * radii[0]:
                return PartType.DOUBLE_CYLINDER

        if holes_count == 0 and outer_count == 0 and self.is_thin_plate():
            return PartType.PLATE

        if holes_count > 0:
            if self.is_round_plate():
                return PartType.ROUND_PLATE_WITH_HOLES
            if planes >= 6:
                return PartType.RECTANGULAR_PLATE_WITH_HOLES

        if self.is_thin_plate() and cones == 0:
            return PartType.PLATE

        return PartType.OTHER


def cylinder_from_face(
    face: Mapping[str, Any],
    bbox: BBox3D,
) -> CylinderData | None:
    if _normalize_surface_type(face.get("type")) != SurfaceType.CYLINDER.value:
        return None

    params = _as_mapping(face.get("params"))
    axis = _as_mapping(params.get("axis"))

    return CylinderData(
        face_id=_as_int_or_none(face.get("face_id")),
        radius=_as_float(params.get("radius")),
        height=_as_float(params.get("height"), bbox.dz),
        center=_as_point(axis.get("location"), bbox.center, 3),
        axis_direction=_as_point(axis.get("axis_direction"), [0.0, 0.0, 1.0], 3),
        orientation=_normalize_orientation(params.get("orientation")),
    )


class DrawingConfigGenerator:
    def __init__(
        self,
        drafting_data: Mapping[str, Any],
        source: str = "drafting_data.json",
        units: str = DEFAULT_UNITS,
    ):
        self.drafting_data = _as_mapping(drafting_data)
        self.source = source
        self.units = units
        self.bbox = BBox3D.from_mapping(_as_mapping(self.drafting_data.get("bbox")))
        self.faces = self._faces_from_data()
        self.cylinders = [
            cylinder
            for face in self.faces
            if (cylinder := cylinder_from_face(face, self.bbox)) is not None
        ]
        self.part_type = DraftingPartClassifier(self.bbox, self.faces).classify()

    def generate(self) -> dict[str, Any]:
        features_3d = self._build_features_3d()
        views = {
            view.value: self._build_view(view, features_3d).to_dict()
            for view in ViewName
        }

        return to_jsonable(
            {
                "schema_version": SCHEMA_VERSION,
                "source": self.source,
                "units": self.units,
                "part_type": self.part_type.value,
                "bbox_3d": self.bbox.to_dict(),
                "views": views,
                "features_3d": features_3d,
                "generation_hints_for_csharp": self._generation_hints(),
            }
        )

    def _faces_from_data(self) -> list[Mapping[str, Any]]:
        faces = self.drafting_data.get("faces")
        if not isinstance(faces, Sequence) or isinstance(faces, (str, bytes)):
            return []
        return [_as_mapping(face) for face in faces]

    def _build_features_3d(self) -> list[dict[str, Any]]:
        features: list[dict[str, Any]] = []

        holes = [
            cylinder
            for cylinder in self.cylinders
            if cylinder.orientation == Orientation.REVERSED
        ]
        outer_cylinders = [
            cylinder
            for cylinder in self.cylinders
            if cylinder.orientation == Orientation.FORWARD
        ]

        for index, cylinder in enumerate(holes, start=1):
            features.append(
                self._feature_from_cylinder(
                    cylinder=cylinder,
                    feature_id=f"hole_{index}",
                    feature_type=FeatureType.HOLE,
                )
            )

        for index, cylinder in enumerate(outer_cylinders, start=1):
            features.append(
                self._feature_from_cylinder(
                    cylinder=cylinder,
                    feature_id=f"outer_cylinder_{index}",
                    feature_type=FeatureType.OUTER_CYLINDER,
                )
            )

        return features

    def _feature_from_cylinder(
        self,
        cylinder: CylinderData,
        feature_id: str,
        feature_type: FeatureType,
    ) -> dict[str, Any]:
        projections = {
            view.value: self._circular_projection(cylinder.center, cylinder.radius, view)
            for view in ViewName
        }

        feature = Feature3D(
            id=feature_id,
            type=feature_type,
            shape=ShapeType.CIRCLE,
            center_3d=cylinder.center,
            axis_direction=cylinder.axis_direction,
            radius=cylinder.radius,
            diameter=cylinder.diameter,
            height=cylinder.height,
            source_face_id=cylinder.face_id,
            orientation=cylinder.orientation,
            projections=projections,
        )
        return feature.to_dict()

    def _circular_projection(
        self,
        center_3d: Sequence[float],
        radius: float,
        view: ViewName,
    ) -> dict[str, Any]:
        center = project_point(center_3d, view)
        anchors = circle_anchor_points(center, radius)
        return {
            "center": center,
            "radius": radius,
            "diameter": 2.0 * radius,
            "anchor_points": anchors,
            "centerlines": [
                {
                    "id": "horizontal",
                    "start": anchors["left"],
                    "end": anchors["right"],
                },
                {
                    "id": "vertical",
                    "start": anchors["bottom"],
                    "end": anchors["top"],
                },
            ],
        }

    def _build_view(
        self,
        view: ViewName,
        features_3d: Sequence[Mapping[str, Any]],
    ) -> DrawingView:
        spec = VIEW_SPECS[view]
        view_bbox = self.bbox.view_bbox(view)

        return DrawingView(
            name=view,
            projection_plane=spec.projection_plane,
            visible_axes=list(spec.visible_axes),
            origin_3d=self.bbox.minimum,
            view_bbox_2d=view_bbox,
            outline=self._outline_for_view(view),
            features=self._features_for_view(view, features_3d),
            anchor_points=self._anchor_points_for_view(view_bbox),
            dimensions=self._dimensions_for_view(view, features_3d),
            notes=[],
        )

    def _outline_for_view(self, view: ViewName) -> dict[str, Any]:
        view_bbox = self.bbox.view_bbox(view)
        min_x, min_y = view_bbox.minimum
        max_x, max_y = view_bbox.maximum

        if view == ViewName.TOP and self._is_round_bbox_xy():
            radius = max(abs(self.bbox.dx), abs(self.bbox.dy)) / 2.0
            return {
                "type": ShapeType.CIRCLE.value,
                "source": "bbox_xy",
                "center": view_bbox.center,
                "radius": radius,
                "diameter": 2.0 * radius,
            }

        return {
            "type": ShapeType.RECTANGLE.value,
            "source": f"bbox_{VIEW_SPECS[view].projection_plane.value.lower()}",
            "points": [
                [min_x, min_y],
                [max_x, min_y],
                [max_x, max_y],
                [min_x, max_y],
            ],
        }

    def _is_round_bbox_xy(self) -> bool:
        dx = abs(self.bbox.dx)
        dy = abs(self.bbox.dy)
        max_xy = max(dx, dy)
        if max_xy <= 0.0:
            return False
        return abs(dx - dy) / max_xy < ROUND_BBOX_TOLERANCE

    def _anchor_points_for_view(self, view_bbox: Any) -> dict[str, Any]:
        min_x, min_y = view_bbox.minimum
        max_x, max_y = view_bbox.maximum
        center_x, center_y = view_bbox.center

        return {
            "bbox_min": [min_x, min_y],
            "bbox_max": [max_x, max_y],
            "bbox_center": [center_x, center_y],
            "left_mid": [min_x, center_y],
            "right_mid": [max_x, center_y],
            "top_mid": [center_x, max_y],
            "bottom_mid": [center_x, min_y],
            "corners": {
                "bottom_left": [min_x, min_y],
                "bottom_right": [max_x, min_y],
                "top_right": [max_x, max_y],
                "top_left": [min_x, max_y],
            },
        }

    def _features_for_view(
        self,
        view: ViewName,
        features_3d: Sequence[Mapping[str, Any]],
    ) -> list[dict[str, Any]]:
        view_features = []
        for feature in features_3d:
            if feature.get("type") != FeatureType.HOLE.value:
                continue

            projections = _as_mapping(feature.get("projections"))
            projection = _as_mapping(projections.get(view.value))
            view_features.append(
                {
                    "id": feature.get("id"),
                    "type": feature.get("type"),
                    "shape": feature.get("shape"),
                    "source_feature_3d": feature.get("id"),
                    "center_3d": feature.get("center_3d", []),
                    "axis_direction": feature.get("axis_direction", []),
                    "center": projection.get("center", [0.0, 0.0]),
                    "radius": projection.get("radius", 0.0),
                    "diameter": projection.get("diameter", 0.0),
                    "anchor_points": projection.get("anchor_points", {}),
                    "centerlines": projection.get("centerlines", []),
                    "style_hint": (
                        "visible_circle" if view == ViewName.TOP else "projected_centerline"
                    ),
                }
            )
        return view_features

    def _dimensions_for_view(
        self,
        view: ViewName,
        features_3d: Sequence[Mapping[str, Any]],
    ) -> list[Dimension]:
        dimensions: list[Dimension] = []

        if view == ViewName.TOP:
            dimensions.extend(self._top_global_dimensions())
            dimensions.extend(self._hole_dimensions(features_3d))
            dimensions.extend(self._outer_cylinder_top_dimensions(features_3d))

        if view == ViewName.FRONT:
            dimensions.append(self._thickness_dimension(ViewName.FRONT))
            dimensions.extend(self._outer_cylinder_height_dimensions(view, features_3d))

        if view == ViewName.LEFT:
            dimensions.append(self._thickness_dimension(ViewName.LEFT))
            dimensions.extend(self._outer_cylinder_height_dimensions(view, features_3d))

        return dimensions

    def _top_global_dimensions(self) -> list[Dimension]:
        return [
            Dimension(
                id="dim_length_top",
                type=DimensionType.LINEAR,
                name="LENGTH",
                value=abs(self.bbox.dx),
                view=ViewName.TOP,
                target_feature_id=None,
                points={
                    "start": [self.bbox.xmin, self.bbox.ymin],
                    "end": [self.bbox.xmax, self.bbox.ymin],
                },
                placement_hint="below_outline",
            ),
            Dimension(
                id="dim_width_top",
                type=DimensionType.LINEAR,
                name="WIDTH",
                value=abs(self.bbox.dy),
                view=ViewName.TOP,
                target_feature_id=None,
                points={
                    "start": [self.bbox.xmin, self.bbox.ymin],
                    "end": [self.bbox.xmin, self.bbox.ymax],
                },
                placement_hint="left_of_outline",
            ),
        ]

    def _thickness_dimension(self, view: ViewName) -> Dimension:
        if view == ViewName.FRONT:
            start = [self.bbox.xmax, self.bbox.zmin]
            end = [self.bbox.xmax, self.bbox.zmax]
            dimension_id = "dim_thickness_front"
        else:
            start = [self.bbox.ymax, self.bbox.zmin]
            end = [self.bbox.ymax, self.bbox.zmax]
            dimension_id = "dim_thickness_left"

        return Dimension(
            id=dimension_id,
            type=DimensionType.LINEAR,
            name="THICKNESS",
            value=abs(self.bbox.dz),
            view=view,
            target_feature_id=None,
            points={"start": start, "end": end},
            placement_hint="right_of_outline",
        )

    def _hole_dimensions(
        self,
        features_3d: Sequence[Mapping[str, Any]],
    ) -> list[Dimension]:
        dimensions: list[Dimension] = []
        for feature in features_3d:
            if feature.get("type") != FeatureType.HOLE.value:
                continue
            feature_id = str(feature.get("id"))
            projection = _as_mapping(
                _as_mapping(feature.get("projections")).get(ViewName.TOP.value)
            )
            center = _as_point(projection.get("center"), [0.0, 0.0], 2)
            diameter = _as_float(feature.get("diameter"))
            radius = _as_float(feature.get("radius"))

            dimensions.append(
                Dimension(
                    id=f"dim_{feature_id}_diameter",
                    type=DimensionType.DIAMETER,
                    name="HOLE_DIAMETER",
                    value=diameter,
                    view=ViewName.TOP,
                    target_feature_id=feature_id,
                    points={"center": center},
                    placement_hint="near_hole",
                )
            )
            dimensions.append(
                Dimension(
                    id=f"dim_{feature_id}_center_mark",
                    type=DimensionType.CENTER_MARK,
                    name="HOLE_CENTER_MARK",
                    value=0.0,
                    view=ViewName.TOP,
                    target_feature_id=feature_id,
                    points={
                        "center": center,
                        "horizontal": {
                            "start": [center[0] - radius, center[1]],
                            "end": [center[0] + radius, center[1]],
                        },
                        "vertical": {
                            "start": [center[0], center[1] - radius],
                            "end": [center[0], center[1] + radius],
                        },
                    },
                    placement_hint="at_hole_center",
                )
            )
            dimensions.extend(self._hole_coordinate_dimensions(feature_id, center))

        return dimensions

    def _hole_coordinate_dimensions(
        self,
        feature_id: str,
        center: Sequence[float],
    ) -> list[Dimension]:
        center_2d = _as_point(center, [0.0, 0.0], 2)
        x, y = center_2d
        return [
            Dimension(
                id=f"dim_{feature_id}_center_x",
                type=DimensionType.LINEAR,
                name="HOLE_CENTER_X",
                value=x - self.bbox.xmin,
                view=ViewName.TOP,
                target_feature_id=feature_id,
                points={
                    "start": [self.bbox.xmin, y],
                    "end": [x, y],
                    "reference": "left_bbox_edge",
                },
                placement_hint="horizontal_hole_location",
            ),
            Dimension(
                id=f"dim_{feature_id}_center_y",
                type=DimensionType.LINEAR,
                name="HOLE_CENTER_Y",
                value=y - self.bbox.ymin,
                view=ViewName.TOP,
                target_feature_id=feature_id,
                points={
                    "start": [x, self.bbox.ymin],
                    "end": [x, y],
                    "reference": "bottom_bbox_edge",
                },
                placement_hint="vertical_hole_location",
            ),
        ]

    def _outer_cylinder_top_dimensions(
        self,
        features_3d: Sequence[Mapping[str, Any]],
    ) -> list[Dimension]:
        dimensions: list[Dimension] = []
        for feature in features_3d:
            if feature.get("type") != FeatureType.OUTER_CYLINDER.value:
                continue

            feature_id = str(feature.get("id"))
            projection = _as_mapping(
                _as_mapping(feature.get("projections")).get(ViewName.TOP.value)
            )
            dimensions.append(
                Dimension(
                    id=f"dim_{feature_id}_diameter_top",
                    type=DimensionType.DIAMETER,
                    name="OUTER_DIAMETER",
                    value=_as_float(feature.get("diameter")),
                    view=ViewName.TOP,
                    target_feature_id=feature_id,
                    points={"center": projection.get("center", [0.0, 0.0])},
                    placement_hint="outside_outline",
                )
            )

        return dimensions

    def _outer_cylinder_height_dimensions(
        self,
        view: ViewName,
        features_3d: Sequence[Mapping[str, Any]],
    ) -> list[Dimension]:
        dimensions: list[Dimension] = []
        for feature in features_3d:
            if feature.get("type") != FeatureType.OUTER_CYLINDER.value:
                continue

            feature_id = str(feature.get("id"))
            center_3d = _as_point(feature.get("center_3d"), self.bbox.center, 3)
            start_3d = [center_3d[0], center_3d[1], self.bbox.zmin]
            end_3d = [center_3d[0], center_3d[1], self.bbox.zmax]
            dimensions.append(
                Dimension(
                    id=f"dim_{feature_id}_height_{view.value.lower()}",
                    type=DimensionType.LINEAR,
                    name="CYLINDER_HEIGHT",
                    value=_as_float(feature.get("height"), abs(self.bbox.dz)),
                    view=view,
                    target_feature_id=feature_id,
                    points={
                        "start": project_point(start_3d, view),
                        "end": project_point(end_3d, view),
                    },
                    placement_hint="along_cylinder_axis",
                )
            )

        return dimensions

    def _generation_hints(self) -> dict[str, Any]:
        return {
            "recommended_order": [
                "draw_view_outlines",
                "draw_centerlines",
                "draw_holes",
                "draw_dimensions",
                "draw_annotations",
            ],
            "coordinate_system": (
                "Use projected 2D coordinates from each view. "
                "Do not recompute 3D geometry in C#."
            ),
            "projection_rules": {
                "TOP": "[x, y, z] -> [x, y]",
                "FRONT": "[x, y, z] -> [x, z]",
                "LEFT": "[x, y, z] -> [y, z]",
            },
            "units": self.units,
        }


def build_drawing_config(
    drafting_data: Mapping[str, Any],
    source: str = "drafting_data.json",
    units: str = DEFAULT_UNITS,
) -> dict[str, Any]:
    return DrawingConfigGenerator(
        drafting_data=drafting_data,
        source=source,
        units=units,
    ).generate()


def load_drafting_data(input_path: str | Path) -> dict[str, Any]:
    with Path(input_path).open("r", encoding="utf-8") as file:
        data = json.load(file)
    return dict(_as_mapping(data))


def write_drawing_config(config: Mapping[str, Any], output_path: str | Path) -> None:
    with Path(output_path).open("w", encoding="utf-8") as file:
        json.dump(to_jsonable(dict(config)), file, indent=2, ensure_ascii=False)
        file.write("\n")


def generate_drawing_config_file(
    input_path: str | Path,
    output_path: str | Path,
    units: str = DEFAULT_UNITS,
) -> dict[str, Any]:
    input_path = Path(input_path)
    data = load_drafting_data(input_path)
    config = build_drawing_config(data, source=input_path.name, units=units)
    write_drawing_config(config, output_path)
    return config
