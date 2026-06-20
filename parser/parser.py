# .\parser\parser.py
import os
import sys
import json
import faulthandler
import numpy as np

from OCC.Core.BRepGProp import brepgprop
from OCC.Core.GProp import GProp_GProps
from OCC.Core.TopTools import TopTools_IndexedDataMapOfShapeListOfShape
from OCC.Core.TopExp import topexp
from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopAbs import TopAbs_FACE, TopAbs_FORWARD, TopAbs_REVERSED, TopAbs_EDGE
from OCC.Core.BRepAdaptor import BRepAdaptor_Surface, BRepAdaptor_Curve
from OCC.Core.GeomAbs import (
    GeomAbs_Plane, GeomAbs_Cylinder, GeomAbs_Cone, 
    GeomAbs_Sphere, GeomAbs_Torus, GeomAbs_BSplineSurface, 
    GeomAbs_BezierSurface, GeomAbs_SurfaceOfRevolution, 
    GeomAbs_SurfaceOfExtrusion, GeomAbs_Line, GeomAbs_Circle, GeomAbs_Ellipse
)
from OCC.Core.Interface import Interface_Static
from OCC.Core.Bnd import Bnd_Box
from OCC.Core.BRepBndLib import brepbndlib
from OCC.Core.GCPnts import GCPnts_AbscissaPoint

from OCC.Core.BRep import BRep_Tool

import OCC.Core.TopoDS as TopoDS_module

CAST_TO_EDGE = getattr(
    TopoDS_module,
    [n for n in dir(TopoDS_module) if "edge" in n.lower()][0]
)

faulthandler.enable()

_cast_funcs = [name for name in dir(TopoDS_module) if 'face' in name.lower()]
if not _cast_funcs:
    raise ImportError("Не найдена функция кастинга Face в TopoDS. Проверьте установку pythonocc-core.")
CAST_TO_FACE = getattr(TopoDS_module, _cast_funcs[0])

def occ_pnt_to_tuple(pnt): 
    return (pnt.X(), pnt.Y(), pnt.Z())

def occ_dir_to_tuple(dir_vec): 
    return (dir_vec.X(), dir_vec.Y(), dir_vec.Z())

def occ_ax3_to_dict(ax3):
    return {
        "location": occ_pnt_to_tuple(ax3.Location()),
        "axis_direction": occ_dir_to_tuple(ax3.Axis().Direction()),
        "x_direction": occ_dir_to_tuple(ax3.XDirection()),
        "y_direction": occ_dir_to_tuple(ax3.YDirection())
    }

def face_area(face):
    props = GProp_GProps()
    brepgprop.SurfaceProperties(face, props)
    return props.Mass()

def face_orientation(face):

    orient = face.Orientation()

    if orient == TopAbs_FORWARD:
        return "FORWARD"

    if orient == TopAbs_REVERSED:
        return "REVERSED"

    return str(int(orient))

def compute_bbox(shape):

    bbox = Bnd_Box()

    brepbndlib.Add(shape, bbox)

    xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()

    return {
        "xmin": xmin,
        "ymin": ymin,
        "zmin": zmin,
        "xmax": xmax,
        "ymax": ymax,
        "zmax": zmax,

        "dx": xmax - xmin,
        "dy": ymax - ymin,
        "dz": zmax - zmin
    }

def analyze_faces_for_drafting(shape):
    """
    Извлекает аналитические параметры граней для инженерного анализа и чертежей.
    """
    if shape.IsNull():
        raise ValueError("Передан пустой (Null) Shape. Невозможно выполнить анализ.")
    
    face_adjacency = TopTools_IndexedDataMapOfShapeListOfShape()

    topexp.MapShapesAndAncestors(
        shape,
        TopAbs_FACE,
        TopAbs_FACE,
        face_adjacency
    )
        
    explorer = TopExp_Explorer(shape, TopAbs_FACE)
    features = []
    face_idx = 0
    
    while explorer.More():
        try:
            face = CAST_TO_FACE(explorer.Current())
            if face.IsNull():
                print(f"  [WARN] Грань #{face_idx} пропущена (Null Face)")
                face_idx += 1
                explorer.Next()
                continue
                
            adaptor = BRepAdaptor_Surface(face)
            surf_type = adaptor.GetType()
            
            feature = {
                "face_id": face_idx,
                "type": "UNKNOWN",
                "params": {},
                "area": face_area(face),
                "adjacent_faces": []
            }
            
            if surf_type == GeomAbs_Plane:
                plane = adaptor.Plane()
                feature["type"] = "PLANE"
                feature["params"] = {
                    "location": occ_pnt_to_tuple(plane.Location()),
                    "normal": occ_dir_to_tuple(plane.Axis().Direction())
                }
            elif surf_type == GeomAbs_Cylinder:
                cyl = adaptor.Cylinder()
                v1 = adaptor.FirstVParameter()
                v2 = adaptor.LastVParameter()
                feature["type"] = "CYLINDER"
                height = abs(v2 - v1)

                feature["params"] = {
                    "radius": cyl.Radius(),
                    "height": height,
                    "axis": occ_ax3_to_dict(cyl.Position()),
                    "orientation": face_orientation(face)
                }
            elif surf_type == GeomAbs_Cone:
                cone = adaptor.Cone()
                feature["type"] = "CONE"
                feature["params"] = {
                    "radius": cone.RefRadius(),
                    "semi_angle": cone.SemiAngle(),
                    "axis": occ_ax3_to_dict(cone.Position())
                }
            elif surf_type == GeomAbs_Sphere:
                sphere = adaptor.Sphere()
                feature["type"] = "SPHERE"
                feature["params"] = {
                    "radius": sphere.Radius(),
                    "center": occ_pnt_to_tuple(sphere.Position().Location())
                }
            elif surf_type == GeomAbs_Torus:
                torus = adaptor.Torus()
                feature["type"] = "TORUS"
                feature["params"] = {
                    "major_radius": torus.MajorRadius(),
                    "minor_radius": torus.MinorRadius(),
                    "axis": occ_ax3_to_dict(torus.Position())
                }
            elif surf_type in (GeomAbs_BSplineSurface, GeomAbs_BezierSurface):
                feature["type"] = "FREEFORM_SURFACE"
                feature["params"] = {"note": "NURBS/Bezier. Требует аппроксимации для чертежей."}
            else:
                feature["type"] = "COMPLEX_SURFACE"
                feature["params"] = {"occ_type": str(surf_type)}

            features.append(feature)
        except Exception as e:
            print(f"  [ERROR] Ошибка обработки грани #{face_idx}: {type(e).__name__} | {e}")
            
        face_idx += 1
        explorer.Next()
        
    return features

