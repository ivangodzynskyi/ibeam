"""
================================================================
  Генератор плити (gmsh) → ЛІРА САПР .sli
================================================================

Генерує 2D плиту за допомогою gmsh (геометрія як у mesh_test_gmsh.py:
3 прямі лінії + сплайн) та записує у .sli формат.
Включає вертикальні ребра жорсткості на опорах та всередині прольоту.

Підтримує четирикутні (quad) та трикутні (triangle) елементи.

МАТЕРІАЛИ:
  1 — основна плита (товщина: --thickness)
  2 — ребра жорсткості (товщина: --rib-thickness)

ВИКОРИСТАННЯ:
  python plate_gmsh_sli.py                            # за замовч.
  python plate_gmsh_sli.py --quads                    # рекомбінація в квади
  python plate_gmsh_sli.py --width 2 --height 1.5
  python plate_gmsh_sli.py --mesh-size 0.05           # дрібніша сітка
  python plate_gmsh_sli.py --thickness 0.008 --name my_plate
  python plate_gmsh_sli.py --rib-count 3 --rib-width 0.15 --rib-thickness 0.01
    # 3 внутрішніх ребра + 2 опорних на краях (x=0, x=width)

ІМПОРТ У ЛІРА:
  Файл → Відкрити / Імпорт → вибрати *.sli
"""

import argparse
from typing import List

import gmsh

from ibeam_sli_generator import Node, Quad
from sli_writer import write_plate_sli


