import json
import numpy as np
from collections import Counter


class PartClassifier:

    def __init__(self, json_file):
        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.bbox = data["bbox"]
        self.faces = data["faces"]

    # -----------------------------
    # FEATURES
    # -----------------------------
    def extract_features(self):

        types = Counter(f["type"] for f in self.faces)

        cylinders = []
        holes = []
        outer_cylinders = []
        cones = 0

        for f in self.faces:

            t = f["type"]

            if t == "CONE":
                cones += 1

            if t != "CYLINDER":
                continue

            params = f["params"]

            cyl = {
                "radius": params.get("radius", 0),
                "height": params.get("height", 0),
                "area": f.get("area", 0),
                "orientation": params.get("orientation", None)
            }

            cylinders.append(cyl)

            # отверстие
            if cyl["orientation"] == "REVERSED":
                holes.append(cyl)
            else:
                outer_cylinders.append(cyl)

        return {
            "planes": types["PLANE"],
            "cylinders": len(cylinders),
            "cones": cones,

            "holes": holes,
            "outer_cylinders": outer_cylinders,

            "all_cylinders": cylinders
        }

    # -----------------------------
    # GEOMETRY HELPERS
    # -----------------------------
    def is_round_plate(self):

        dx = self.bbox["dx"]
        dy = self.bbox["dy"]

        return abs(dx - dy) / max(dx, dy) < 0.15

    def is_thin_plate(self):

        dx = self.bbox["dx"]
        dy = self.bbox["dy"]
        dz = self.bbox["dz"]

        return dz < 0.2 * min(dx, dy)

    # -----------------------------
    # CLASSIFICATION
    # -----------------------------
    def classify(self):

        f = self.extract_features()

        planes = f["planes"]
        holes = len(f["holes"])
        outer = len(f["outer_cylinders"])
        cylinders = f["cylinders"]
        cones = f["cones"]

        bbox = self.bbox

        dx, dy, dz = bbox["dx"], bbox["dy"], bbox["dz"]

        # --------------------------------------------------
        # 1. Обычный цилиндр
        # --------------------------------------------------
        if outer == 1 and holes == 0 and planes <= 3:

            # if dz > 2 * max(dx, dy):
            return "CYLINDER"

        # --------------------------------------------------
        # 2. Два цилиндра
        # --------------------------------------------------
        if outer >= 2:

            radii = sorted(
                [c["radius"] for c in f["outer_cylinders"]],
                reverse=True
            )

            if len(radii) >= 2 and radii[1] > 0.3 * radii[0]:
                return "DOUBLE_CYLINDER"

        # --------------------------------------------------
        # 3. Лист без отверстий
        # --------------------------------------------------
        if holes == 0 and outer == 0:

            if self.is_thin_plate():
                return "PLATE"

        # --------------------------------------------------
        # 4. Лист с отверстиями
        # --------------------------------------------------
        if holes > 0:

            # -----------------------------
            # КРУГЛЫЙ ЛИСТ
            # -----------------------------
            if self.is_round_plate():
                return "ROUND_PLATE_WITH_HOLES"

            # -----------------------------
            # ПРЯМОУГОЛЬНЫЙ ЛИСТ
            # -----------------------------
            if planes >= 6:
                return "RECTANGULAR_PLATE_WITH_HOLES"

        # --------------------------------------------------
        # 5. Лист (если не попал выше)
        # --------------------------------------------------
        if self.is_thin_plate():
            return "PLATE"

        # --------------------------------------------------
        # 6. Всё остальное
        # --------------------------------------------------
        return "OTHER"
    
