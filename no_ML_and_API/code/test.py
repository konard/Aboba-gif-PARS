import os
import ezdxf
import cadquery as cq
import math
from OCP.BRepAdaptor import BRepAdaptor_Surface, BRepAdaptor_Curve
from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Line, GeomAbs_Circle

# --- ЧАСТЬ 1: Чтение и РАСПОЗНАВАНИЕ ПРИЗНАКОВ ---
def analyze_existing_part(filename="test.stp"):
    print(f"[INFO] Чтение файла: {filename}")
    try:
        part = cq.importers.importStep(filename)
    except Exception as e:
        print(f"[ERROR] Не удалось прочитать файл: {e}")
        return None, None
    
    solid = part.val()
    bb = solid.BoundingBox()
    
    print("="*60)
    print(f"[INFO] Габариты 3D модели: X={bb.xlen}, Y={bb.ylen}, Z={bb.zlen}")
    
    unique_holes = {}
    for face in solid.Faces():
        if face.geomType() == 'CYLINDER':
            surf_adaptor = BRepAdaptor_Surface(face.wrapped)
            if surf_adaptor.GetType() == GeomAbs_Cylinder:
                cyl = surf_adaptor.Cylinder()
                radius = cyl.Radius()
                if radius < 1.0: continue
                
                axis = cyl.Axis()
                center = axis.Location()
                direction = axis.Direction()
                
                key = (round(radius, 1), round(center.X(), 1), round(center.Y(), 1), round(center.Z(), 1))
                if key not in unique_holes:
                    unique_holes[key] = {
                        "diameter": round(radius * 2, 2),
                        "center_3d": (center.X(), center.Y(), center.Z()),
                        "axis_3d": (direction.X(), direction.Y(), direction.Z())
                    }
                
    features = {"holes": list(unique_holes.values())}
    print(f"[INFO] Найдено уникальных цилиндрических элементов: {len(features['holes'])}")
    print("="*60)
    return part, features

# --- ЧАСТЬ 2: Чтение STEP и HLR ---
def get_2d_projections(step_file):
    from OCP.STEPControl import STEPControl_Reader
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape
    from OCP.HLRAlgo import HLRAlgo_Projector
    from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

    reader = STEPControl_Reader()
    if reader.ReadFile(step_file) != IFSelect_RetDone:
        return None
        
    reader.TransferRoots()
    shape = reader.OneShape()

    views = {
        "Front": gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, -1, 0), gp_Dir(1, 0, 0)), 
        "Top": gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(0, 0, -1), gp_Dir(1, 0, 0)),   
        "Right": gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(-1, 0, 0), gp_Dir(0, -1, 0))   
    }

    projections_data = {}
    for view_name, ax2 in views.items():
        hlr_algo = HLRBRep_Algo()
        hlr_algo.Add(shape)
        hlr_algo.Projector(HLRAlgo_Projector(ax2))
        hlr_algo.Update()
        hlr_algo.Hide()
        
        hlr_shapes = HLRBRep_HLRToShape(hlr_algo)
        edges = extract_edges_to_primitives(hlr_shapes.VCompound())
        edges = stitch_arcs_to_circles(edges)
        
        cq_shape = cq.Shape(hlr_shapes.VCompound())
        bb_2d = cq_shape.BoundingBox()
        
        projections_data[view_name] = {
            "visible": edges, 
            "bbox": {"min_x": bb_2d.xmin, "max_x": bb_2d.xmax, "min_y": bb_2d.ymin, "max_y": bb_2d.ymax}
        }
    return projections_data

def extract_edges_to_primitives(shape):
    edges_data = []
    if shape.IsNull(): return edges_data
    cq_shape = cq.Shape(shape)
    
    for cq_edge in cq_shape.Edges():
        ocp_edge = cq_edge.wrapped 
        curve_adaptor = BRepAdaptor_Curve(ocp_edge)
        curve_type = curve_adaptor.GetType()
        first_param = curve_adaptor.FirstParameter()
        last_param = curve_adaptor.LastParameter()
        
        if curve_type == GeomAbs_Line:
            p1, p2 = curve_adaptor.Value(first_param), curve_adaptor.Value(last_param)
            edges_data.append({"type": "line", "data": [(p1.X(), p1.Y()), (p2.X(), p2.Y())]})
        elif curve_type == GeomAbs_Circle:
            center, radius = curve_adaptor.Circle().Location(), curve_adaptor.Circle().Radius()
            if (last_param - first_param) >= 2 * math.pi - 0.1:
                edges_data.append({"type": "circle", "data": {"center": (center.X(), center.Y()), "radius": radius, "angle_span": last_param - first_param}})
            else:
                edges_data.append({"type": "arc", "data": {"center": (center.X(), center.Y()), "radius": radius, "angle_span": last_param - first_param}})
    return edges_data

