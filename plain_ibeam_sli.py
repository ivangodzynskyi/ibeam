"""
================================================================
  Генератор суцільної двотаврової балки → ЛІРА САПР .sli
================================================================

Будує пластинчату модель шарнірно-опертої сортаментної балки
(без перфорації) за параметрами з config.py:
  H  — висота сортаментної балки, мм
  Bf — ширина полиці, мм
  Tw — товщина стінки, мм
  Tb — товщина полиць, мм
  Lb — довжина балки, мм
  nb — кількість проміжків на кожній стороні полиці

Система координат (як у ibeam_gmsh_sli.py):
  X — вздовж балки (від -L/2 до +L/2, центр прольоту при x=0)
  Y — ширина полиці (від -bf/2 до +bf/2)
  Z — висота (z=0 — середина висоти перерізу)

Геометрія (серединні площини пластин):
  - полиці на z = ±zf, де zf = (H - Tb)/2000
  - стінка y=0, z від -zf до +zf

Опори та навантаження — точно як у ibeam_gmsh_sli.py:
  - ліва опора  (x=-L/2, z=-zf): закріплення X,Y,Z
  - права опора (x=+L/2, z=-zf): закріплення Y,Z
  - сила -10 кН по Z у вузлі (0, 0, +zf), завантаження 1

ВИКОРИСТАННЯ:
  python plain_ibeam_sli.py
  python plain_ibeam_sli.py --name my_beam --output my_beam.sli

ІМПОРТ У ЛІРА:
  Файл → Відкрити / Імпорт → вибрати *.sli
"""

import argparse
from typing import Dict, List, Tuple

from config import Config
from ibeam_sli_generator import Node, Quad
from sli_writer import write_plate_sli


