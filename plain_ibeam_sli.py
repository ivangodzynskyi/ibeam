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
             E: float = 2.02027e7, nu: float = 0.28, rho: float = 7850.0,
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
    #    Вертикальна сила -10 кН у вузлі (0, 0, zf)
    loads = []
    for node in nodes:
        if abs(node.x) < tol and abs(node.y) < tol and abs(node.z - zf) < tol:
            loads.append((node.id, 3, -10.0, 1))
            break

    # ── Записуємо .sli ───────────────────────────────────────
    materials = [
        {"num": 1, "H": cfg.tw, "F": nu, "E": E, "Ro": rho},
        {"num": 2, "H": cfg.tb, "F": nu, "E": E, "Ro": rho},
    ]

    filepath = output if output.endswith('.sli') else output + '.sli'
    write_plate_sli(name, nodes, elements, materials, filepath,
                    restrictions=restrictions, loads=loads)

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
    print(f"  Constraints: {len(restrictions)}")
    print(f"  Loads      : {len(loads)}")
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
