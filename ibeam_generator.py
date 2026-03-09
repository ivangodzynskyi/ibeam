"""
===============================================================
  Генератор двотаврової балки змінної висоти — сітка СЕ
  Формат виводу: текстовий файл для ЛІРА САПР (.txt / .lir)
  Автор: згенеровано Claude
===============================================================

ПАРАМЕТРИ (змінюються між моделями):
  L        — довжина балки [м]
  h1       — висота перерізу на початку [м]
  h2       — висота перерізу на кінці [м]
  tw       — товщина стінки [м]
  tf       — товщина полиці [м]
  bf       — ширина полиці [м]
  nx       — кількість елементів вздовж осі X (по довжині)
  nw       — кількість елементів по висоті стінки
  nf       — кількість елементів по ширині полиці

ВИКОРИСТАННЯ:
  python ibeam_generator.py                   # інтерактивний режим
  python ibeam_generator.py --batch           # пакетний режим (кілька моделей)
  python ibeam_generator.py --help            # довідка

ВИХОДИ:
  <назва>.txt   — файл вхідних даних ЛІРА САПР
  <назва>.dxf   — геометрія сітки для AutoCAD/перегляду (опційно)
"""

import argparse
import os
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Tuple, Dict


# ─────────────────────────────────────────────
#  Структури даних
# ─────────────────────────────────────────────

@dataclass
class BeamParams:
    """Параметри двотаврової балки."""
    L:   float = 6.0    # довжина балки, м
    h1:  float = 0.6    # висота перерізу на початку, м
    h2:  float = 1.0    # висота перерізу на кінці, м
    tw:  float = 0.012  # товщина стінки, м
    tf:  float = 0.016  # товщина полиці, м
    bf:  float = 0.3    # ширина полиці, м
    nx:  int   = 10     # елементів по довжині
    nw:  int   = 4      # елементів по висоті стінки
    nf:  int   = 3      # елементів по ширині полиці (на кожну сторону)
    E:   float = 2.06e8 # модуль пружності, кН/м²
    nu:  float = 0.3    # коефіцієнт Пуассона
    name: str  = "ibeam_model"

    def web_height(self, x: float) -> float:
        """Висота стінки (без полиць) в точці x."""
        h = self.h1 + (self.h2 - self.h1) * x / self.L
        return h - 2 * self.tf

    def total_height(self, x: float) -> float:
        """Повна висота перерізу в точці x."""
        return self.h1 + (self.h2 - self.h1) * x / self.L


@dataclass
class Node:
    id:  int
    x:   float
    y:   float
    z:   float = 0.0


@dataclass
class Element:
    id:   int
    nodes: List[int]   # список id вузлів (4 вузли — чотирикутник)
    thickness: float
    part: str          # 'web' | 'top_flange' | 'bot_flange'


# ─────────────────────────────────────────────
#  Генерація сітки
# ─────────────────────────────────────────────

