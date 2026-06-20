# .\parser\drawing_schema.py
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping


class ViewName(str, Enum):
    TOP = "TOP"
    FRONT = "FRONT"
    LEFT = "LEFT"


class ProjectionPlane(str, Enum):
    XY = "XY"
    XZ = "XZ"
    YZ = "YZ"


class AxisName(str, Enum):
    X = "X"
    Y = "Y"
    Z = "Z"


class SurfaceType(str, Enum):
    PLANE = "PLANE"
    CYLINDER = "CYLINDER"
    CONE = "CONE"
    SPHERE = "SPHERE"
    TORUS = "TORUS"
    FREEFORM_SURFACE = "FREEFORM_SURFACE"
    COMPLEX_SURFACE = "COMPLEX_SURFACE"
    UNKNOWN = "UNKNOWN"


class Orientation(str, Enum):
    FORWARD = "FORWARD"
    REVERSED = "REVERSED"


class PartType(str, Enum):
    CYLINDER = "CYLINDER"
    DOUBLE_CYLINDER = "DOUBLE_CYLINDER"
    PLATE = "PLATE"
    ROUND_PLATE_WITH_HOLES = "ROUND_PLATE_WITH_HOLES"
    RECTANGULAR_PLATE_WITH_HOLES = "RECTANGULAR_PLATE_WITH_HOLES"
    OTHER = "OTHER"


class FeatureType(str, Enum):
    HOLE = "HOLE"
    HOLE_AXIS_PROJECTION = "HOLE_AXIS_PROJECTION"
    OUTER_CYLINDER = "OUTER_CYLINDER"
    CYLINDER_AXIS_PROJECTION = "CYLINDER_AXIS_PROJECTION"


class ShapeType(str, Enum):
    CIRCLE = "CIRCLE"
    CENTERLINE = "CENTERLINE"
    CYLINDER = "CYLINDER"
    RECTANGLE = "RECTANGLE"


class DimensionType(str, Enum):
    LINEAR = "LINEAR"
    DIAMETER = "DIAMETER"
    RADIUS = "RADIUS"
    CENTER_MARK = "CENTER_MARK"


@dataclass(frozen=True)
class ViewSpec:
    name: ViewName
    projection_plane: ProjectionPlane
    visible_axes: tuple[AxisName, AxisName]
    coordinate_indices: tuple[int, int]


VIEW_SPECS: Mapping[ViewName, ViewSpec] = {
    ViewName.TOP: ViewSpec(
        name=ViewName.TOP,
        projection_plane=ProjectionPlane.XY,
        visible_axes=(AxisName.X, AxisName.Y),
        coordinate_indices=(0, 1),
    ),
    ViewName.FRONT: ViewSpec(
        name=ViewName.FRONT,
        projection_plane=ProjectionPlane.XZ,
        visible_axes=(AxisName.X, AxisName.Z),
        coordinate_indices=(0, 2),
    ),
    ViewName.LEFT: ViewSpec(
        name=ViewName.LEFT,
        projection_plane=ProjectionPlane.YZ,
        visible_axes=(AxisName.Y, AxisName.Z),
        coordinate_indices=(1, 2),
    ),
}


def enum_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    return value


def to_jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [to_jsonable(item) for item in value]
    if isinstance(value, list):
        return [to_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(enum_value(key)): to_jsonable(item) for key, item in value.items()}
    return value


