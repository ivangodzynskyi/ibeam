"""
================================================================
  Генератор двотаврової балки змінної висоти → ЛІРА САПР .sli
================================================================

Формат .sli — це XML (FE_Project), який ЛІРА САПР 2024 відкриває
через Файл → Імпорт → *.sli

Система координат (з аналізу вашого файлу test2.sli):
  X — ширина полиці  (поперечний напрямок)
  Y — вздовж осі балки (повздовжній напрямок)
  Z — висота перерізу (вертикальний напрямок)

Структура балки:
  - Верхня полиця:  Z = h(y)/2 .. h(y)/2 + tf
  - Стінка:         Z = -h_w(y)/2 .. h_w(y)/2
  - Нижня полиця:   Z = -h(y)/2 - tf .. -h(y)/2

Матеріали:
  Material 1 — полиці (H = tf)
  Material 2 — стінка (H = tw)

Навантаження:
  LC1 — q кН/м² по всьому прольоту (верхній пояс)
  LC2 — q кН/м² по лівій половині  (верхній пояс)

ВИКОРИСТАННЯ:
  python ibeam_sli_generator.py                         # інтерактивно
  python ibeam_sli_generator.py --batch                 # 7 моделей
  python ibeam_sli_generator.py --L 8 --h1 0.6 --h2 1.0 --nx 10 --nw 8

ІМПОРТ У ЛІРА:
  Файл → Відкрити / Імпорт → вибрати *.sli
"""

import argparse
import os
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Tuple, Dict
import xml.etree.ElementTree as ET


# ──────────────────────────────────────────────────────────────
#  Параметри балки
# ──────────────────────────────────────────────────────────────

@dataclass
class BeamParams:
    L:    float = 6.0     # довжина балки (вісь Y), м
    h1:   float = 0.6     # висота перерізу на початку (Y=0), м
    h2:   float = 1.0     # висота перерізу на кінці  (Y=L), м
    tw:   float = 0.008   # товщина стінки, м
    tf:   float = 0.012   # товщина полиці, м
    bf:   float = 0.2     # ширина полиці, м
    nx:   int   = 4       # елементів по ширині полиці (на кожну сторону від стінки)
    ny:   int   = 10      # елементів по довжині балки
    nw:   int   = 8       # елементів по висоті стінки
    E:    float = 2.02027e7  # модуль пружності, кН/м²  (= 206 ГПа ÷ кН/м²)
    nu:   float = 0.28    # коефіцієнт Пуассона
    rho:  float = 7850.0  # щільність, кг/м³
    q:    float = 1.0     # навантаження, кН/м²
    name: str   = "ibeam"

    def h(self, y: float) -> float:
        """Повна висота перерізу в точці y."""
        return self.h1 + (self.h2 - self.h1) * y / self.L

    def hw(self, y: float) -> float:
        """Висота стінки (між полицями) в точці y."""
        return self.h(y) - 2 * self.tf


# ──────────────────────────────────────────────────────────────
#  Вузли та елементи
# ──────────────────────────────────────────────────────────────

@dataclass
class Node:
    id: int
    x:  float   # ширина (поперечний)
    y:  float   # вздовж осі
    z:  float   # висота (вертикальний)


@dataclass
class Quad:
    id:       int
    n1: int; n2: int; n3: int; n4: int
    mat:      int   # 1=полиця, 2=стінка


# ──────────────────────────────────────────────────────────────
#  Генератор сітки
# ──────────────────────────────────────────────────────────────