class IBeamMeshGenerator:
    def __init__(self, p: BeamParams):
        self.p = p
        self.nodes: List[Node] = []
        self.elements: List[Element] = []
        self._node_id = 1
        self._elem_id = 1
        # Сітка вузлів: словник (i_col, i_row, part) -> node_id
        self._grid: Dict[Tuple, int] = {}

    def _add_node(self, x: float, y: float, z: float = 0.0) -> int:
        nid = self._node_id
        self.nodes.append(Node(nid, round(x, 6), round(y, 6), round(z, 6)))
        self._node_id += 1
        return nid

    def _add_element(self, n1, n2, n3, n4, thickness: float, part: str) -> int:
        eid = self._elem_id
        self.elements.append(Element(eid, [n1, n2, n3, n4], thickness, part))
        self._elem_id += 1
        return eid

    def generate(self):
        """Головна функція генерації сітки."""
        p = self.p
        nx, nw, nf = p.nx, p.nw, p.nf

        # X-координати колонок вузлів
        x_cols = [p.L * i / nx for i in range(nx + 1)]

        # ── 1. СТІНКА ──────────────────────────────────────────────────
        # Вузлова сітка стінки: (nx+1) колонок × (nw+1) рядків
        web_nodes = {}  # (col, row) -> node_id

        for ic, x in enumerate(x_cols):
            hw = p.web_height(x)   # висота стінки в цьому перерізі
            y_bot = -hw / 2        # нижня межа стінки (локальна Y від центра)
            for ir in range(nw + 1):
                y = y_bot + hw * ir / nw
                nid = self._add_node(x, y)
                web_nodes[(ic, ir)] = nid

        # Елементи стінки
        for ic in range(nx):
            x_mid = (x_cols[ic] + x_cols[ic + 1]) / 2
            hw_mid = p.web_height(x_mid)
            for ir in range(nw):
                n1 = web_nodes[(ic,     ir    )]
                n2 = web_nodes[(ic + 1, ir    )]
                n3 = web_nodes[(ic + 1, ir + 1)]
                n4 = web_nodes[(ic,     ir + 1)]
                self._add_element(n1, n2, n3, n4, p.tw, 'web')

        # ── 2. ПОЛИЦІ ──────────────────────────────────────────────────
        # Верхня та нижня полиці: по (nf) елементів вліво і вправо від осі
        # + перший ряд вузлів полиці збігається з крайнім рядом стінки

        for sign, label in [(+1, 'top'), (-1, 'bot')]:
            flange_nodes = {}  # (col, row_f) -> node_id
            # row_f = 0 — вузли, що збігаються з кромкою стінки
            # row_f = 1 — зовнішня кромка полиці

            for ic, x in enumerate(x_cols):
                hw = p.web_height(x)
                # Y-координата кромки стінки (де приєднується полиця)
                y_web_edge = sign * hw / 2

                # row_f = 0: вузли вже створені як крайній ряд стінки
                if sign == +1:
                    flange_nodes[(ic, 0)] = web_nodes[(ic, nw)]
                else:
                    flange_nodes[(ic, 0)] = web_nodes[(ic, 0)]

                # row_f = 1: зовнішня кромка полиці
                y_outer = y_web_edge + sign * p.tf
                nid = self._add_node(x, y_outer)
                flange_nodes[(ic, 1)] = nid

            # Елементи полиці: по ширині ділимо на 2*nf+1 ділянок
            # Полиця — від -bf/2 до +bf/2, але стінка займає [-tw/2, +tw/2]
            # Спрощення: вся полиця як суцільна пластина (включно зі стінкою)
            # Для більш детальної моделі — додаткові вузли по Z

            # Тут реалізуємо 2D-модель (площина XY), полиця — один ряд елементів
            for ic in range(nx):
                x_mid = (x_cols[ic] + x_cols[ic + 1]) / 2
                # Ефективна ширина полиці — для задання товщини враховуємо bf
                n1 = flange_nodes[(ic,     0)]
                n2 = flange_nodes[(ic + 1, 0)]
                n3 = flange_nodes[(ic + 1, 1)]
                n4 = flange_nodes[(ic,     1)]
                part = f'{label}_flange'
                self._add_element(n1, n2, n3, n4, p.bf, part)

        return self.nodes, self.elements


# ─────────────────────────────────────────────
#  Запис у формат ЛІРА САПР
# ─────────────────────────────────────────────