def stitch_arcs_to_circles(edges_data):
    new_edges = [e for e in edges_data if e["type"] != "arc"]
    arcs = [e for e in edges_data if e["type"] == "arc"]
    
    groups = {}
    for arc in arcs:
        c, r = arc["data"]["center"], arc["data"]["radius"]
        key = (round(c[0], 1), round(c[1], 1), round(r, 1))
        groups.setdefault(key, []).append(arc)
        
    for key, group in groups.items():
        if sum(a["data"]["angle_span"] for a in group) >= 2 * math.pi - 0.5:
            new_edges.append({"type": "circle", "data": {"center": group[0]["data"]["center"], "radius": group[0]["data"]["radius"]}})
        else:
            new_edges.extend(group)
    return new_edges

def find_internal_features(lines_data, part_bbox):
    internal_lines = []
    tol = 2.5 
    
    for line in lines_data:
        if line["type"] != "line": continue
        p1, p2 = line["data"]
        mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
        
        if (mx > part_bbox["min_x"] + tol and mx < part_bbox["max_x"] - tol and
            my > part_bbox["min_y"] + tol and my < part_bbox["max_y"] - tol):
            internal_lines.append(line)
            
    if not internal_lines: return []
    
    groups = []
    for line in internal_lines:
        p1, p2 = line["data"]
        matched = False
        for group in groups:
            for g_line in group:
                gp1, gp2 = g_line["data"]
                if min(math.hypot(p1[0]-gp1[0], p1[1]-gp1[1]), math.hypot(p1[0]-gp2[0], p1[1]-gp2[1]),
                       math.hypot(p2[0]-gp1[0], p2[1]-gp1[1]), math.hypot(p2[0]-gp2[0], p2[1]-gp2[1])) < 3.0:
                    group.append(line)
                    matched = True
                    break
            if matched: break
        if not matched:
            groups.append([line])
            
    return [{"min_x": min(p[0] for line in g for p in line["data"]),
             "max_x": max(p[0] for line in g for p in line["data"]),
             "min_y": min(p[1] for line in g for p in line["data"]),
             "max_y": max(p[1] for line in g for p in line["data"])} for g in groups]