class IBeamMesh:
    def __init__(self, p: BeamParams):
        self.p = p
        self.nodes:    List[Node] = []
        self.elements: List[Quad] = []
        self._nid = 1
        self._eid = 1

    def _n(self, x, y, z) -> int:
        nid = self._nid
        self.nodes.append(Node(nid, round(x, 8), round(y, 8), round(z, 8)))
        self._nid += 1
        return nid

    def _q(self, n1, n2, n3, n4, mat) -> int:
        eid = self._eid
        self.elements.append(Quad(eid, n1, n2, n3, n4, mat))
        self._eid += 1
        return eid

    def build(self):
        p = self.p

        # Y-координати зрізів (вздовж осі балки)
        y_cuts = [p.L * j / p.ny for j in range(p.ny + 1)]

        # ── 1. СТІНКА ─────────────────────────────────────────────
        # Вузли: (ny+1) зрізів × (nw+1) рядів по висоті
        # X = 0 (вісь симетрії)
        web_grid: Dict[Tuple[int,int], int] = {}   # (j_y, k_z) → node_id

        for j, y in enumerate(y_cuts):
            hw = p.hw(y)
            z_bot = -hw / 2
            for k in range(p.nw + 1):
                z = z_bot + hw * k / p.nw
                web_grid[(j, k)] = self._n(0.0, y, z)

        # Елементи стінки
        for j in range(p.ny):
            for k in range(p.nw):
                n1 = web_grid[(j,   k  )]
                n2 = web_grid[(j+1, k  )]
                n3 = web_grid[(j+1, k+1)]
                n4 = web_grid[(j,   k+1)]
                self._q(n1, n2, n3, n4, mat=2)  # стінка → mat 2

        # ── 2. ПОЛИЦІ ─────────────────────────────────────────────
        # Верхня та нижня полиці
        # X: від -bf/2 до +bf/2, розбито на 2*nx ділянок
        # Верхня: Z від hw/2 до hw/2 + tf
        # Нижня:  Z від -hw/2 - tf до -hw/2

        x_cuts = [-p.bf/2 + p.bf * i / (2 * p.nx) for i in range(2 * p.nx + 1)]

        for sign, label in [(+1, 'top'), (-1, 'bot')]:
            fl_grid: Dict[Tuple[int,int], int] = {}   # (j_y, i_x) → node_id

            for j, y in enumerate(y_cuts):
                hw = p.hw(y)
                # Z координати двох рядів полиці
                if sign == +1:
                    z_inner = hw / 2           # межа зі стінкою
                    z_outer = hw / 2 + p.tf    # зовнішня кромка
                else:
                    z_inner = -hw / 2
                    z_outer = -hw / 2 - p.tf

                for i, x in enumerate(x_cuts):
                    # Вузли на межі зі стінкою (inner)
                    # Вузли на осі (x=0) збігаються з вузлами стінки
                    if i == p.nx:  # центральний вузол = вузол стінки
                        if sign == +1:
                            fl_grid[(j, i, 'inner')] = web_grid[(j, p.nw)]
                        else:
                            fl_grid[(j, i, 'inner')] = web_grid[(j, 0)]
                    else:
                        fl_grid[(j, i, 'inner')] = self._n(x, y, z_inner)

                    # Зовнішній ряд вузлів
                    fl_grid[(j, i, 'outer')] = self._n(x, y, z_outer)

            # Елементи полиці
            for j in range(p.ny):
                for i in range(2 * p.nx):
                    n1 = fl_grid[(j,   i,   'inner')]
                    n2 = fl_grid[(j+1, i,   'inner')]
                    n3 = fl_grid[(j+1, i+1, 'inner')]
                    n4 = fl_grid[(j,   i+1, 'inner')]
                    self._q(n1, n2, n3, n4, mat=1)  # полиця → mat 1

                    n1 = fl_grid[(j,   i,   'outer')]
                    n2 = fl_grid[(j+1, i,   'outer')]
                    n3 = fl_grid[(j+1, i+1, 'outer')]
                    n4 = fl_grid[(j,   i+1, 'outer')]
                    self._q(n1, n2, n3, n4, mat=1)

        return self.nodes, self.elements

    # ── Допоміжні вибірки ─────────────────────────────────────

    def support_nodes(self, y_val: float) -> List[int]:
        """Всі вузли в зрізі Y ≈ y_val."""
        return [n.id for n in self.nodes if abs(n.y - y_val) < 1e-6]

    def top_outer_nodes(self) -> List[Tuple[float, int]]:
        """
        Вузли верхньої зовнішньої кромки полиці (max Z для кожного Y).
        Повертає [(y, node_id), ...] відсортовано по Y.
        """
        by_y: Dict[float, List[Node]] = defaultdict(list)
        for n in self.nodes:
            by_y[round(n.y, 6)].append(n)
        result = []
        for y_val in sorted(by_y):
            top = max(by_y[y_val], key=lambda n: n.z)
            result.append((y_val, top.id))
        return result

    def nodal_forces(self, y_min: float, y_max: float) -> List[Tuple[int, float]]:
        """
        Вузлові сили на верхній кромці в діапазоні [y_min, y_max].
        F = -q * (dy_left + dy_right)/2 * bf  (мінус = вниз по Z)
        NDOF=3 відповідає Z у ЛІРА sli-форматі.
        """
        top = self.top_outer_nodes()
        ys  = [yv for yv, _ in top]
        forces = []
        for i, (yv, nid) in enumerate(top):
            if yv < y_min - 1e-9 or yv > y_max + 1e-9:
                continue
            dy_l = (yv - ys[i-1]) / 2 if i > 0          else 0.0
            dy_r = (ys[i+1] - yv) / 2 if i < len(ys)-1  else 0.0
            if abs(yv - y_min) < 1e-9 and i > 0:
                dy_l = 0.0
            if abs(yv - y_max) < 1e-9 and i < len(ys)-1:
                dy_r = 0.0
            dy = dy_l + dy_r
            if dy < 1e-12:
                continue
            F = -self.p.q * dy * self.p.bf   # кН (q в кН/м²)
            forces.append((nid, F))
        return forces