class LiraWriter:
    """
    Записує модель у текстовий формат вхідних даних ЛІРА САПР.
    Формат: ASCII-препроцесор ЛІРА (команди NODE, ELEM, MAT, PROP, BC).
    """

    def __init__(self, p: BeamParams, nodes: List[Node], elements: List[Element]):
        self.p = p
        self.nodes = nodes
        self.elements = elements

    def write(self, filepath: str):
        p = self.p
        lines = []

        # ── Заголовок ──
        lines += [
            f"; ============================================================",
            f"; Модель: {p.name}",
            f"; Двотаврова балка змінної висоти",
            f"; L={p.L} м | h1={p.h1} м | h2={p.h2} м",
            f"; tw={p.tw*1000:.1f} мм | tf={p.tf*1000:.1f} мм | bf={p.bf*1000:.1f} мм",
            f"; Сітка: nx={p.nx} | nw={p.nw} | nf={p.nf}",
            f"; Вузлів: {len(self.nodes)} | Елементів: {len(self.elements)}",
            f"; ============================================================",
            "",
            "ЗАДАЧА",
            f"НАЗВА '{p.name}'",
            "",
        ]

        # ── Матеріал ──
        lines += [
            "; --- Матеріал (сталь) ---",
            "МАТЕРІАЛ 1",
            f"  E    {p.E:.3E}",
            f"  NU   {p.nu}",
            f"  RO   7850.0",
            "",
        ]

        # ── Властивості елементів (тип 41 — чотирикутна пластина) ──
        # Різна товщина для стінки та полиць
        prop_map = {
            'web':        (1, p.tw),
            'top_flange': (2, p.tf),
            'bot_flange': (3, p.tf),
        }
        lines += ["; --- Властивості пластин (тип 41) ---"]
        for name, (pid, t) in prop_map.items():
            lines += [
                f"ВЛАСТИВІСТЬ {pid}  ; {name}",
                f"  ТИП    41",
                f"  МАТ    1",
                f"  Т      {t:.6f}",
                "",
            ]

        # ── Вузли ──
        lines += ["; --- Вузли ---", "ВУЗЛИ"]
        for n in self.nodes:
            lines.append(f"  {n.id:6d}  {n.x:12.6f}  {n.y:12.6f}  {n.z:12.6f}")
        lines.append("")

        # ── Елементи ──
        lines += ["; --- Елементи ---", "ЕЛЕМЕНТИ"]
        for e in self.elements:
            pid = prop_map[e.part][0]
            ns = "  ".join(f"{n:6d}" for n in e.nodes)
            lines.append(f"  {e.id:6d}  {ns}  PROP={pid}")
        lines.append("")

        # ── Граничні умови (приклад: шарнірне закріплення на початку і кінці) ──
        # Вузли з x≈0 та x≈L
        support_start = [n.id for n in self.nodes if abs(n.x) < 1e-6]
        support_end   = [n.id for n in self.nodes if abs(n.x - p.L) < 1e-6]

        lines += [
            "; --- Граничні умови ---",
            "; Ліва опора: закріплення UX, UY, UZ",
        ]
        for nid in support_start:
            lines.append(f"  ЗВ'ЯЗОК {nid}  UX UY UZ")

        lines += ["; Права опора: закріплення UY, UZ (рухома по X)"]
        for nid in support_end:
            lines.append(f"  ЗВ'ЯЗОК {nid}  UY UZ")
        lines.append("")

        # ── Навантаження ──────────────────────────────────────────────────────
        #
        # Розподілене навантаження q = 1 кН/м² прикладається на верхню полицю
        # як еквівалентні вузлові сили F_i = q * A_i, де A_i — площа впливу вузла.
        #
        # Площа впливу вузла по осі X:
        #   - крайній вузол (x=0 або x=L): A_x = dx/2
        #   - внутрішній вузол:            A_x = (dx_left + dx_right) / 2
        # По осі Z (ширина): bf (вся ширина полиці припадає на один рядок вузлів
        #   у 2D-моделі; для 3D уточнюється)
        #
        # Два завантаження:
        #   LC1 — q по всьому прольоту  (x: 0 … L)
        #         Вузли верхньої полиці: top_flange, зовнішній ряд (y_outer)
        #   LC2 — q по лівій половині   (x: 0 … L/2)
        # ─────────────────────────────────────────────────────────────────────

        q = 1.0  # кН/м² — одиничне навантаження

        # Знаходимо вузли верхньої зовнішньої кромки полиці:
        # це вузли з максимальним Y (y_outer = hw/2 + tf) для кожної колонки X.
        # У нашій моделі вони були додані в циклі sign=+1, row_f=1.
        # Знайдемо їх: серед усіх вузлів знайдемо ті, що мають найбільший Y
        # для свого X-зрізу (з точністю до tf/10).

        # Групуємо вузли по X-coordinate
        x_to_nodes: Dict[float, List[Node]] = defaultdict(list)
        for n in self.nodes:
            x_to_nodes[round(n.x, 5)].append(n)

        # Для кожного X-зрізу вибираємо вузол з максимальним Y (верхня кромка полиці)
        x_sorted = sorted(x_to_nodes.keys())
        top_flange_nodes: List[Tuple[float, int]] = []  # (x, node_id)
        for x_val in x_sorted:
            top_node = max(x_to_nodes[x_val], key=lambda n: n.y)
            top_flange_nodes.append((x_val, top_node.id))

        # Обчислюємо площу впливу кожного вузла та відповідну силу
        def nodal_forces(top_nodes: List[Tuple[float, int]],
                         x_min: float, x_max: float) -> List[Tuple[int, float]]:
            """
            Повертає список (node_id, Fy) для вузлів у діапазоні [x_min, x_max].
            Fy < 0 — сила направлена вниз (глобальна вісь Y вниз).
            """
            forces = []
            xs = [xv for xv, _ in top_nodes]
            n_total = len(xs)

            for i, (x_val, nid) in enumerate(top_nodes):
                # Фільтр: вузол має бути у заданому діапазоні X
                if x_val < x_min - 1e-9 or x_val > x_max + 1e-9:
                    continue

                # Ширина смуги впливу по X
                dx_left  = (x_val - xs[i - 1]) / 2 if i > 0          else 0.0
                dx_right = (xs[i + 1] - x_val) / 2 if i < n_total - 1 else 0.0

                # Якщо вузол на межі зони завантаження — обрізаємо половину
                if abs(x_val - x_min) < 1e-9 and i > 0:
                    dx_left = 0.0   # лівий крайній вузол зони
                if abs(x_val - x_max) < 1e-9 and i < n_total - 1:
                    dx_right = 0.0  # правий крайній вузол зони

                dx = dx_left + dx_right
                if dx < 1e-12:
                    continue

                # Площа впливу: dx * bf (ширина полиці)
                A_influence = dx * p.bf
                F = -q * A_influence   # мінус — вниз по Y

                forces.append((nid, F))
            return forces

        # LC1: вся довжина
        forces_lc1 = nodal_forces(top_flange_nodes, 0.0, p.L)
        # LC2: ліва половина (0 … L/2)
        forces_lc2 = nodal_forces(top_flange_nodes, 0.0, p.L / 2)

        total_lc1 = sum(abs(f) for _, f in forces_lc1)
        total_lc2 = sum(abs(f) for _, f in forces_lc2)

        lines += [
            "; ─────────────────────────────────────────────────",
            "; --- Навантаження ---",
            f"; q = {q} кН/м² на верхню полицю (bf = {p.bf} м)",
            f"; LC1: весь проліт  — сумарна сила ≈ {total_lc1:.3f} кН",
            f"; LC2: ліва половина — сумарна сила ≈ {total_lc2:.3f} кН",
            "; ─────────────────────────────────────────────────",
            "",
        ]

        # LC1 — рівномірне по всьому прольоту
        lines += [
            "ЗАВАНТАЖЕННЯ 1",
            f"  НАЗВА 'LC1 — q=1 кН/м² по всьому прольоту (L={p.L} м)'",
        ]
        for nid, F in forces_lc1:
            lines.append(f"  ВУЗЛОВА СИЛА  {nid:6d}  FY  {F:.6f}")
        lines.append("")

        # LC2 — ліва половина прольоту
        lines += [
            "ЗАВАНТАЖЕННЯ 2",
            f"  НАЗВА 'LC2 — q=1 кН/м² по лівій половині прольоту (0…{p.L/2:.2f} м)'",
        ]
        for nid, F in forces_lc2:
            lines.append(f"  ВУЗЛОВА СИЛА  {nid:6d}  FY  {F:.6f}")
        lines.append("")

        # ── Кінець ──
        lines += ["КІНЕЦЬ", ""]

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

        print(f"  [OK] ЛІРА файл збережено: {filepath}")
        print(f"       Вузлів: {len(self.nodes):,} | Елементів: {len(self.elements):,}")