class DimensionGenerator:

    def __init__(self, data, part_type):
        self.data = data
        self.part_type = part_type

        self.bbox = data["bbox"]
        self.faces = data["faces"]

    # ----------------------------
    # BASIC HELPERS
    # ----------------------------

    def project(self, p, view):

        x, y, z = p

        if view == "TOP":
            return [x, y]

        if view == "FRONT":
            return [x, z]

        if view == "LEFT":
            return [y, z]

        return [x, y]

    # ----------------------------
    # FEATURE EXTRACTION
    # ----------------------------

    def get_cylinders(self):

        cyls = []

        for f in self.faces:

            if f["type"] != "CYLINDER":
                continue

            p = f["params"]

            cyls.append({
                "radius": p["radius"],
                "height": p["height"],
                "center": p["axis"]["location"],
                "orientation": p.get("orientation", "FORWARD")
            })

        return cyls

    def get_holes(self):

        return [
            c for c in self.get_cylinders()
            if c["orientation"] == "REVERSED"
        ]

    def get_outer_cylinders(self):

        return [
            c for c in self.get_cylinders()
            if c["orientation"] == "FORWARD"
        ]

    # ----------------------------
    # BBOX FEATURES
    # ----------------------------

    def bbox_dims(self):

        dx = self.bbox["dx"]
        dy = self.bbox["dy"]
        dz = self.bbox["dz"]

        return dx, dy, dz

    # ----------------------------
    # DIMENSIONS
    # ----------------------------

    def generate_global_dimensions(self):

        dx, dy, dz = self.bbox_dims()

        dims = [
            {
                "type": "LINEAR",
                "name": "LENGTH",
                "value": max(dx, dy)
            },
            {
                "type": "LINEAR",
                "name": "WIDTH",
                "value": min(dx, dy)
            },
            {
                "type": "LINEAR",
                "name": "THICKNESS",
                "value": dz
            }
        ]

        return dims

    def generate_cylinder_dimensions(self):

        cyls = self.get_outer_cylinders()

        dims = []

        for c in cyls:

            dims.append({
                "type": "DIAMETER",
                "value": 2 * c["radius"],
                "center_3d": c["center"]
            })

            dims.append({
                "type": "LINEAR",
                "name": "HEIGHT",
                "value": c["height"],
                "center_3d": c["center"]
            })

        return dims

    def generate_hole_dimensions(self):

        holes = self.get_holes()

        dims = []

        for h in holes:

            center = h["center"]
            r = h["radius"]

            dims.append({
                "type": "DIAMETER",
                "value": 2 * r,
                "center_3d": center
            })

            # position relative bbox origin
            dims.append({
                "type": "HOLE_POS_X",
                "value": center[0]
            })

            dims.append({
                "type": "HOLE_POS_Y",
                "value": center[1]
            })

        return dims
    
    def allowed_views(self, dim):

        t = dim["type"]

        # ------------------------
        # CYLINDER / ROUND PARTS
        # ------------------------

        if self.part_type in ["CYLINDER", "ROUND_PLATE_WITH_HOLES"]:

            if t == "DIAMETER":
                return ["TOP"]

            if t == "LINEAR" and dim.get("name") == "HEIGHT":
                return ["FRONT", "LEFT"]

            if t == "LINEAR" and dim.get("name") == "THICKNESS":
                return ["FRONT", "LEFT"]

        # ------------------------
        # RECTANGULAR PLATE
        # ------------------------

        if self.part_type == "RECTANGULAR_PLATE_WITH_HOLES":

            if t in ["LINEAR", "GLOBAL"]:

                if dim.get("name") in ["LENGTH", "WIDTH"]:
                    return ["TOP"]

                if dim.get("name") == "THICKNESS":
                    return ["FRONT", "LEFT"]

            if t == "DIAMETER":
                return ["TOP"]

            if t == "HOLE_POS_X" or t == "HOLE_POS_Y":
                return ["TOP"]

        # ------------------------
        # DOUBLE CYLINDER
        # ------------------------

        if self.part_type == "DOUBLE_CYLINDER":

            if t == "DIAMETER":
                return ["TOP", "FRONT"]

            if t == "LINEAR":
                return ["FRONT", "LEFT"]

        # fallback
        return ["TOP", "FRONT", "LEFT"]

    # ----------------------------
    # VIEW GENERATION
    # ----------------------------

    def build_view(self, view):

        dims = []

        dims += self.generate_global_dimensions()
        dims += self.generate_cylinder_dimensions()
        dims += self.generate_hole_dimensions()

        projected = []

        for d in dims:

            allowed = self.allowed_views(d)

            if view not in allowed:
                continue   # ❌ ВЫКИДЫВАЕМ размер

            d2 = d.copy()

            if "center_3d" in d2:
                d2["center_2d"] = self.project(d2["center_3d"], view)
                del d2["center_3d"]

            projected.append(d2)

        return {
            "view": view,
            "dimensions": projected
        }

    # ----------------------------
    # MAIN
    # ----------------------------

    def generate(self):

        return {
            "part_type": self.part_type,

            "views": {
                "TOP": self.build_view("TOP"),
                "FRONT": self.build_view("FRONT"),
                "LEFT": self.build_view("LEFT")
            }
        }

    
if __name__ == "__main__":
    classifier = PartClassifier("drafting_data.json")

    features = classifier.extract_features()

    print("FEATURES:")
    for k, v in features.items():
        if k.endswith("_data"):
            continue
        print(k, "=", v)
    part_type = classifier.classify()
    print("\nCLASS =", part_type)

    # part_type = classifier.classify()  # сюда вставь результат классификатора
    with open("drafting_data.json", "r", encoding="utf-8") as f:
        data = json.load(f)

    gen = DimensionGenerator(data, part_type)

    result = gen.generate()

    with open("drawing_dimensions.json", "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print("DONE -> drawing_dimensions.json")