def generate(width: float, height: float, mesh_size: float,
             use_quads: bool, thickness: float, E: float,
             nu: float, rho: float, name: str, output: str,
             rib_thickness: float = 0.01, rib_width: float = 0.1,
             rib_count: int = 2):
    """Будує сітку плити через gmsh, зберігає .sli.

    rib_thickness — товщина ребра жорсткості (м)
    rib_width    — ширина ребра жорсткості у напрямку Y (м)
    rib_count    — кількість внутрішніх ребер (крім опорних на краях)
    """

    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.add("plate")
    geo = gmsh.model.geo

    # ── Геометрія (як mesh_test_gmsh.py) ──────────────────────
    p1 = geo.addPoint(0, 0, 0, mesh_size)
    p2 = geo.addPoint(width, 0, 0, mesh_size)
    p3 = geo.addPoint(width, height, 0, mesh_size)
    p4 = geo.addPoint(0, height, 0, mesh_size)
    p5 = geo.addPoint(0.5, 2*height/3, 0, mesh_size)
    p6 = geo.addPoint(0.5, height/3, 0, mesh_size)

    l1 = geo.addLine(p1, p2)
    l2 = geo.addLine(p2, p3)
    l3 = geo.addLine(p3, p4)
    curve = geo.addSpline([p4, p5, p6, p1])

    loop = geo.addCurveLoop([l1, l2, l3, curve])
    geo.addPlaneSurface([loop])
    geo.synchronize()

    if use_quads:
        gmsh.option.setNumber("Mesh.RecombineAll", 1)

    gmsh.model.mesh.generate(2)

    # ── Витягуємо вузли ───────────────────────────────────────
    node_tags, coords, _ = gmsh.model.mesh.getNodes()
    nodes: List[Node] = []
    tag_to_id = {}
    for i, tag in enumerate(node_tags):
        nid = i + 1
        tag_to_id[int(tag)] = nid
        x = round(coords[3 * i], 8)
        y = round(coords[3 * i + 1], 8)
        z = round(coords[3 * i + 2], 8)
        nodes.append(Node(nid, x, y, z))

    # ── Витягуємо елементи (dim=2) ────────────────────────────
    elem_types, elem_tags_list, elem_node_tags_list = \
        gmsh.model.mesh.getElements(dim=2)

    elements: List[Quad] = []
    eid = 1
    tri_count = 0
    quad_count = 0

    for et, tags, ntags in zip(elem_types, elem_tags_list,
                               elem_node_tags_list):
        if et == 2:  # 3-node triangle
            for i in range(len(tags)):
                n1 = tag_to_id[int(ntags[i * 3])]
                n2 = tag_to_id[int(ntags[i * 3 + 1])]
                n3 = tag_to_id[int(ntags[i * 3 + 2])]
                elements.append(Quad(eid, n1, n2, n3, 0, mat=1))
                eid += 1
                tri_count += 1
        elif et == 3:  # 4-node quad
            for i in range(len(tags)):
                n1 = tag_to_id[int(ntags[i * 4])]
                n2 = tag_to_id[int(ntags[i * 4 + 1])]
                n3 = tag_to_id[int(ntags[i * 4 + 2])]
                n4 = tag_to_id[int(ntags[i * 4 + 3])]
                elements.append(Quad(eid, n1, n2, n3, n4, mat=1))
                eid += 1
                quad_count += 1

    gmsh.finalize()

    # ── Ребра жорсткості (опорні та внутрішні) ───────────────
    rib_elem_count = 0
    rib_x_positions = [0.0, width]  # опорні ребра на краях

    # Додати внутрішні ребра рівномірно по х
    if rib_count > 0 and width > 0:
        dx_internal = width / (rib_count + 1)
        for i in range(1, rib_count + 1):
            rib_x_positions.insert(-1, i * dx_internal)

    rib_x_tol = 1e-6
    dy_rib_half = rib_width / 2

    for rib_x in rib_x_positions:
        # 1. Зібрати всі Y-значення вузлів на лінії x = rib_x
        y_axis = {}  # round(y,8) → node_id
        for node in nodes:
            if abs(node.x - rib_x) < rib_x_tol:
                y_axis[round(node.y, 8)] = node.id

        y_vals = sorted(y_axis.keys())
        if len(y_vals) < 2:
            continue  # ребро повинно мати щонайменше 2 вузли

        # 2. Розбити проміжки для дрібнішої сітки
        extra_y = []
        for k in range(len(y_vals) - 1):
            y1, y2 = y_vals[k], y_vals[k + 1]
            gap = y2 - y1
            n_sub = max(2, round(gap / mesh_size))
            dy = gap / n_sub
            for s in range(1, n_sub):
                extra_y.append(round(y1 + s * dy, 8))

        for yv in extra_y:
            yk = round(yv, 8)
            if yk not in y_axis:
                nid += 1
                nodes.append(Node(nid, rib_x, yv, 0.0))
                y_axis[yk] = nid

        y_vals = sorted(y_axis.keys())

        # 3. Побудувати lookup для вузлів поблизу ребра (центр ± rib_width/2)
        rib_lookup = {}  # round(y,6) → node_id
        for node in nodes:
            if (abs(node.x - rib_x) < rib_x_tol and
                abs(node.y) <= dy_rib_half + rib_x_tol):
                key = round(node.y, 6)
                rib_lookup[key] = node.id

        # 4. Побудувати сітку ребра
        rib_grid = {}
        nb_rib = max(1, round(rib_width / (2 * mesh_size)))
        dy_step = rib_width / (2 * nb_rib)

        for iy, yv in enumerate(y_vals):
            for iy_dir in range(-nb_rib, nb_rib + 1):
                y_rib = round(yv + iy_dir * dy_step, 8)
                key = round(y_rib, 6)

                if key in rib_lookup:
                    rib_grid[(iy, iy_dir)] = rib_lookup[key]
                else:
                    nid += 1
                    nodes.append(Node(nid, rib_x, y_rib, 0.0))
                    rib_grid[(iy, iy_dir)] = nid

        # 5. Створити елементи ребра (матеріал 2)
        for iy in range(len(y_vals) - 1):
            for iy_dir in range(-nb_rib, nb_rib):
                n1 = rib_grid[(iy, iy_dir)]
                n2 = rib_grid[(iy + 1, iy_dir)]
                n3 = rib_grid[(iy + 1, iy_dir + 1)]
                n4 = rib_grid[(iy, iy_dir + 1)]
                elements.append(Quad(eid, n1, n2, n3, n4, mat=2))
                eid += 1
                rib_elem_count += 1

    # ── Записуємо .sli ────────────────────────────────────────
    materials = [
        {"num": 1, "H": thickness, "F": nu, "E": E, "Ro": rho},
        {"num": 2, "H": rib_thickness, "F": nu, "E": E, "Ro": rho}
    ]

    filepath = output if output.endswith('.sli') else output + '.sli'
    write_plate_sli(name, nodes, elements, materials, filepath)

    print(f"\n{'=' * 60}")
    print(f"  Плита: {name}")
    print(f"{'=' * 60}")
    print(f"  Розміри    : {width} x {height} м")
    print(f"  Крок сітки : {mesh_size} м")
    print(f"  Товщина    : {thickness * 1000:.1f} мм")
    print(f"  Ребра      : ширина={rib_width} м, товщина={rib_thickness*1000:.1f} мм, "
          f"внутрішніх={rib_count}")
    print(f"  Вузлів     : {len(nodes)}")
    print(f"  Елементів  : {len(elements)} "
          f"(плита: quad={quad_count}, tri={tri_count}, ребра={rib_elem_count})")
    print(f"  Файл       : {filepath}")

    return filepath


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Генератор плити (gmsh) → ЛІРА САПР .sli"
    )
    parser.add_argument("--width", type=float, default=1.0,
                        help="Ширина плити, м (default: 1.0)")
    parser.add_argument("--height", type=float, default=1.0,
                        help="Висота плити, м (default: 1.0)")
    parser.add_argument("--mesh-size", type=float, default=0.1,
                        help="Розмір елемента, м (default: 0.1)")
    parser.add_argument("--quads", action="store_true",
                        help="Рекомбінувати трикутники в квади")
    parser.add_argument("--thickness", type=float, default=0.01,
                        help="Товщина плити, м (default: 0.01)")
    parser.add_argument("--E", type=float, default=2.02027e7,
                        help="Модуль пружності, кН/м² (default: 2.02027e7)")
    parser.add_argument("--nu", type=float, default=0.28,
                        help="Коефіцієнт Пуассона (default: 0.28)")
    parser.add_argument("--rho", type=float, default=7850.0,
                        help="Щільність, кг/м³ (default: 7850)")
    parser.add_argument("--name", type=str, default="plate",
                        help="Назва моделі (default: plate)")
    parser.add_argument("--output", type=str, default="plate.sli",
                        help="Вихідний файл (default: plate.sli)")
    parser.add_argument("--rib-thickness", type=float, default=0.01,
                        help="Товщина ребра жорсткості, м (default: 0.01)")
    parser.add_argument("--rib-width", type=float, default=0.1,
                        help="Ширина ребра жорсткості по Y, м (default: 0.1)")
    parser.add_argument("--rib-count", type=int, default=2,
                        help="Кількість внутрішніх ребер (крім опорних, default: 2)")

    args = parser.parse_args()
    generate(
        width=args.width, height=args.height, mesh_size=args.mesh_size,
        use_quads=args.quads, thickness=args.thickness, E=args.E,
        nu=args.nu, rho=args.rho, name=args.name, output=args.output,
        rib_thickness=args.rib_thickness, rib_width=args.rib_width,
        rib_count=args.rib_count,
    )