# ─────────────────────────────────────────────
#  Запис у DXF (геометрія для перегляду)
# ─────────────────────────────────────────────

class DXFWriter:
    """Мінімальний DXF-запис сітки (LINE-елементи)."""

    def __init__(self, nodes: List[Node], elements: List[Element]):
        self.nodes = {n.id: n for n in nodes}
        self.elements = elements

    def write(self, filepath: str):
        nd = self.nodes
        lines = [
            "0\nSECTION\n2\nHEADER\n0\nENDSEC",
            "0\nSECTION\n2\nENTITIES",
        ]

        color_map = {'web': 7, 'top_flange': 3, 'bot_flange': 5}

        for e in self.elements:
            color = color_map.get(e.part.split('_')[0] if 'flange' in e.part else e.part, 7)
            ns = [nd[i] for i in e.nodes]
            # 4 ребра чотирикутника
            for i in range(4):
                a, b = ns[i], ns[(i + 1) % 4]
                lines += [
                    f"0\nLINE\n8\n{e.part}\n62\n{color}",
                    f"10\n{a.x:.6f}\n20\n{a.y:.6f}\n30\n{a.z:.6f}",
                    f"11\n{b.x:.6f}\n21\n{b.y:.6f}\n31\n{b.z:.6f}",
                ]

        lines += ["0\nENDSEC\n0\nEOF"]

        with open(filepath, 'w') as f:
            f.write('\n'.join(lines))
        print(f"  [OK] DXF файл збережено:  {filepath}")


