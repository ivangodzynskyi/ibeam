"""
================================================================
  Генератор меш-сітки меандру (gmsh) → ЛІРА САПР .sli
================================================================

Будує 2D меш для контуру в площині XOZ:
  - верхня грань — крива меандру (лінії + філлети)
  - права грань  — від кінця меандру вниз на h2
  - нижня грань  — пряма від (length, -height-h2) до (0, -h1)
  - ліва грань   — пряма від (0, -h1) до (0, 0)

ВИКОРИСТАННЯ:
  python meander_gmsh_sli.py
  python meander_gmsh_sli.py --quads
  python meander_gmsh_sli.py --mesh-size 0.02
"""

import argparse
import math
from typing import List

import gmsh

from config import Config
from meander_generator import MeanderGenerator, Point, Fillet
from ibeam_sli_generator import Node, Quad
from sli_writer import write_plate_sli


def generate(cfg: Config, mesh_size: float = 0.05,
             use_quads: bool = False, thickness: float = 0.01,
             E: float = 2.02027e7, nu: float = 0.28, rho: float = 7850.0,
             name: str = "meander", output: str = "meander.sli"):
    """Будує меш контуру з меандром через gmsh, зберігає .sli."""

    # ── Генеруємо криву меандру ───────────────────────────────
    items = MeanderGenerator.generate_with_fillets(
        length=cfg.length, height=cfg.height,
        periods=cfg.periods, radius=cfg.radius,
        k_angle=cfg.k_angle,
    )

    # Остання точка меандру
    last_meander = items[-1]
    last_x = last_meander.x if isinstance(last_meander, Point) else last_meander.p2.x
    last_y = last_meander.y if isinstance(last_meander, Point) else last_meander.p2.y

    gmsh.initialize()
    gmsh.option.setNumber("General.Terminal", 0)
    gmsh.model.add("meander")
    geo = gmsh.model.geo

    # ── Допоміжна функція: створити gmsh-точку ───────────────
    point_cache = {}

    def add_pt(x: float, z: float) -> int:
        """Створює gmsh-точку в площині XOZ (y=0)."""
        key = (round(x, 10), round(z, 10))
        if key not in point_cache:
            point_cache[key] = geo.addPoint(x, 0, z, mesh_size)
        return point_cache[key]

    # ── Будуємо криві меандру ─────────────────────────────────
    curves = []
    prev_pt_id = None
    center_pt_ids = set()  # точки-центри дуг (не включати в меш)

    for i, item in enumerate(items):
        if isinstance(item, Point):
            pt_id = add_pt(item.x, item.y)
            if prev_pt_id is not None and prev_pt_id != pt_id:
                curves.append(geo.addLine(prev_pt_id, pt_id))
            prev_pt_id = pt_id
        elif isinstance(item, Fillet):
            p1_id = add_pt(item.p1.x, item.p1.y)
            p2_id = add_pt(item.p2.x, item.p2.y)
            pc_id = add_pt(item.p_center.x, item.p_center.y)
            center_pt_ids.add(pc_id)

            # Лінія від попередньої точки до початку дуги
            if prev_pt_id is not None and prev_pt_id != p1_id:
                curves.append(geo.addLine(prev_pt_id, p1_id))

            # Дуга філлету
            curves.append(geo.addCircleArc(p1_id, pc_id, p2_id))
            prev_pt_id = p2_id

    # ── Замикаючі лінії ──────────────────────────────────────
    # Кінець меандру → (length, -height - h2)
    p_br = add_pt(cfg.length, last_y - cfg.h2)
    curves.append(geo.addLine(prev_pt_id, p_br))

    # → (0, -h1)  — edgeLine (нижня грань стінки)
    p_bl = add_pt(0, -cfg.h1)
    edge_line_tag = geo.addLine(p_br, p_bl)
    curves.append(edge_line_tag)

    # → (0, 0) — замикання
    p_start = add_pt(0, 0)
    curves.append(geo.addLine(p_bl, p_start))

    # ── Поверхня ─────────────────────────────────────────────
    loop = geo.addCurveLoop(curves)
    geo.addPlaneSurface([loop])
    geo.synchronize()

    if use_quads:
        gmsh.option.setNumber("Mesh.RecombineAll", 1)

    gmsh.model.mesh.generate(2)

    # ── Витягуємо вузли edgeLine (до finalize!) ────────────────
    edge_tags_raw, edge_crds_raw, _ = gmsh.model.mesh.getNodes(
        dim=1, tag=abs(edge_line_tag), includeBoundary=True,
    )
    edge_pts = []
    for i, tag in enumerate(edge_tags_raw):
        ex = round(edge_crds_raw[3 * i], 8)
        ez = round(edge_crds_raw[3 * i + 2], 8)
        edge_pts.append((ex, ez, int(tag)))
    edge_pts.sort(key=lambda p: p[0])  # сортуємо по X

    # ── Витягуємо вузли (без центрів дуг) ────────────────────
    node_tags, coords, _ = gmsh.model.mesh.getNodes()
    nodes: List[Node] = []
    tag_to_id = {}
    nid = 0
    for i, tag in enumerate(node_tags):
        if int(tag) in center_pt_ids:
            continue
        nid += 1
        tag_to_id[int(tag)] = nid
        x = round(coords[3 * i], 8)
        y = round(coords[3 * i + 1], 8)
        z = round(coords[3 * i + 2], 8)
        nodes.append(Node(nid, x, y, z))

    # ── Витягуємо елементи (dim=2) ───────────────────────────
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

    # ── Полка: меш-сітка вздовж edgeLine (Y-direction) ─────────
    flange_quad_count = 0
    if cfg.nb > 0 and cfg.bf > 0:
        dy = cfg.bf / (2 * cfg.nb)
        n_edge = len(edge_pts)

        # edge_grid[(i, j)] → node_id
        # i — індекс вздовж edgeLine, j — індекс по Y
        # j = 0 → y = -bf/2,  j = nb → y = 0,  j = 2*nb → y = bf/2
        edge_grid = {}

        for i, (ex, ez, gmsh_tag) in enumerate(edge_pts):
            # Вузол на y=0 вже існує (стінка)
            edge_grid[(i, cfg.nb)] = tag_to_id[gmsh_tag]

            # Додатній бік Y (від 0 до bf/2)
            for j in range(1, cfg.nb + 1):
                y_val = round(j * dy, 8)
                nid += 1
                nodes.append(Node(nid, ex, y_val, ez))
                edge_grid[(i, cfg.nb + j)] = nid

            # Від'ємний бік Y (від 0 до -bf/2)
            for j in range(1, cfg.nb + 1):
                y_val = round(-j * dy, 8)
                nid += 1
                nodes.append(Node(nid, ex, y_val, ez))
                edge_grid[(i, cfg.nb - j)] = nid

        # Прямокутні елементи полки
        for i in range(n_edge - 1):
            for j in range(2 * cfg.nb):
                n1 = edge_grid[(i, j)]
                n2 = edge_grid[(i + 1, j)]
                n3 = edge_grid[(i + 1, j + 1)]
                n4 = edge_grid[(i, j + 1)]
                elements.append(Quad(eid, n1, n2, n3, n4, mat=2))
                eid += 1
                flange_quad_count += 1

    # ── Записуємо .sli ───────────────────────────────────────
    materials = [
        {"num": 1, "H": thickness, "F": nu, "E": E, "Ro": rho},
        {"num": 2, "H": thickness, "F": nu, "E": E, "Ro": rho},
    ]

    filepath = output if output.endswith('.sli') else output + '.sli'
    write_plate_sli(name, nodes, elements, materials, filepath)

    print(f"\n{'=' * 60}")
    print(f"  Меандр: {name}")
    print(f"{'=' * 60}")
    print(f"  length={cfg.length}, height={cfg.height}, "
          f"periods={cfg.periods}, radius={cfg.radius}")
    print(f"  h1={cfg.h1}, h2={cfg.h2}, bf={cfg.bf}, nb={cfg.nb}")
    print(f"  Крок сітки : {mesh_size} м")
    print(f"  Вузлів     : {len(nodes)}")
    print(f"  Стінка     : {quad_count + tri_count} "
          f"(quad={quad_count}, tri={tri_count})")
    print(f"  Полка      : {flange_quad_count} quad")
    print(f"  Всього ел. : {len(elements)}")
    print(f"  Файл       : {filepath}")

    return filepath


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Генератор меш-сітки меандру (gmsh) → ЛІРА САПР .sli"
    )
    parser.add_argument("--mesh-size", type=float, default=0.05,
                        help="Розмір елемента, м (default: 0.05)")
    parser.add_argument("--quads", action="store_true",
                        help="Рекомбінувати трикутники в квади")
    parser.add_argument("--thickness", type=float, default=0.01,
                        help="Товщина, м (default: 0.01)")
    parser.add_argument("--name", type=str, default="meander",
                        help="Назва моделі (default: meander)")
    parser.add_argument("--output", type=str, default="meander.sli",
                        help="Вихідний файл (default: meander.sli)")

    args = parser.parse_args()
    cfg = Config()
    generate(cfg, mesh_size=args.mesh_size, use_quads=args.quads,
             thickness=args.thickness, name=args.name, output=args.output)