# --- ЧАСТЬ 3: Экспорт и РАЗМЕРЫ ---
def export_to_dxf(projections_data, features, output_file="step_to_dxf_step3.dxf"):
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    
    doc.layers.add('VISIBLE', color=7, lineweight=200)
    doc.layers.add('DIMENSIONS', color=7, lineweight=18) 

    dimstyle = doc.dimstyles.new("GOST_STYLE")
    dimstyle.dxf.dimtxsty = "Standard"
    dimstyle.dxf.dimtxt = 3.5
    dimstyle.dxf.dimasz = 2.5
    dimstyle.dxf.dimexe = 1.25
    dimstyle.dxf.dimexo = 1.25
    dimstyle.dxf.dimdec = 0
    dimstyle.dxf.dimtad = 1
    dimstyle.dxf.dimtoh = 0
    dimstyle.dxf.dimclrd = 7
    dimstyle.dxf.dimclre = 7
    dimstyle.dxf.dimclrt = 7
    dimstyle.dxf.dimlfac = 1.0

    layout_positions = {"Front": (0, 0), "Right": (150, 0), "Top": (0, -120)}
    dim_attribs = {'layer': 'DIMENSIONS'}
    view_normals = {"Front": (0, -1, 0), "Top": (0, 0, -1), "Right": (-1, 0, 0)}

    for view_name, data in projections_data.items():
        base_x, base_y = layout_positions[view_name]
        block = doc.blocks.new(name=f"VIEW_{view_name}")
        bb = data["bbox"]
        
        # 1. Геометрия
        for edge in data["visible"]:
            if edge["type"] == "line": block.add_line(edge["data"][0], edge["data"][1], dxfattribs={'layer': 'VISIBLE'})
            elif edge["type"] == "circle": block.add_circle(edge["data"]["center"], edge["data"]["radius"], dxfattribs={'layer': 'VISIBLE'})
            elif edge["type"] == "arc": block.add_lwpolyline(edge["data"].get("points", []), dxfattribs={'layer': 'VISIBLE'})
        
        # ДИНАМИЧЕСКИЕ СЧЕТЧИКИ (ЛЕСЕНКА)
        h_lane = 10.0  # Отступ для горизонтальных размеров (снизу)
        v_lane = 10.0  # Отступ для вертикальных размеров (слева)

        # 2. Прямоугольные отверстия
        rect_features = find_internal_features(data["visible"], bb)
        if rect_features:
            print(f"[INFO] Вид {view_name}: найдено {len(rect_features)} внутр. элементов")
            
            # Горизонтальные (X): Сортируем слева направо
            sorted_x = sorted(rect_features, key=lambda f: f["min_x"])
            for feat in sorted_x:
                # А) Ширина отверстия (ближе к детали)
                y_dim = bb["min_y"] - h_lane
                block.add_linear_dim(base=((feat["min_x"] + feat["max_x"])/2, y_dim),
                                     p1=(feat["min_x"], feat["min_y"]), p2=(feat["max_x"], feat["min_y"]),
                                     angle=0, dimstyle="GOST_STYLE", dxfattribs=dim_attribs)
                h_lane += 8.0
                
                # Б) Привязка к левой базе (дальше)
                y_dim = bb["min_y"] - h_lane
                block.add_linear_dim(base=((bb["min_x"] + feat["min_x"])/2, y_dim),
                                     p1=(bb["min_x"], feat["min_y"]), p2=(feat["min_x"], feat["min_y"]),
                                     angle=0, dimstyle="GOST_STYLE", dxfattribs=dim_attribs)
                h_lane += 8.0

            # Вертикальные (Y): Сортируем снизу вверх
            sorted_y = sorted(rect_features, key=lambda f: f["min_y"])
            for feat in sorted_y:
                # А) Высота отверстия (строго СЛЕВА, чтобы не пересекать деталь)
                # add_aligned_dim автоматически выравнивает размер по вектору p1->p2
                # distance > 0 сдвигает влево от вектора, направленного снизу вверх
                block.add_aligned_dim(p1=(feat["min_x"], feat["min_y"]), p2=(feat["min_x"], feat["max_y"]),
                                      distance=v_lane, dimstyle="GOST_STYLE", dxfattribs=dim_attribs)
                v_lane += 8.0
                
                # Б) Привязка к нижней базе (строго СЛЕВА от детали)
                # p1=край_детали, p2=край_отверстия. distance > 0 сдвигает влево
                block.add_aligned_dim(p1=(bb["min_x"], bb["min_y"]), p2=(bb["min_x"], feat["min_y"]),
                                      distance=v_lane, dimstyle="GOST_STYLE", dxfattribs=dim_attribs)
                v_lane += 8.0

        # 3. Круглые отверстия (Диаметр + Координаты центров)
        if features.get("holes"):
            for hole in features["holes"]:
                axis = hole["axis_3d"]
                view_normal = view_normals[view_name]
                if abs(axis[0]*view_normal[0] + axis[1]*view_normal[1] + axis[2]*view_normal[2]) > 0.9:
                    cx_3d, cy_3d, cz_3d = hole["center_3d"]
                    exp_cx = cx_3d if view_name == "Front" else (cx_3d if view_name == "Top" else -cy_3d)
                    exp_cy = cz_3d if view_name in ["Front", "Right"] else -cy_3d
                    
                    for edge in data["visible"]:
                        if edge["type"] == "circle":
                            c2d, r2d = edge["data"]["center"], edge["data"]["radius"]
                            if math.hypot(c2d[0] - exp_cx, c2d[1] - exp_cy) < 1.0 and abs(r2d - hole["diameter"]/2) < 0.5:
                                cx, cy = c2d
                                
                                # Диаметр
                                block.add_diameter_dim_2p((cx - r2d, cy), (cx + r2d, cy), dimstyle="GOST_STYLE", dxfattribs=dim_attribs)
                                
                                # Координата X центра (продолжаем горизонтальную лесенку)
                                y_dim = bb["min_y"] - h_lane
                                block.add_linear_dim(base=((bb["min_x"] + cx)/2, y_dim),
                                                     p1=(bb["min_x"], cy), p2=(cx, cy),
                                                     angle=0, dimstyle="GOST_STYLE", dxfattribs=dim_attribs)
                                h_lane += 8.0
                                
                                # Координата Y центра (продолжаем вертикальную лесенку)
                                block.add_aligned_dim(p1=(bb["min_x"], bb["min_y"]), p2=(bb["min_x"], cy),
                                                      distance=v_lane, dimstyle="GOST_STYLE", dxfattribs=dim_attribs)
                                v_lane += 8.0
                                break

        # 4. ГАБАРИТНЫЕ РАЗМЕРЫ (САМЫЕ ДАЛЬНИЕ, за пределами всех внутренних размеров)
        # Габарит по ширине (снизу)
        block.add_linear_dim(base=((bb["min_x"] + bb["max_x"])/2, bb["min_y"] - h_lane - 5), 
                             p1=(bb["min_x"], bb["min_y"]), p2=(bb["max_x"], bb["min_y"]), 
                             angle=0, dimstyle="GOST_STYLE", dxfattribs=dim_attribs)
        
        # Габарит по высоте (слева)
        block.add_aligned_dim(p1=(bb["min_x"], bb["min_y"]), p2=(bb["min_x"], bb["max_y"]), 
                              distance=v_lane + 5, dimstyle="GOST_STYLE", dxfattribs=dim_attribs)

        msp.add_blockref(block.name, insert=(base_x, base_y))

    doc.saveas(output_file)
    print(f"[SUCCESS] Сохранено в {output_file}")

if __name__ == "__main__":
    part, features = analyze_existing_part("no_ML_and_API/geometry/test.stp")
    if part:
        projections = get_2d_projections("no_ML_and_API/geometry/test.stp")
        if projections:
            export_to_dxf(projections, features, "no_ML_and_API/results/test.dxf")