# ─────────────────────────────────────────────
#  Звіт моделі
# ─────────────────────────────────────────────

def print_summary(p: BeamParams, nodes: List[Node], elements: List[Element]):
    web_count = sum(1 for e in elements if e.part == 'web')
    flange_count = len(elements) - web_count
    print()
    print("=" * 55)
    print(f"  МОДЕЛЬ: {p.name}")
    print("=" * 55)
    print(f"  Довжина балки L  : {p.L} м")
    print(f"  Висота h1 / h2   : {p.h1*1000:.0f} / {p.h2*1000:.0f} мм")
    print(f"  Товщина стінки tw: {p.tw*1000:.1f} мм")
    print(f"  Товщина полиці tf: {p.tf*1000:.1f} мм")
    print(f"  Ширина полиці bf : {p.bf*1000:.0f} мм")
    print(f"  Сітка nx/nw/nf   : {p.nx} / {p.nw} / {p.nf}")
    print(f"  Вузлів           : {len(nodes)}")
    print(f"  Елементів усього : {len(elements)}")
    print(f"    - стінка       : {web_count}")
    print(f"    - полиці       : {flange_count}")
    print("=" * 55)


# ─────────────────────────────────────────────
#  Генерація однієї моделі
# ─────────────────────────────────────────────

def generate_model(p: BeamParams, output_dir: str = ".", dxf: bool = True):
    """Генерує одну модель і зберігає файли."""
    os.makedirs(output_dir, exist_ok=True)

    gen = IBeamMeshGenerator(p)
    nodes, elements = gen.generate()

    print_summary(p, nodes, elements)

    # ЛІРА файл
    lira_path = os.path.join(output_dir, f"{p.name}.txt")
    LiraWriter(p, nodes, elements).write(lira_path)

    # DXF файл
    if dxf:
        dxf_path = os.path.join(output_dir, f"{p.name}.dxf")
        DXFWriter(nodes, elements).write(dxf_path)

    return nodes, elements


# ─────────────────────────────────────────────
#  Пакетний режим
# ─────────────────────────────────────────────

def run_batch(output_dir: str = "batch_models"):
    """
    Приклад пакетної генерації кількох моделей із різними параметрами.
    Відредагуйте список MODELS для своїх задач.
    """

    MODELS = [
        # ── Варіація сітки ──────────────────────────────────────────
        BeamParams(
            L=8.0, h1=0.6, h2=1.0, tw=0.012, tf=0.016, bf=0.3,
            nx=8,  nw=4, nf=3,
            name="model_coarse"   # груба сітка
        ),
        BeamParams(
            L=8.0, h1=0.6, h2=1.0, tw=0.012, tf=0.016, bf=0.3,
            nx=16, nw=8, nf=4,
            name="model_medium"   # середня сітка
        ),
        BeamParams(
            L=8.0, h1=0.6, h2=1.0, tw=0.012, tf=0.016, bf=0.3,
            nx=32, nw=16, nf=6,
            name="model_fine"     # дрібна сітка
        ),

        # ── Варіація висоти балки ────────────────────────────────────
        BeamParams(
            L=10.0, h1=0.4, h2=0.8, tw=0.010, tf=0.014, bf=0.25,
            nx=20, nw=6, nf=4,
            name="model_h400_800"
        ),
        BeamParams(
            L=10.0, h1=0.6, h2=1.2, tw=0.014, tf=0.020, bf=0.35,
            nx=20, nw=8, nf=4,
            name="model_h600_1200"
        ),

        # ── Варіація товщини стінки та полиць ────────────────────────
        BeamParams(
            L=6.0, h1=0.5, h2=0.9, tw=0.008, tf=0.012, bf=0.25,
            nx=12, nw=6, nf=3,
            name="model_thin_walls"
        ),
        BeamParams(
            L=6.0, h1=0.5, h2=0.9, tw=0.020, tf=0.028, bf=0.30,
            nx=12, nw=6, nf=3,
            name="model_thick_walls"
        ),
    ]

    print(f"\nПакетна генерація: {len(MODELS)} моделей → '{output_dir}/'")
    print("-" * 55)

    for i, params in enumerate(MODELS, 1):
        print(f"\n[{i}/{len(MODELS)}] Генерую: {params.name}")
        generate_model(params, output_dir=output_dir, dxf=True)

    print(f"\n✓ Готово! Всі файли збережено у папці '{output_dir}/'")


