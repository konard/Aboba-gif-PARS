# Pipeline генерации данных для чертежа

Папка `parser/` содержит два этапа подготовки данных:

```text
STEP-файл
  -> parser.py
  -> parser/drafting_data.json
  -> drawing_config_generator.py / generate_drawing_config.py
  -> parser/drawing_config.json
  -> C#-агент генерации чертежа
```

## `parser.py`

`parser.py` читает STEP-файл через `pythonocc-core` / OpenCascade, извлекает аналитические поверхности, ребра и габаритный 3D bbox, затем сохраняет низкоуровневый JSON `parser/drafting_data.json`.

В `drafting_data.json` попадают:

- `bbox`: `xmin`, `ymin`, `zmin`, `xmax`, `ymax`, `zmax`, `dx`, `dy`, `dz`;
- `faces`: грани с типами `PLANE`, `CYLINDER`, `CONE`, `SPHERE`, `TORUS`, `FREEFORM_SURFACE`, `COMPLEX_SURFACE`;
- `edges`: линии, окружности и другие распознанные ребра.

Пример запуска:

```bash
python parser/parser.py
```

Если код будет расширен CLI-аргументами для STEP, ожидаемый сценарий такой:

```bash
python parser/parser.py --input path/to/model.stp --output parser/drafting_data.json
```

## `drawing_config_generator.py`

`drawing_config_generator.py` не читает STEP и не использует OpenCascade. Он работает только с готовым `drafting_data.json` и строит высокоуровневый `drawing_config.json` для будущего C#-агента.

Генератор создает:

- `bbox_3d`;
- виды `TOP`, `FRONT`, `LEFT`;
- 2D bbox, контуры, точки привязки и заметки для каждого вида;
- 3D features для отверстий и внешних цилиндров;
- проекции отверстий и цилиндров;
- габаритные размеры, диаметры отверстий и center marks;
- подсказки `generation_hints_for_csharp`.

Правила проекций:

```text
TOP:   [x, y, z] -> [x, y]
FRONT: [x, y, z] -> [x, z]
LEFT:  [x, y, z] -> [y, z]
```

Круговая проекция цилиндра создается только на виде, где ось цилиндра почти параллельна направлению взгляда:

```text
TOP   смотрит вдоль Z
FRONT смотрит вдоль Y
LEFT  смотрит вдоль X
```

Если ось не параллельна виду, генератор создает `CENTERLINE`/скрытую проекцию и добавляет `notes`, чтобы C#-агент не рисовал видимую окружность.

## `generate_drawing_config.py`

`generate_drawing_config.py` - CLI-обертка над генератором.

Запуск с путями по умолчанию:

```bash
python parser/generate_drawing_config.py
```

По умолчанию команда читает:

```text
parser/drafting_data.json
```

и пишет:

```text
parser/drawing_config.json
```

Явные пути:

```bash
python parser/generate_drawing_config.py --input parser/drafting_data.json --output parser/drawing_config.json
```

После успешной генерации выводится сообщение вида:

```text
Drawing config saved to parser/drawing_config.json
```

## `drawing_config.json`

`drawing_config.json` - это готовая инструкция для C#-агента чертежей. Агент не должен читать STEP, пересчитывать 3D-геометрию или самостоятельно выбирать проекции. Он должен рисовать по подготовленным 2D-координатам, features, dimensions и notes.

Минимальная структура:

```json
{
  "schema_version": "1.0",
  "source": "drafting_data.json",
  "units": "mm",
  "part_type": "ROUND_PLATE_WITH_HOLES",
  "bbox_3d": {},
  "views": {
    "TOP": {},
    "FRONT": {},
    "LEFT": {}
  },
  "features_3d": [],
  "generation_hints_for_csharp": {}
}
```

## Ограничения текущей версии

- Отверстия определяются эвристикой: `face.type == "CYLINDER"` и `face.params.orientation == "REVERSED"`.
- Внешний цилиндр определяется как `CYLINDER` с `orientation == "FORWARD"`.
- Круглые проекции цилиндров выбираются по направлению оси, а не рисуются на всех видах.
- Диаметр отверстия ставится только на виде, где отверстие видно как окружность; если такой вид определить нельзя, используется fallback на `TOP` с warning в `notes`.
- Круглый `TOP` outline не выбирается только по `bbox.dx == bbox.dy`; нужен тип круглой детали или внешний `FORWARD`-цилиндр.
- Сложные NURBS/freeform поверхности пока не превращаются в точные чертежные контуры.

## Окружение

Для `parser.py` нужен `pythonocc-core`. Прослойка `drawing_config_generator.py` и тесты генератора не зависят от OpenCascade и работают на искусственных словарях/JSON.

Пример conda-окружения:

```yaml
name: cad_ml
channels:
  - conda-forge
  - defaults
dependencies:
  - python=3.10
  - numpy
  - pythonocc-core=7.9.3
  - pyvista
  - trimesh
  - pandas
  - tqdm
  - pip
  - pip:
      - ezdxf
```