# ──────────────────────────────────────────────────────────────
#  Запис у .sli (XML формат ЛІРА САПР)
# ──────────────────────────────────────────────────────────────

def _fmt(v: float) -> str:
    """Форматує число: без зайвих нулів, але з достатньою точністю."""
    if v == 0.0:
        return "0"
    s = f"{v:.8g}"
    return s


def write_sli(p: BeamParams,
              nodes: List[Node],
              elements: List[Quad],
              forces_lc1: List[Tuple[int, float]],
              forces_lc2: List[Tuple[int, float]],
              filepath: str):
    """
    Записує модель у форматі .sli (XML FE_Project).

    Структура файлу (з аналізу test2.sli):
      <FE_Project Title="..." Description="">
        <DegreesOfFreedom X="1" Y="1" Z="1" UX="1" UY="1" UZ="1" />
        <NodesCoordArray NumberOfElem="N">
          <NodeCoords NdX="..." NdY="..." NdZ="..." />
          ...
        </NodesCoordArray>
        <RestrictionsArray NumberOfElem="R">
          <Restricts NdNum="..." NDOF="1|2|3" />   ← 1=X,2=Y,3=Z
          ...
        </RestrictionsArray>
        <ElementsArray NumberOfElem="E">
          <Element Type="2" Material="1|2">
            <Nodes Nd1=".." Nd2=".." Nd3=".." Nd4=".." />
          </Element>
          ...
        </ElementsArray>
        <MaterialsArray NumberOfElem="2">
          <Material Num="1" KindEl="3" H="tf" F="nu" E="E" Ro="rho" />
          <Material Num="2" KindEl="3" H="tw" F="nu" E="E" Ro="rho" />
        </MaterialsArray>
        <NodesLoadingArray NumberOfElem="...">
          <NodesLoading NumNode=".." NDOF="3" LoadType="0"
                        LoadNumber="1|2" LoadValue="..." LocalSys="0" />
          ...
        </NodesLoadingArray>
        <ElemHingeArray    NumberOfElem="0" />
        <NodeHingeArray    NumberOfElem="0" />
        <EccentricityArray NumberOfElem="0" />
        <ElemLoadingArray  NumberOfElem="0" />
      </FE_Project>
    """

    lines = []

    def ln(s):
        lines.append(s)

    ln('<?xml version="1.0" standalone="yes"?>')
    ln('<!--Generated by ibeam_sli_generator.py-->')
    ln(f'<FE_Project Title="{p.name}" Description="">')
    ln('  <DegreesOfFreedom X="1" Y="1" Z="1" UX="1" UY="1" UZ="1" />')

    # ── Вузли ──────────────────────────────────────────────────
    ln(f'  <NodesCoordArray NumberOfElem="{len(nodes)}">')
    for n in nodes:
        ln(f'    <NodeCoords NdX="{_fmt(n.x)}" NdY="{_fmt(n.y)}" NdZ="{_fmt(n.z)}" />')
    ln('  </NodesCoordArray>')

    # ── В'язі ──────────────────────────────────────────────────
    # Ліва опора (Y=0): закріплення X(1), Y(2), Z(3)
    # Права опора (Y=L): закріплення X(1), Z(3) — рухома по Y
    support_start = [n.id for n in nodes if abs(n.y) < 1e-6]
    support_end   = [n.id for n in nodes if abs(n.y - p.L) < 1e-6]

    restrictions = []
    for nid in support_start:
        restrictions += [(nid, 1), (nid, 2), (nid, 3)]
    for nid in support_end:
        restrictions += [(nid, 1), (nid, 3)]

    ln(f'  <RestrictionsArray NumberOfElem="{len(restrictions)}">')
    for nid, dof in restrictions:
        ln(f'    <Restricts NdNum="{nid}" NDOF="{dof}" />')
    ln('  </RestrictionsArray>')

    # ── Елементи ───────────────────────────────────────────────
    ln(f'  <ElementsArray NumberOfElem="{len(elements)}">')
    for e in elements:
        ln(f'    <Element Type="2" Material="{e.mat}">')
        ln(f'      <Nodes Nd1="{e.n1}" Nd2="{e.n2}" Nd3="{e.n3}" Nd4="{e.n4}" />')
        ln('    </Element>')
    ln('  </ElementsArray>')

    # ── Матеріали ──────────────────────────────────────────────
    # KindEl=3 — пластина (з test2.sli)
    # H — товщина, F — nu, E — модуль, Ro — щільність
    ln('  <MaterialsArray NumberOfElem="2">')
    ln(f'    <Material Num="1" KindEl="3" H="{_fmt(p.tf)}" F="{_fmt(p.nu)}" '
       f'E="{_fmt(p.E)}" Ro="{_fmt(p.rho)}" />')
    ln(f'    <Material Num="2" KindEl="3" H="{_fmt(p.tw)}" F="{_fmt(p.nu)}" '
       f'E="{_fmt(p.E)}" Ro="{_fmt(p.rho)}" />')
    ln('  </MaterialsArray>')

    # ── Навантаження ───────────────────────────────────────────
    # NDOF=3 → Z (вертикаль), LoadType=0 → статичне, LocalSys=0 → глобальна
    # LoadNumber=1 → LC1, LoadNumber=2 → LC2
    # LoadValue в кН (негативне → вниз)
    all_loads = (
        [(nid, f, 1) for nid, f in forces_lc1] +
        [(nid, f, 2) for nid, f in forces_lc2]
    )
    ln(f'  <NodesLoadingArray NumberOfElem="{len(all_loads)}">')
    for nid, fval, lc in all_loads:
        ln(f'    <NodesLoading NumNode="{nid}" NDOF="3" LoadType="0" '
           f'LoadNumber="{lc}" LoadValue="{_fmt(fval)}" LocalSys="0" />')
    ln('  </NodesLoadingArray>')

    # ── Порожні блоки (обов'язкові для ЛІРА) ──────────────────
    ln('  <ElemHingeArray NumberOfElem="0" />')
    ln('  <NodeHingeArray NumberOfElem="0" />')
    ln('  <EccentricityArray NumberOfElem="0" />')
    ln('  <ElemLoadingArray NumberOfElem="0" />')
    ln('</FE_Project>')

    os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
    with open(filepath, 'w', encoding='utf-8', newline='\r\n') as f:
        f.write('\n'.join(lines))


