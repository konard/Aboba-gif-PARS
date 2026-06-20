Ты — эксперт по Python, CAD/CAM и генерации инженерных чертежей.

В проекте есть parser.py, который через OpenCascade читает STEP-файл и создаёт drafting_data.json. Этот JSON содержит bbox, faces и edges. Нужно написать промежуточный Python-слой, который создаёт drawing_config.json — конфиг для будущего AI-агента, который будет писать C#-код генерации чертежа.

Не меняй parser.py. Работай только поверх drafting_data.json.

Нужно создать:
- parser/drawing_config_generator.py
- parser/generate_drawing_config.py

drawing_config.json должен содержать:
- schema_version;
- units;
- part_type;
- bbox_3d;
- views TOP/FRONT/LEFT;
- projection_plane для каждого вида;
- outline каждого вида;
- features каждого вида;
- отверстия;
- центры отверстий;
- anchor_points;
- dimensions;
- generation_hints_for_csharp.

Правила проекций:
TOP: [x,y,z] -> [x,y]
FRONT: [x,y,z] -> [x,z]
LEFT: [x,y,z] -> [y,z]

Правила отверстий:
CYLINDER с orientation == "REVERSED" считать отверстием.
Центр брать из params.axis.location.
Радиус брать из params.radius.
Диаметр = 2 * radius.
Для каждого отверстия создать center, left, right, top, bottom anchor points.

Правила outline:
Если abs(dx - dy) / max(dx, dy) < 0.15, то TOP outline = CIRCLE.
Иначе TOP outline = RECTANGLE по bbox.
FRONT и LEFT outline = RECTANGLE по bbox.

Размеры:
- LENGTH на TOP;
- WIDTH на TOP;
- THICKNESS на FRONT и LEFT;
- DIAMETER для каждого отверстия на TOP;
- CENTER_MARK для каждого отверстия на TOP.

Выходной JSON должен быть удобен для C#-агента: C# не должен пересчитывать геометрию, он должен только рисовать по готовым координатам.

Напиши полный рабочий код с dataclass, типами, безопасным чтением JSON и сохранением результата.