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


def _parse_hole_numbers(val) -> List[int]:
    """Розбирає fillHolesNumbers ("1,2,5" | [1,2,5] | "") у список int."""
    if not val:
        return []
    if isinstance(val, (list, tuple)):
        return [int(x) for x in val]
    return [int(s) for s in str(val).split(',') if s.strip()]


def generate(cfg: Config, mesh_size: float = 0.05,
             use_quads: bool = False,
             E: float = 2.02027e7, nu: float = 0.28, rho: float = 7850.0,
             name: str = "meander", output: str = "meander.sli",
             fill_holes=None):
    """Будує меш контуру з меандром через gmsh, зберігає .sli.

    fill_holes — номери отворів для заповнення (рядок "1,2,5" або список).
    Якщо None — береться cfg.fillHolesNumbers. Нумерація йде від краю
    півбалки (x=length) до центру (x=0); напівзападина біля x=0 — останній
    (найбільший) номер.
    """

    requested_holes = _parse_hole_numbers(
        fill_holes if fill_holes is not None else cfg.fillHolesNumbers
    )

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
    arc_curves = []  # теги дуг для setTransfiniteCurve
    prev_pt_id = None
    center_pt_ids = set()  # точки-центри дуг (не включати в меш)

    # Трекінг точок та кривих меандру (для побудови отворів).
    # meander_pts[k] = (pt_id, x, z);  meander_curves[k] з'єднує точки k→k+1
    meander_pts = []
    meander_curves = []

    def _track(pt_id, x, z):
        meander_pts.append((pt_id, round(x, 10), round(z, 10)))

    for i, item in enumerate(items):
        if isinstance(item, Point):
            pt_id = add_pt(item.x, item.y)
            if prev_pt_id is None:
                _track(pt_id, item.x, item.y)          # перша точка меандру
            elif prev_pt_id != pt_id:
                c = geo.addLine(prev_pt_id, pt_id)
                curves.append(c)
                meander_curves.append(c)
                _track(pt_id, item.x, item.y)
            prev_pt_id = pt_id
        elif isinstance(item, Fillet):
            p1_id = add_pt(item.p1.x, item.p1.y)
            p2_id = add_pt(item.p2.x, item.p2.y)
            pc_id = add_pt(item.p_center.x, item.p_center.y)
            center_pt_ids.add(pc_id)

            # Лінія від попередньої точки до початку дуги
            if prev_pt_id is not None and prev_pt_id != p1_id:
                c = geo.addLine(prev_pt_id, p1_id)
                curves.append(c)
                meander_curves.append(c)
                _track(p1_id, item.p1.x, item.p1.y)

            # Дуга філлету
            arc_tag = geo.addCircleArc(p1_id, pc_id, p2_id)
            curves.append(arc_tag)
            arc_curves.append(arc_tag)
            meander_curves.append(arc_tag)
            _track(p2_id, item.p2.x, item.p2.y)
            prev_pt_id = p2_id

    # ── Визначаємо отвори (западини меандру) ──────────────────
    #   Точки меандру на осі z=0 розділяють криву на плато (z=0) та
    #   западини (занурення до z=-height). Кожна западина → отвір.
    z0_tol = 1e-9
    z0_idx = [k for k, (pid, x, z) in enumerate(meander_pts) if abs(z) < z0_tol]

    valleys = []  # {curves, xmin, center, left_pt, right_pt}

    # Центральна напівзападина: від початку меандру (0,-h) до 1-го z=0.
    # Замикається лише після дзеркала по YOZ (вісь x=0).
    if z0_idx and z0_idx[0] > 0:
        f0 = z0_idx[0]
        valleys.append({
            'curves': meander_curves[0:f0],
            'xmin': 0.0,
            'center': True,
            'left_pt': meander_pts[0],     # (0, -height) на осі x=0
            'right_pt': meander_pts[f0],   # (~, 0)
        })

    # Повні западини: між сусідніми z=0 точками з проміжними точками z<0.
    for a, b in zip(z0_idx[:-1], z0_idx[1:]):
        if b - a >= 2:
            xs = [meander_pts[k][1] for k in range(a, b + 1)]
            valleys.append({
                'curves': meander_curves[a:b],
                'xmin': min(xs),
                'center': False,
                'left_pt': meander_pts[a],
                'right_pt': meander_pts[b],
            })

    # Нумерація від краю (x=length) до центру: більший x → менший номер.
    valleys.sort(key=lambda v: v['xmin'], reverse=True)
    total_holes = len(valleys)

    # ── Валідація запитаних номерів отворів ───────────────────
    if requested_holes:
        bad = [n for n in requested_holes if n < 1 or n > total_holes]
        if bad:
            gmsh.finalize()
            raise ValueError(
                f"Запитано отвори {sorted(set(requested_holes))}, але півбалка "
                f"має лише {total_holes} отвір(ів). Недопустимі номери: "
                f"{sorted(set(bad))}. Збільште periods у конфізі."
            )

    # ── Замикаючі лінії ──────────────────────────────────────
    # Кінець меандру → (length, -height - h2)
    p_br = add_pt(cfg.length, last_y - cfg.h2)
    curves.append(geo.addLine(prev_pt_id, p_br))

    # → (0, -h1)  — edgeLine (нижня грань стінки)
    p_bl = add_pt(0, -cfg.h1)
    edge_line_tag = geo.addLine(p_br, p_bl)
    curves.append(edge_line_tag)

    # → (0, -height) — замикання до початку меандру
    p_start = add_pt(0, -cfg.height)
    curves.append(geo.addLine(p_bl, p_start))

    # ── Поверхня стінки ──────────────────────────────────────
    wall_loop = geo.addCurveLoop(curves)
    wall_surface = geo.addPlaneSurface([wall_loop])

    # ── Поверхні-заповнення отворів (нижня половина, до z=0) ──
    #   Кожен отвір замикається швом по z=0; центральний — ще й
    #   лінією по осі x=0. Спільні криві з меандром → конформна сітка.
    hole_surfaces = []
    p00_id = None  # точка (0,0) на перетині осей симетрії
    for num in sorted(set(requested_holes)):
        v = valleys[num - 1]
        loop_curves = list(v['curves'])          # left_pt →...→ right_pt
        rp_id = v['right_pt'][0]
        lp_id = v['left_pt'][0]
        if v['center']:
            if p00_id is None:
                p00_id = add_pt(0.0, 0.0)
            loop_curves += [geo.addLine(rp_id, p00_id),   # шов z=0
                            geo.addLine(p00_id, lp_id)]    # вісь x=0
        else:
            loop_curves += [geo.addLine(rp_id, lp_id)]     # шов z=0
        hloop = geo.addCurveLoop(loop_curves)
        hole_surfaces.append(geo.addPlaneSurface([hloop]))

    geo.synchronize()

    # Подрібнення дуг: мінімум 6 вузлів на кожну дугу філлету
    arc_num_nodes = 6
    for arc_tag in arc_curves:
        gmsh.model.geo.mesh.setTransfiniteCurve(arc_tag, arc_num_nodes)
    geo.synchronize()

    gmsh.option.setNumber("Mesh.Algorithm", 8)  # Frontal-Delaunay for Quads
    gmsh.option.setNumber("Mesh.RecombineAll", 1)

    if use_quads:
        gmsh.option.setNumber("Mesh.SubdivisionAlgorithm", 1)  # all quads

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

    # ── Витягуємо елементи (dim=2) по поверхнях ───────────────
    #   Стінка → mat=1, заповнення отворів → mat=3.
    elements: List[Quad] = []
    eid = 1
    tri_count = 0
    quad_count = 0
    fill_count = 0

    surface_mat = [(wall_surface, 1)] + [(hs, 3) for hs in hole_surfaces]
    for stag, mat in surface_mat:
        elem_types, elem_tags_list, elem_node_tags_list = \
            gmsh.model.mesh.getElements(dim=2, tag=stag)
        for et, tags, ntags in zip(elem_types, elem_tags_list,
                                   elem_node_tags_list):
            if et == 2:  # 3-node triangle
                for i in range(len(tags)):
                    n1 = tag_to_id[int(ntags[i * 3])]
                    n2 = tag_to_id[int(ntags[i * 3 + 1])]
                    n3 = tag_to_id[int(ntags[i * 3 + 2])]
                    elements.append(Quad(eid, n1, n2, n3, 0, mat=mat))
                    eid += 1
                    if mat == 1:
                        tri_count += 1
                    else:
                        fill_count += 1
            elif et == 3:  # 4-node quad
                for i in range(len(tags)):
                    n1 = tag_to_id[int(ntags[i * 4])]
                    n2 = tag_to_id[int(ntags[i * 4 + 1])]
                    n3 = tag_to_id[int(ntags[i * 4 + 2])]
                    n4 = tag_to_id[int(ntags[i * 4 + 3])]
                    elements.append(Quad(eid, n1, n2, n3, n4, mat=mat))
                    eid += 1
                    if mat == 1:
                        quad_count += 1
                    else:
                        fill_count += 1

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

    # ── Дзеркальна сітка відносно XOY (z → −z) ──────────────
    #    верхня стінка (mat=3) + верхня полиця (mat=4)
    #    Спільні вузли: z ≈ 0 (ті самі ID)
    original_elements = list(elements)
    mirror_map = {}  # old_nid → mirrored_nid
    z_tol = 1e-6

    for node in list(nodes):
        if abs(node.z) < z_tol:
            mirror_map[node.id] = node.id
        else:
            nid += 1
            mirror_map[node.id] = nid
            nodes.append(Node(nid, node.x, node.y, -node.z))

    mirror_wall_count = 0
    mirror_flange_count = 0
    for elem in original_elements:
        mn1 = mirror_map[elem.n1]
        mn2 = mirror_map[elem.n2]
        mn3 = mirror_map[elem.n3]
        mn4 = mirror_map[elem.n4] if elem.n4 != 0 else 0

        if elem.mat == 1:
            mirror_wall_count += 1
        elif elem.mat == 2:
            mirror_flange_count += 1

        # Реверс обходу для збереження напрямку нормалі
        if mn4 == 0:  # трикутник
            elements.append(Quad(eid, mn1, mn3, mn2, 0, mat=elem.mat))
        else:  # чотирикутник
            elements.append(Quad(eid, mn1, mn4, mn3, mn2, mat=elem.mat))
        eid += 1

    # ── Дзеркальна сітка відносно YOZ (x → −x) ──────────────
    #    Спільні вузли: x ≈ 0 (ті самі ID)
    all_before_x_mirror = list(elements)
    x_mirror_map = {}  # old_nid → mirrored_nid
    x_tol = 1e-6

    for node in list(nodes):
        if abs(node.x) < x_tol:
            x_mirror_map[node.id] = node.id
        else:
            nid += 1
            x_mirror_map[node.id] = nid
            nodes.append(Node(nid, -node.x, node.y, node.z))

    x_mirror_count = 0
    for elem in all_before_x_mirror:
        mn1 = x_mirror_map[elem.n1]
        mn2 = x_mirror_map[elem.n2]
        mn3 = x_mirror_map[elem.n3]
        mn4 = x_mirror_map[elem.n4] if elem.n4 != 0 else 0

        # Реверс обходу для збереження напрямку нормалі
        if mn4 == 0:  # трикутник
            elements.append(Quad(eid, mn1, mn3, mn2, 0, mat=elem.mat))
        else:  # чотирикутник
            elements.append(Quad(eid, mn1, mn4, mn3, mn2, mat=elem.mat))
        eid += 1
        x_mirror_count += 1

    # ── Середнє ребро (x=0, площина YOZ) ─────────────────────
    #    Прямокутник: y ∈ [0, bf/2], z ∈ [-(height+h2), height+h2]
    #    Спільні вузли з існуючими сітками при x ≈ 0
    rib_elem_count = 0
    if cfg.nb > 0 and cfg.bf > 0:
        rib_x_tol = 1e-6
        rib_y_tol = 1e-6

        # 1. Зібрати всі z-значення вузлів на осі x=0, y=0
        z_axis = {}  # round(z,8) → node_id
        for node in nodes:
            if abs(node.x) < rib_x_tol and abs(node.y) < rib_y_tol:
                z_axis[round(node.z, 8)] = node.id

        z_vals = sorted(z_axis.keys())

        # 2. Розбити проміжки де z змінює знак
        extra_z = []
        for k in range(len(z_vals) - 1):
            z1, z2 = z_vals[k], z_vals[k + 1]
            if z1 < -rib_x_tol and z2 > rib_x_tol:
                gap = z2 - z1
                n_sub = max(2, round(gap / mesh_size))
                dz = gap / n_sub
                for s in range(1, n_sub):
                    extra_z.append(round(z1 + s * dz, 8))
                # гарантувати z=0
                if not any(abs(zz) < rib_x_tol for zz in extra_z):
                    extra_z.append(0.0)

        # Додати нові вузли на осі
        for zv in extra_z:
            zk = round(zv, 8)
            if zk not in z_axis:
                nid += 1
                nodes.append(Node(nid, 0.0, 0.0, zv))
                z_axis[zk] = nid

        z_vals = sorted(z_axis.keys())

        # 3. Побудувати lookup для існуючих вузлів при x ≈ 0
        rib_lookup = {}  # (y_round, z_round) → node_id
        for node in nodes:
            if abs(node.x) < rib_x_tol:
                key = (round(node.y, 6), round(node.z, 6))
                rib_lookup[key] = node.id

        # 4. Побудувати сітку rib_grid[(iz, iy)] → node_id
        dy = cfg.bf / (2 * cfg.nb)
        rib_grid = {}

        for iz, zv in enumerate(z_vals):
            for iy in range(cfg.nb + 1):
                y_val = round(iy * dy, 8)
                key = (round(y_val, 6), round(zv, 6))
                if key in rib_lookup:
                    rib_grid[(iz, iy)] = rib_lookup[key]
                else:
                    nid += 1
                    nodes.append(Node(nid, 0.0, y_val, zv))
                    rib_lookup[key] = nid
                    rib_grid[(iz, iy)] = nid

        # 5. Прямокутні елементи ребра
        for iz in range(len(z_vals) - 1):
            for iy in range(cfg.nb):
                n1 = rib_grid[(iz, iy)]
                n2 = rib_grid[(iz + 1, iy)]
                n3 = rib_grid[(iz + 1, iy + 1)]
                n4 = rib_grid[(iz, iy + 1)]
                elements.append(Quad(eid, n1, n2, n3, n4, mat=1))
                eid += 1
                rib_elem_count += 1

    # ── В'язі (опори) ────────────────────────────────────────
    restrictions = []
    tol = 1e-6
    for node in nodes:
        # Ліва опора: x = -length, z = -h2 → закріплення X,Y,Z
        if abs(node.x - (-cfg.length)) < tol and abs(node.z - (-cfg.h2)) < tol:
            restrictions += [(node.id, 1), (node.id, 2), (node.id, 3)]
        # Права опора: x = length, z = -h2 → закріплення Y,Z
        elif abs(node.x - cfg.length) < tol and abs(node.z - (-cfg.h2)) < tol:
            restrictions += [(node.id, 2), (node.id, 3)]

    # ── Навантаження ──────────────────────────────────────────
    #    Вертикальна сила -10 т у вузлі (0, h1, 0)
    loads = []
    target_z = cfg.h1
    for node in nodes:
        if abs(node.x) < tol and abs(node.y) < tol and abs(node.z - target_z) < tol:
            loads.append((node.id, 3, -10.0, 1))
            break

    # ── Записуємо .sli ───────────────────────────────────────
    materials = [
        {"num": 1, "H": cfg.tw, "F": nu, "E": E, "Ro": rho},
        {"num": 2, "H": cfg.tb, "F": nu, "E": E, "Ro": rho},
        {"num": 3, "H": cfg.t_fill, "F": nu, "E": E, "Ro": rho},
    ]

    filepath = output if output.endswith('.sli') else output + '.sli'
    write_plate_sli(name, nodes, elements, materials, filepath,
                    restrictions=restrictions, loads=loads)

    print(f"\n{'=' * 60}")
    print(f"  Meander: {name}")
    print(f"{'=' * 60}")
    print(f"  length={cfg.length}, height={cfg.height}, "
          f"periods={cfg.periods}, radius={cfg.radius}")
    print(f"  h1={cfg.h1}, h2={cfg.h2}, bf={cfg.bf}, nb={cfg.nb}")
    print(f"  Mesh size  : {mesh_size} m")
    print(f"  Nodes      : {len(nodes)}")
    print(f"  Wall       : {quad_count + tri_count} "
          f"(quad={quad_count}, tri={tri_count})")
    print(f"  Holes      : {total_holes} (filled={sorted(set(requested_holes))}, "
          f"t_fill={cfg.t_fill}, fill el.={fill_count} per quadrant)")
    print(f"  Flange     : {flange_quad_count} quad")
    print(f"  Top wall   : {mirror_wall_count} el.")
    print(f"  Top flange : {mirror_flange_count} el.")
    print(f"  X-mirror   : {x_mirror_count} el.")
    print(f"  Mid rib    : {rib_elem_count} el.")
    print(f"  Constraints: {len(restrictions)}")
    print(f"  Total el.  : {len(elements)}")
    print(f"  File       : {filepath}")

    return filepath


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Генератор меш-сітки меандру (gmsh) → ЛІРА САПР .sli"
    )
    parser.add_argument("--mesh-size", type=float, default=0.05,
                        help="Розмір елемента, м (default: 0.05)")
    parser.add_argument("--quads", action="store_true",
                        help="Рекомбінувати трикутники в квади")
    parser.add_argument("--name", type=str, default="meander",
                        help="Назва моделі (default: meander)")
    parser.add_argument("--output", type=str, default="meander.sli",
                        help="Вихідний файл (default: meander.sli)")
    parser.add_argument("--fill-holes", type=str, default=None,
                        help="Номери отворів для заповнення, напр. 1,2,5 "
                             "(нумерація від краю до центру)")
    parser.add_argument("--t-fill", type=float, default=None,
                        help="Товщина сітки-заповнення отворів, м")

    args = parser.parse_args()
    cfg = Config()
    if args.t_fill is not None:
        cfg.t_fill = args.t_fill
    generate(cfg, mesh_size=args.mesh_size, use_quads=args.quads,
             name=args.name, output=args.output, fill_holes=args.fill_holes)
