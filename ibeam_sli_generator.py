"""
================================================================
  Генератор двотаврової балки змінної висоти → ЛІРА САПР .sli
================================================================

Система координат:
  X — ширина полиці  (поперечний напрямок)
  Y — вздовж осі балки (повздовжній напрямок)
  Z — висота перерізу (вертикальний напрямок)

Структура балки:
  - Верхня полиця:  Z = h_w(y)/2  (один пояс на межі зі стінкою)
  - Стінка:         Z = -h_w(y)/2 .. h_w(y)/2
  - Нижня полиця:   Z = -h_w(y)/2 (один пояс на межі зі стінкою)

Матеріали:
  Material 1 — полиці (H = tf)
  Material 2 — стінка (H = tw)

Навантаження:
  LC1 — q кН/м² по всьому прольоту (верхній пояс)
  LC2 — q кН/м² по лівій половині  (верхній пояс)

Конвертація в .sli — див. sli_writer.py

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
        self._top_flange: Dict[Tuple[int, int], int] = {}  # (j_y, i_x) → node_id

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
        # Верхня: Z = hw/2   (на межі зі стінкою)
        # Нижня:  Z = -hw/2  (на межі зі стінкою)

        x_cuts = [-p.bf/2 + p.bf * i / (2 * p.nx) for i in range(2 * p.nx + 1)]

        for sign, label in [(+1, 'top'), (-1, 'bot')]:
            fl_grid: Dict[Tuple[int,int], int] = {}   # (j_y, i_x) → node_id

            for j, y in enumerate(y_cuts):
                hw = p.hw(y)
                # Z координата полиці (на межі зі стінкою)
                if sign == +1:
                    z_inner = hw / 2           # межа зі стінкою
                else:
                    z_inner = -hw / 2

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


            # Зберігаємо вузли верхньої полиці для навантаження
            if sign == +1:
                for j in range(p.ny + 1):
                    for i in range(2 * p.nx + 1):
                        self._top_flange[(j, i)] = fl_grid[(j, i, 'inner')]

            # Елементи полиці
            for j in range(p.ny):
                for i in range(2 * p.nx):
                    n1 = fl_grid[(j,   i,   'inner')]
                    n2 = fl_grid[(j+1, i,   'inner')]
                    n3 = fl_grid[(j+1, i+1, 'inner')]
                    n4 = fl_grid[(j,   i+1, 'inner')]
                    self._q(n1, n2, n3, n4, mat=1)  # полиця → mat 1


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
        Вузлові сили на ВСІХ вузлах верхньої полиці в діапазоні [y_min, y_max].
        F = -q * dx * dy  (вантажна площа кожного вузла, мінус = вниз по Z)
        NDOF=3 відповідає Z у ЛІРА sli-форматі.
        """
        p = self.p
        y_cuts = [p.L * j / p.ny for j in range(p.ny + 1)]
        x_cuts = [-p.bf/2 + p.bf * i / (2 * p.nx) for i in range(2 * p.nx + 1)]

        forces = []
        for j in range(p.ny + 1):
            y = y_cuts[j]
            if y < y_min - 1e-9 or y > y_max + 1e-9:
                continue

            # Вантажна довжина по Y
            dy_l = (y - y_cuts[j-1]) / 2 if j > 0    else 0.0
            dy_r = (y_cuts[j+1] - y) / 2 if j < p.ny else 0.0
            if abs(y - y_min) < 1e-9 and j > 0:
                dy_l = 0.0
            if abs(y - y_max) < 1e-9 and j < p.ny:
                dy_r = 0.0
            dy = dy_l + dy_r
            if dy < 1e-12:
                continue

            for i in range(2 * p.nx + 1):
                # Вантажна ширина по X
                dx_l = (x_cuts[i] - x_cuts[i-1]) / 2 if i > 0          else 0.0
                dx_r = (x_cuts[i+1] - x_cuts[i]) / 2 if i < 2 * p.nx   else 0.0
                dx = dx_l + dx_r
                if dx < 1e-12:
                    continue

                nid = self._top_flange[(j, i)]
                F = -p.q * dx * dy   # кН (q в кН/м²)
                forces.append((nid, F))

        return forces


# ──────────────────────────────────────────────────────────────
#  Генерація однієї моделі
# ──────────────────────────────────────────────────────────────

def generate(p: BeamParams, output_dir: str = ".") -> str:
    """Будує сітку, обчислює навантаження, зберігає .sli. Повертає шлях до файлу."""
    from sli_writer import write_sli

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