# ──────────────────────────────────────────────────────────────
#  Генерація однієї моделі
# ──────────────────────────────────────────────────────────────

def generate(p: BeamParams, output_dir: str = ".") -> str:
    """Будує сітку, обчислює навантаження, зберігає .sli. Повертає шлях до файлу."""

    mesh = IBeamMesh(p)
    nodes, elements = mesh.build()

    forces_lc1 = mesh.nodal_forces(0.0, p.L)
    forces_lc2 = mesh.nodal_forces(0.0, p.L / 2)

    total_lc1 = sum(abs(f) for _, f in forces_lc1)
    total_lc2 = sum(abs(f) for _, f in forces_lc2)

    # Підрахунок елементів по частинах
    web_count    = sum(1 for e in elements if e.mat == 2)
    flange_count = len(elements) - web_count

    filepath = os.path.join(output_dir, f"{p.name}.sli")
    write_sli(p, nodes, elements, forces_lc1, forces_lc2, filepath)

    print(f"\n{'='*60}")
    print(f"  Модель: {p.name}")
    print(f"{'='*60}")
    print(f"  L        = {p.L} м")
    print(f"  h1 / h2  = {p.h1*1000:.0f} / {p.h2*1000:.0f} мм")
    print(f"  tw / tf  = {p.tw*1000:.1f} / {p.tf*1000:.1f} мм")
    print(f"  bf       = {p.bf*1000:.0f} мм")
    print(f"  Сітка    : ny={p.ny}, nw={p.nw}, nx={p.nx}")
    print(f"  Вузлів   : {len(nodes)}")
    print(f"  Елементів: {len(elements)} (стінка={web_count}, полиці={flange_count})")
    print(f"  LC1 сума : {total_lc1:.3f} кН  ({len(forces_lc1)} вузлів)")
    print(f"  LC2 сума : {total_lc2:.3f} кН  ({len(forces_lc2)} вузлів)")
    print(f"  Файл     : {filepath}")

    return filepath


# ──────────────────────────────────────────────────────────────
#  Пакетний режим
# ──────────────────────────────────────────────────────────────