def generate(cfg: Config,
             E: float = 2.02027e7, nu: float = 0.28, rho: float = 7.8500,
             name: str = "plain_ibeam", output: str = "plain_ibeam.sli"):
    """Будує структуровану сітку суцільної балки, зберігає .sli."""

    L = cfg.Lb / 1000                   # повна довжина балки, м
    bf = cfg.bf                         # ширина полиці, м
    zf = (cfg.H - cfg.Tb) / 2000        # серединна площина полиці, м
    hw = 2 * zf                         # висота стінки між полицями, м

    # ── Розбивка сітки за nb ──────────────────────────────────
    dy = bf / (2 * cfg.nb)              # крок по ширині полиці
    nx = max(2, round(L / dy))          # проміжків по довжині
    if nx % 2:
        nx += 1                         # парне → ряд вузлів при x=0
    nz = max(1, round(hw / dy))         # проміжків по висоті стінки

    x_cuts = [round(-L / 2 + L * i / nx, 8) for i in range(nx + 1)]
    z_cuts = [round(-zf + hw * k / nz, 8) for k in range(nz + 1)]
    y_cuts = [round(-bf / 2 + dy * j, 8) for j in range(2 * cfg.nb + 1)]

    nodes: List[Node] = []
    elements: List[Quad] = []
    nid = 0
    eid = 1

    def add_node(x: float, y: float, z: float) -> int:
        nonlocal nid
        nid += 1
        nodes.append(Node(nid, x, y, z))
        return nid

    # ── Стінка (y=0): (nx+1) × (nz+1) вузлів ──────────────────
    web_grid: Dict[Tuple[int, int], int] = {}   # (i_x, k_z) → node_id
    for i, x in enumerate(x_cuts):
        for k, z in enumerate(z_cuts):
            web_grid[(i, k)] = add_node(x, 0.0, z)

    web_count = 0
    for i in range(nx):
        for k in range(nz):
            n1 = web_grid[(i,     k)]
            n2 = web_grid[(i + 1, k)]
            n3 = web_grid[(i + 1, k + 1)]
            n4 = web_grid[(i,     k + 1)]
            elements.append(Quad(eid, n1, n2, n3, n4, mat=1))
            eid += 1
            web_count += 1

    # ── Полиці (z=±zf): спільні вузли зі стінкою при y=0 ──────
    flange_count = 0
    for k_web, z in [(nz, zf), (0, -zf)]:
        fl_grid: Dict[Tuple[int, int], int] = {}   # (i_x, j_y) → node_id
        for i, x in enumerate(x_cuts):
            for j, y in enumerate(y_cuts):
                if j == cfg.nb:  # y=0 → вузол стінки
                    fl_grid[(i, j)] = web_grid[(i, k_web)]
                else:
                    fl_grid[(i, j)] = add_node(x, y, z)

        for i in range(nx):
            for j in range(2 * cfg.nb):
                n1 = fl_grid[(i,     j)]
                n2 = fl_grid[(i + 1, j)]
                n3 = fl_grid[(i + 1, j + 1)]
                n4 = fl_grid[(i,     j + 1)]
                elements.append(Quad(eid, n1, n2, n3, n4, mat=2))
                eid += 1
                flange_count += 1

    # ── Вертикальні ребра жорсткості ────────────────────────
    rib_elem_count = 0
    support_rib_elem_count = 0
    rib_x_tol = 1e-6
    rib_y_tol = 1e-6

    # Середнє ребро (x=0, площина YOZ)
    z_axis = {}  # round(z,8) → node_id
    for node in nodes:
        if abs(node.x) < rib_x_tol and abs(node.y) < rib_y_tol:
            z_axis[round(node.z, 8)] = node.id

    if z_axis:
        z_vals = sorted(z_axis.keys())
        rib_lookup = {}  # (y_round, z_round) → node_id
        for node in nodes:
            if abs(node.x) < rib_x_tol:
                key = (round(node.y, 6), round(node.z, 6))
                rib_lookup[key] = node.id

        dy = bf / (2 * cfg.nb)
        rib_grid = {}
        for iz, zv in enumerate(z_vals):
            for iy in range(-cfg.nb, cfg.nb + 1):
                y_val = round(iy * dy, 8)
                key = (round(y_val, 6), round(zv, 6))
                if key in rib_lookup:
                    rib_grid[(iz, iy)] = rib_lookup[key]
                else:
                    nid += 1
                    nodes.append(Node(nid, 0.0, y_val, zv))
                    rib_lookup[key] = nid
                    rib_grid[(iz, iy)] = nid

        for iz in range(len(z_vals) - 1):
            for iy in range(-cfg.nb, cfg.nb):
                n1 = rib_grid[(iz, iy)]
                n2 = rib_grid[(iz + 1, iy)]
                n3 = rib_grid[(iz + 1, iy + 1)]
                n4 = rib_grid[(iz, iy + 1)]
                elements.append(Quad(eid, n1, n2, n3, n4, mat=1))
                eid += 1
                rib_elem_count += 1

    # Опорні ребра (x=±L/2, площина YOZ)
    for support_x in [-L / 2, L / 2]:
        z_support_axis = {}  # round(z,8) → node_id
        for node in nodes:
            if abs(node.x - support_x) < rib_x_tol and abs(node.y) < rib_y_tol:
                zk = round(node.z, 8)
                if zk not in z_support_axis:
                    z_support_axis[zk] = node.id

        if z_support_axis:
            z_support_vals = sorted(z_support_axis.keys())
            support_lookup = {}  # (y_round, z_round) → node_id
            for node in nodes:
                if abs(node.x - support_x) < rib_x_tol:
                    key = (round(node.y, 6), round(node.z, 6))
                    support_lookup[key] = node.id

            support_grid = {}
            for iz, zv in enumerate(z_support_vals):
                for iy in range(-cfg.nb, cfg.nb + 1):
                    y_val = round(iy * dy, 8)
                    key = (round(y_val, 6), round(zv, 6))
                    if key in support_lookup:
                        support_grid[(iz, iy)] = support_lookup[key]
                    else:
                        nid += 1
                        nodes.append(Node(nid, support_x, y_val, zv))
                        support_lookup[key] = nid
                        support_grid[(iz, iy)] = nid

            for iz in range(len(z_support_vals) - 1):
                for iy in range(-cfg.nb, cfg.nb):
                    n1 = support_grid[(iz, iy)]
                    n2 = support_grid[(iz + 1, iy)]
                    n3 = support_grid[(iz + 1, iy + 1)]
                    n4 = support_grid[(iz, iy + 1)]
                    elements.append(Quad(eid, n1, n2, n3, n4, mat=1))
                    eid += 1
                    support_rib_elem_count += 1

    # ── В'язі (опори) ────────────────────────────────────────
    restrictions = []
    tol = 1e-6
    for node in nodes:
        # Ліва опора: x = -L/2, z = -zf → закріплення X,Y,Z
        if abs(node.x - (-L / 2)) < tol and abs(node.z - (-zf)) < tol:
            restrictions += [(node.id, 1), (node.id, 2), (node.id, 3)]
        # Права опора: x = L/2, z = -zf → закріплення Y,Z
        elif abs(node.x - L / 2) < tol and abs(node.z - (-zf)) < tol:
            restrictions += [(node.id, 2), (node.id, 3)]

    # ── Навантаження ──────────────────────────────────────────
    #    Розподілити силу -10 кН по 4 прилеглим елементам верхнього поясу
    loads = []
    distributed_loads = []  # (elem_id, load_value_per_m2)

    # Знайти вузол (0, 0, zf)
    target_node_id = None
    for node in nodes:
        if abs(node.x) < tol and abs(node.y) < tol and abs(node.z - zf) < tol:
            target_node_id = node.id
            break

    if target_node_id is not None:
        # Знайти всі елементи, що містять цей вузол (матеріал 2 = верхній поясу)
        adjacent_elements = []
        for elem in elements:
            if elem.mat == 2:  # верхній пояс
                elem_nodes = [elem.n1, elem.n2, elem.n3]
                if elem.n4 != 0:
                    elem_nodes.append(elem.n4)
                if target_node_id in elem_nodes:
                    adjacent_elements.append(elem)

        # Обчислити площу елементів
        node_map = {n.id: n for n in nodes}
        total_area = 0.0
        for elem in adjacent_elements:
            elem_nodes_list = [elem.n1, elem.n2, elem.n3]
            if elem.n4 != 0:
                elem_nodes_list.append(elem.n4)

            # Отримати координати вузлів
            node_coords = [node_map[nid] for nid in elem_nodes_list]

            # Обчислити площу як добуток розмірів по X та Y
            xs = [n.x for n in node_coords]
            ys = [n.y for n in node_coords]
            dx = max(xs) - min(xs)
            dy = max(ys) - min(ys)
            area = dx * dy
            total_area += area

        # Розділити силу на площу (отримати кН/м²)
        if total_area > 0:
            load_per_area = -100.0 / total_area  # кН/м²
            distributed_loads = [(elem.id, load_per_area) for elem in adjacent_elements]

    # ── Записуємо .sli ───────────────────────────────────────
    materials = [
        {"num": 1, "H": cfg.tw, "F": nu, "E": E, "Ro": rho},
        {"num": 2, "H": cfg.tb, "F": nu, "E": E, "Ro": rho},
    ]

    filepath = output if output.endswith('.sli') else output + '.sli'
    write_plate_sli(name, nodes, elements, materials, filepath,
                    restrictions=restrictions, loads=loads,
                    distributed_loads=distributed_loads)

    print(f"\n{'=' * 60}")
    print(f"  Plain I-beam: {name}")
    print(f"{'=' * 60}")
    print(f"  L={L} м, H={cfg.H} мм, Bf={cfg.Bf} мм, "
          f"Tw={cfg.Tw} мм, Tb={cfg.Tb} мм")
    print(f"  zf={zf} м, hw={hw} м")
    print(f"  Сітка      : nx={nx}, nz={nz}, nb={cfg.nb} (dy={dy} м)")
    print(f"  Вузлів     : {len(nodes)}")
    print(f"  Стінка     : {web_count} quad")
    print(f"  Полиці     : {flange_count} quad")
    print(f"  Mid rib    : {rib_elem_count} quad")
    print(f"  Support ribs: {support_rib_elem_count} quad")
    print(f"  Constraints: {len(restrictions)}")
    print(f"  Loads      : {len(loads)}")
    print(f"  Distributed loads: {len(distributed_loads)}")
    print(f"  Total el.  : {len(elements)}")
    print(f"  File       : {filepath}")

    return filepath


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Генератор суцільної двотаврової балки → ЛІРА САПР .sli"
    )
    parser.add_argument("--name", type=str, default="plain_ibeam",
                        help="Назва моделі (default: plain_ibeam)")
    parser.add_argument("--output", type=str, default="plain_ibeam.sli",
                        help="Вихідний файл (default: plain_ibeam.sli)")

    args = parser.parse_args()
    generate(Config(), name=args.name, output=args.output)