def _float_or_default(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class BBox3D:
    xmin: float = 0.0
    ymin: float = 0.0
    zmin: float = 0.0
    xmax: float = 0.0
    ymax: float = 0.0
    zmax: float = 0.0

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any] | None) -> "BBox3D":
        raw = raw or {}
        xmin = _float_or_default(raw.get("xmin"))
        ymin = _float_or_default(raw.get("ymin"))
        zmin = _float_or_default(raw.get("zmin"))

        dx = _float_or_default(raw.get("dx"))
        dy = _float_or_default(raw.get("dy"))
        dz = _float_or_default(raw.get("dz"))

        xmax = _float_or_default(raw.get("xmax"), xmin + dx)
        ymax = _float_or_default(raw.get("ymax"), ymin + dy)
        zmax = _float_or_default(raw.get("zmax"), zmin + dz)

        return cls(
            xmin=xmin,
            ymin=ymin,
            zmin=zmin,
            xmax=xmax,
            ymax=ymax,
            zmax=zmax,
        )

    @property
    def dx(self) -> float:
        return self.xmax - self.xmin

    @property
    def dy(self) -> float:
        return self.ymax - self.ymin

    @property
    def dz(self) -> float:
        return self.zmax - self.zmin

    @property
    def minimum(self) -> list[float]:
        return [self.xmin, self.ymin, self.zmin]

    @property
    def maximum(self) -> list[float]:
        return [self.xmax, self.ymax, self.zmax]

    @property
    def size(self) -> list[float]:
        return [self.dx, self.dy, self.dz]

    @property
    def center(self) -> list[float]:
        return [
            (self.xmin + self.xmax) / 2.0,
            (self.ymin + self.ymax) / 2.0,
            (self.zmin + self.zmax) / 2.0,
        ]

    def view_bbox(self, view: ViewName) -> "ViewBBox2D":
        spec = VIEW_SPECS[view]
        first, second = spec.coordinate_indices
        minimum = self.minimum
        maximum = self.maximum
        return ViewBBox2D(
            minimum=[minimum[first], minimum[second]],
            maximum=[maximum[first], maximum[second]],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "min": self.minimum,
            "max": self.maximum,
            "size": self.size,
            "center": self.center,
        }


@dataclass(frozen=True)
class ViewBBox2D:
    minimum: list[float]
    maximum: list[float]

    @property
    def size(self) -> list[float]:
        return [
            self.maximum[0] - self.minimum[0],
            self.maximum[1] - self.minimum[1],
        ]

    @property
    def center(self) -> list[float]:
        return [
            (self.minimum[0] + self.maximum[0]) / 2.0,
            (self.minimum[1] + self.maximum[1]) / 2.0,
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "min": list(self.minimum),
            "max": list(self.maximum),
            "size": self.size,
            "center": self.center,
        }


@dataclass(frozen=True)
class Feature3D:
    id: str
    type: FeatureType
    shape: ShapeType
    center_3d: list[float]
    axis_direction: list[float]
    radius: float
    diameter: float
    height: float
    source_face_id: int | None
    orientation: Orientation
    projections: Mapping[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "shape": self.shape.value,
            "center_3d": list(self.center_3d),
            "axis_direction": list(self.axis_direction),
            "radius": self.radius,
            "diameter": self.diameter,
            "height": self.height,
            "source_face_id": self.source_face_id,
            "orientation": self.orientation.value,
            "projections": to_jsonable(dict(self.projections)),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class Dimension:
    id: str
    type: DimensionType
    name: str
    value: float | None
    view: ViewName
    target_feature_id: str | None
    points: Mapping[str, Any]
    placement_hint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": self.type.value,
            "name": self.name,
            "value": self.value,
            "view": self.view.value,
            "target_feature_id": self.target_feature_id,
            "points": to_jsonable(dict(self.points)),
            "placement_hint": self.placement_hint,
        }


@dataclass(frozen=True)
class DrawingView:
    name: ViewName
    projection_plane: ProjectionPlane
    visible_axes: list[AxisName]
    origin_3d: list[float]
    view_bbox_2d: ViewBBox2D
    outline: Mapping[str, Any]
    features: list[Mapping[str, Any]]
    anchor_points: Mapping[str, Any]
    dimensions: list[Dimension]
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name.value,
            "projection_plane": self.projection_plane.value,
            "visible_axes": [axis.value for axis in self.visible_axes],
            "origin_3d": list(self.origin_3d),
            "view_bbox_2d": self.view_bbox_2d.to_dict(),
            "outline": to_jsonable(dict(self.outline)),
            "features": to_jsonable(list(self.features)),
            "anchor_points": to_jsonable(dict(self.anchor_points)),
            "dimensions": [dimension.to_dict() for dimension in self.dimensions],
            "notes": list(self.notes),
        }