def run_batch(output_dir: str = "sli_models"):
    MODELS = [
        BeamParams(L=8.0, h1=0.6, h2=1.0, tw=0.008, tf=0.012, bf=0.20,
                   nx=2, ny=8,  nw=4,  name="model_coarse"),
        BeamParams(L=8.0, h1=0.6, h2=1.0, tw=0.008, tf=0.012, bf=0.20,
                   nx=3, ny=16, nw=8,  name="model_medium"),
        BeamParams(L=8.0, h1=0.6, h2=1.0, tw=0.008, tf=0.012, bf=0.20,
                   nx=4, ny=32, nw=16, name="model_fine"),
        BeamParams(L=10., h1=0.4, h2=0.8, tw=0.006, tf=0.010, bf=0.16,
                   nx=3, ny=20, nw=6,  name="model_h400_800"),
        BeamParams(L=10., h1=0.6, h2=1.2, tw=0.010, tf=0.016, bf=0.25,
                   nx=3, ny=20, nw=10, name="model_h600_1200"),
        BeamParams(L=6.0, h1=0.5, h2=0.9, tw=0.006, tf=0.010, bf=0.18,
                   nx=2, ny=12, nw=6,  name="model_thin"),
        BeamParams(L=6.0, h1=0.5, h2=0.9, tw=0.014, tf=0.020, bf=0.22,
                   nx=3, ny=12, nw=6,  name="model_thick"),
    ]
    print(f"\nПакетна генерація: {len(MODELS)} моделей → '{output_dir}/'")
    for i, pm in enumerate(MODELS, 1):
        print(f"\n[{i}/{len(MODELS)}]", end="")
        generate(pm, output_dir)
    print(f"\n\n✓ Готово! Всі .sli файли у папці '{output_dir}/'")
    print("  Відкривайте у ЛІРА: Файл → Відкрити → *.sli")


# ──────────────────────────────────────────────────────────────
#  Інтерактивний режим
# ──────────────────────────────────────────────────────────────

def run_interactive():
    print("\n" + "="*60)
    print("  Генератор двотаврової балки → ЛІРА САПР (.sli)")
    print("="*60)
    print("  Введіть параметри (Enter = значення за замовч.)\n")

    def ask(prompt, default):
        val = input(f"  {prompt} [{default}]: ").strip()
        return type(default)(val) if val else default

    p = BeamParams(
        L    = ask("Довжина балки L, м",           6.0),
        h1   = ask("Висота h1 (початок), м",       0.5),
        h2   = ask("Висота h2 (кінець), м",        0.5),
        tw   = ask("Товщина стінки tw, м",         0.008),
        tf   = ask("Товщина полиці tf, м",         0.012),
        bf   = ask("Ширина полиці bf, м",          0.2),
        nx   = ask("Ел-тів по ширині полиці nx",   2),
        ny   = ask("Ел-тів по довжині балки ny",   10),
        nw   = ask("Ел-тів по висоті стінки nw",   8),
        q    = ask("Навантаження q, кН/м²",        1.0),
        name = ask("Назва моделі",                 "ibeam"),
    )
    out_dir = ask("Папка виводу", "output")
    generate(p, output_dir=out_dir)
    print("\n✓ Готово! Відкрийте файл у ЛІРА: Файл → Відкрити → *.sli")


# ──────────────────────────────────────────────────────────────
#  Точка входу
# ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Генератор двотаврової балки змінної висоти → ЛІРА САПР .sli"
    )
    parser.add_argument("--batch", action="store_true", help="Пакетна генерація 7 моделей")
    parser.add_argument("--out",   default="sli_output", help="Папка виводу")
    parser.add_argument("--L",     type=float)
    parser.add_argument("--h1",    type=float)
    parser.add_argument("--h2",    type=float)
    parser.add_argument("--tw",    type=float)
    parser.add_argument("--tf",    type=float)
    parser.add_argument("--bf",    type=float)
    parser.add_argument("--nx",    type=int, help="Ел-тів по ширині полиці")
    parser.add_argument("--ny",    type=int, help="Ел-тів по довжині балки")
    parser.add_argument("--nw",    type=int, help="Ел-тів по висоті стінки")
    parser.add_argument("--q",     type=float, default=1.0)
    parser.add_argument("--name",  type=str,   default="ibeam")
    args = parser.parse_args()

    if args.batch:
        run_batch(output_dir=args.out)
    elif any([args.L, args.h1, args.h2, args.tw, args.tf, args.bf,
              args.nx, args.ny, args.nw]):
        p = BeamParams(
            L    = args.L  or 6.0,
            h1   = args.h1 or 0.5,
            h2   = args.h2 or 0.5,
            tw   = args.tw or 0.008,
            tf   = args.tf or 0.012,
            bf   = args.bf or 0.2,
            nx   = args.nx or 2,
            ny   = args.ny or 10,
            nw   = args.nw or 8,
            q    = args.q,
            name = args.name,
        )
        generate(p, output_dir=args.out)
    else:
        run_interactive()