# ─────────────────────────────────────────────
#  Інтерактивний режим
# ─────────────────────────────────────────────

def run_interactive():
    print("\n" + "=" * 55)
    print("  Генератор двотаврової балки змінної висоти (СЕ)")
    print("=" * 55)
    print("  Введіть параметри (Enter = значення за замовч.)\n")

    def ask(prompt, default):
        val = input(f"  {prompt} [{default}]: ").strip()
        return type(default)(val) if val else default

    p = BeamParams(
        L    = ask("Довжина балки L, м",          6.0),
        h1   = ask("Висота h1 (початок), м",      0.6),
        h2   = ask("Висота h2 (кінець), м",       1.0),
        tw   = ask("Товщина стінки tw, м",        0.012),
        tf   = ask("Товщина полиці tf, м",        0.016),
        bf   = ask("Ширина полиці bf, м",         0.3),
        nx   = ask("Елементів по довжині nx",     10),
        nw   = ask("Елементів по висоті стінки nw", 4),
        nf   = ask("Елементів по полиці nf",      3),
        name = ask("Назва моделі",                "ibeam_model"),
    )

    out_dir = ask("Папка виводу", "output")
    dxf_flag = ask("Генерувати DXF? (1=так/0=ні)", 1)

    generate_model(p, output_dir=out_dir, dxf=bool(dxf_flag))
    print(f"\n✓ Готово!")


# ─────────────────────────────────────────────
#  Точка входу
# ─────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Генератор сітки СЕ двотаврової балки змінної висоти для ЛІРА САПР"
    )
    parser.add_argument("--batch",  action="store_true",
                        help="Пакетна генерація заздалегідь визначених моделей")
    parser.add_argument("--out",    default="output",
                        help="Папка для виводу файлів (default: output)")
    parser.add_argument(
        # Швидке задання параметрів без інтерактиву
        "--L",  type=float, help="Довжина балки, м")
    parser.add_argument("--h1", type=float, help="Висота h1, м")
    parser.add_argument("--h2", type=float, help="Висота h2, м")
    parser.add_argument("--tw", type=float, help="Товщина стінки, м")
    parser.add_argument("--tf", type=float, help="Товщина полиці, м")
    parser.add_argument("--bf", type=float, help="Ширина полиці, м")
    parser.add_argument("--nx", type=int,   help="Елементів по довжині")
    parser.add_argument("--nw", type=int,   help="Елементів по висоті стінки")
    parser.add_argument("--nf", type=int,   help="Елементів по ширині полиці")
    parser.add_argument("--name", type=str, default="ibeam_model", help="Назва моделі")
    parser.add_argument("--no-dxf", action="store_true", help="Не генерувати DXF")

    args = parser.parse_args()

    if args.batch:
        run_batch(output_dir=args.out)

    elif any([args.L, args.h1, args.h2, args.tw, args.tf,
              args.bf, args.nx, args.nw, args.nf]):
        # Командний рядок — окрема модель
        p = BeamParams(
            L    = args.L  or 6.0,
            h1   = args.h1 or 0.6,
            h2   = args.h2 or 1.0,
            tw   = args.tw or 0.012,
            tf   = args.tf or 0.016,
            bf   = args.bf or 0.3,
            nx   = args.nx or 10,
            nw   = args.nw or 4,
            nf   = args.nf or 3,
            name = args.name,
        )
        generate_model(p, output_dir=args.out, dxf=not args.no_dxf)

    else:
        run_interactive()