def analyze_edges(shape):

    explorer = TopExp_Explorer(shape, TopAbs_EDGE)

    edges = []
    edge_idx = 0

    while explorer.More():

        try:

            edge = CAST_TO_EDGE(explorer.Current())

            adaptor = BRepAdaptor_Curve(edge)

            curve_type = adaptor.GetType()

            edge_data = {
                "edge_id": edge_idx,
                "type": "UNKNOWN",
                "params": {}
            }
            length = GCPnts_AbscissaPoint.Length(adaptor)

            # ---------------------------------
            # Линия
            # ---------------------------------

            if curve_type == GeomAbs_Line:

                p1 = adaptor.Value(adaptor.FirstParameter())
                p2 = adaptor.Value(adaptor.LastParameter())

                edge_data["type"] = "LINE"

                edge_data["params"] = {
                    "start": occ_pnt_to_tuple(p1),
                    "end": occ_pnt_to_tuple(p2),
                    "length": length
                }

            # ---------------------------------
            # Окружность
            # ---------------------------------

            elif curve_type == GeomAbs_Circle:

                circle = adaptor.Circle()

                edge_data["type"] = "CIRCLE"

                edge_data["params"] = {
                    "center":
                        occ_pnt_to_tuple(
                            circle.Location()
                        ),
                    "radius":
                        circle.Radius(),
                    "axis":
                        occ_ax3_to_dict(
                            circle.Position()
                        ),
                    "length": length
                }

            # ---------------------------------
            # Эллипс
            # ---------------------------------

            elif curve_type == GeomAbs_Ellipse:

                ellipse = adaptor.Ellipse()

                edge_data["type"] = "ELLIPSE"

                edge_data["params"] = {
                    "center":
                        occ_pnt_to_tuple(
                            ellipse.Location()
                        ),
                    "major_radius":
                        ellipse.MajorRadius(),
                    "minor_radius":
                        ellipse.MinorRadius(),
                }

            edges.append(edge_data)

        except Exception as e:

            print(
                f"[EDGE ERROR] #{edge_idx}: "
                f"{type(e).__name__}: {e}"
            )

        edge_idx += 1
        explorer.Next()

    return edges

def save_drafting_data(
        features,
        edges,
        bbox,
        output_file="geometry/drafting_data.json"):

    result = {
        "bbox": bbox,
        "faces": features,
        "edges": edges
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(
            result,
            f,
            indent=2,
            ensure_ascii=False
        )

    print(f"Данные сохранены в {output_file}")

    return output_file

if __name__ == "__main__":
    STEP_FILE = "C:\\Users\\Yascher\\Desktop\\Практика\\top_systems_pract\\geometry\\round_list_with_holes.stp"
    
    try:
        if not os.path.exists(STEP_FILE):
            raise FileNotFoundError(f"Файл не найден по пути: {STEP_FILE}")
            
        print("Загрузка STEP-файла...")
        reader = STEPControl_Reader()
        
        Interface_Static.SetIVal("read.step.shape.healing", 1)
        Interface_Static.SetRVal("read.step.precision.val", 0.001)
        

        read_status = reader.ReadFile(STEP_FILE)
        if read_status != 1:
            raise RuntimeError(f"Ошибка чтения файла. Статус OCCT: {read_status}")
        print("Файл успешно прочитан в память.")

        print("Трансфер данных в топологическое дерево...")
        try:
            reader.TransferRoots()
        except Exception as e:
            raise RuntimeError(f"Crash/ошибка при TransferRoots: {e}") from e
            
        shape = reader.OneShape()
        if shape.IsNull():
            raise RuntimeError("Получен пустой (Null) Shape. Вероятно, файл пуст или содержит только мета-данные.")
        print(f"Shape загружен. Тип: {shape.ShapeType()}")
        bbox = compute_bbox(shape)

        print("\nBOUNDING BOX:")
        for k, v in bbox.items():
            print(f"{k}: {v:.3f}")

        print("Анализ геометрии граней...")
        features = analyze_faces_for_drafting(shape)
        print(f"Обработано граней: {len(features)}")

        edges = analyze_edges(shape)

        print(f"Обработано ребер: {len(edges)}")
        
        type_counts = {}
        for f in features:
            type_counts[f["type"]] = type_counts.get(f["type"], 0) + 1
        print("ТИПЫ ПОВЕРХНОСТЕЙ:", type_counts)
        
        print("Сохранение данных...")
        save_drafting_data(
            features,
            edges,
            bbox
        )
        print("Скрипт завершён успешно.")
        
    except FileNotFoundError as e:
        print(f"Ошибка доступа к файлу: {e}")
        sys.exit(1)
    except RuntimeError as e:
        print(f"Критическая ошибка ядра OCCT: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Неожиданная ошибка: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)