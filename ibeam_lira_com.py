"""
===============================================================
  Двотаврова балка змінної висоти → ЛІРА САПР через COM/OLE API
===============================================================

ВИМОГИ:
  pip install pywin32

ЗАПУСК (тільки Windows, з встановленою ЛІРА САПР):
  python ibeam_lira_com.py                  # інтерактивний режим
  python ibeam_lira_com.py --batch          # пакетна генерація 7 моделей
  python ibeam_lira_com.py --L 8 --h1 0.6 --h2 1.0 --nx 16 --nw 8

ЩО РОБИТЬ СКРИПТ:
  1. Запускає ЛІРА САПР (або підключається до запущеної)
  2. Створює новий проект
  3. Додає вузли, елементи (тип 41 — пластини), матеріал, властивості
  4. Задає граничні умови (шарнірне закріплення)
  5. Додає два завантаження:
       LC1 — q=1 кН/м² по всьому прольоту
       LC2 — q=1 кН/м² по лівій половині прольоту
  6. Зберігає .lir файл

АРХІТЕКТУРА ЛІРА COM-API:
  LirApp   → головний об'єкт програми
    .Tasks  → колекція задач
      .Add  → нова задача (повертає Task)
    Task
      .Nodes     → колекція вузлів
      .Elements  → колекція елементів
      .Materials → колекція матеріалів
      .Loads     → завантаження
      .Constraints → в'язі
"""

import sys
import os
import argparse
from collections import defaultdict
from dataclasses import dataclass
from typing import List, Tuple, Dict, Optional

# ─────────────────────────────────────────────────────────────
#  Імпорт win32com (тільки Windows)
# ─────────────────────────────────────────────────────────────

def _check_platform():
    if sys.platform != "win32":
        print("=" * 60)
        print("  УВАГА: COM/OLE API доступний тільки на Windows!")
        print("  На поточній платформі скрипт запущено в режимі")
        print("  'dry run' — модель будується в пам'яті, але")
        print("  з'єднання з ЛІРА не відбувається.")
        print("=" * 60)
        return False
    return True

IS_WINDOWS = _check_platform()

if IS_WINDOWS:
    try:
        import win32com.client
        import pywintypes
    except ImportError:
        print("Встановіть pywin32:  pip install pywin32")
        sys.exit(1)


# ─────────────────────────────────────────────────────────────
#  Структури даних (спільні з ibeam_generator.py)
# ─────────────────────────────────────────────────────────────

@dataclass
class BeamParams:
    L:    float = 6.0     # довжина балки, м
    h1:   float = 0.6     # висота на початку, м
    h2:   float = 1.0     # висота на кінці, м
    tw:   float = 0.012   # товщина стінки, м
    tf:   float = 0.016   # товщина полиці, м
    bf:   float = 0.3     # ширина полиці, м
    nx:   int   = 10      # елементів по довжині
    nw:   int   = 4       # елементів по висоті стінки
    nf:   int   = 3       # елементів по ширині полиці
    E:    float = 2.06e8  # модуль пружності, кН/м²  (кН + м → кПа)
    nu:   float = 0.3     # коефіцієнт Пуассона
    rho:  float = 7850.0  # питома вага, кг/м³
    q:    float = 1.0     # інтенсивність розподіленого навантаження, кН/м²
    name: str   = "ibeam_model"
    save_dir: str = "."   # папка для збереження .lir файлу

    def web_height(self, x: float) -> float:
        h = self.h1 + (self.h2 - self.h1) * x / self.L
        return h - 2 * self.tf

    def total_height(self, x: float) -> float:
        return self.h1 + (self.h2 - self.h1) * x / self.L


@dataclass
class Node:
    id: int
    x:  float
    y:  float
    z:  float = 0.0


@dataclass
class Element:
    id:        int
    nodes:     List[int]
    thickness: float
    part:      str   # 'web' | 'top_flange' | 'bot_flange'


# ─────────────────────────────────────────────────────────────
#  Генерація сітки (незалежна від COM)
# ─────────────────────────────────────────────────────────────

class IBeamMesh:
    def __init__(self, p: BeamParams):
        self.p = p
        self.nodes:    List[Node]    = []
        self.elements: List[Element] = []
        self._nid = 1
        self._eid = 1

    def _node(self, x, y, z=0.0) -> int:
        nid = self._nid
        self.nodes.append(Node(nid, round(x, 6), round(y, 6), round(z, 6)))
        self._nid += 1
        return nid

    def _elem(self, n1, n2, n3, n4, t, part) -> int:
        eid = self._eid
        self.elements.append(Element(eid, [n1, n2, n3, n4], t, part))
        self._eid += 1
        return eid

    def build(self):
        p = self.p
        x_cols = [p.L * i / p.nx for i in range(p.nx + 1)]

        # ── Стінка ──
        web = {}
        for ic, x in enumerate(x_cols):
            hw  = p.web_height(x)
            y0  = -hw / 2
            for ir in range(p.nw + 1):
                y = y0 + hw * ir / p.nw
                web[(ic, ir)] = self._node(x, y)

        for ic in range(p.nx):
            for ir in range(p.nw):
                self._elem(web[(ic, ir)], web[(ic+1, ir)],
                           web[(ic+1, ir+1)], web[(ic, ir+1)],
                           p.tw, 'web')

        # ── Полиці ──
        for sign, label in [(+1, 'top'), (-1, 'bot')]:
            fl = {}
            for ic, x in enumerate(x_cols):
                hw = p.web_height(x)
                fl[(ic, 0)] = web[(ic, p.nw)] if sign == +1 else web[(ic, 0)]
                y_outer = sign * (hw / 2 + p.tf)
                fl[(ic, 1)] = self._node(x, y_outer)

            for ic in range(p.nx):
                self._elem(fl[(ic, 0)], fl[(ic+1, 0)],
                           fl[(ic+1, 1)], fl[(ic, 1)],
                           p.bf, f'{label}_flange')

        return self.nodes, self.elements

    # ── Допоміжні вибірки ──────────────────────────────────

    def top_flange_nodes(self) -> List[Tuple[float, int]]:
        """Вузли верхньої зовнішньої кромки полиці: [(x, node_id), ...]."""
        by_x: Dict[float, List[Node]] = defaultdict(list)
        for n in self.nodes:
            by_x[round(n.x, 5)].append(n)
        result = []
        for x_val in sorted(by_x):
            top = max(by_x[x_val], key=lambda n: n.y)
            result.append((x_val, top.id))
        return result

    def support_nodes_start(self) -> List[int]:
        return [n.id for n in self.nodes if abs(n.x) < 1e-6]

    def support_nodes_end(self) -> List[int]:
        return [n.id for n in self.nodes if abs(n.x - self.p.L) < 1e-6]

    def nodal_forces(self, x_min: float, x_max: float) -> List[Tuple[int, float]]:
        """Вузлові сили F = q * A_influence (FY < 0 — вниз)."""
        top = self.top_flange_nodes()
        xs  = [xv for xv, _ in top]
        forces = []
        for i, (x_val, nid) in enumerate(top):
            if x_val < x_min - 1e-9 or x_val > x_max + 1e-9:
                continue
            dx_l = (x_val - xs[i-1]) / 2 if i > 0          else 0.0
            dx_r = (xs[i+1] - x_val) / 2 if i < len(xs) - 1 else 0.0
            if abs(x_val - x_min) < 1e-9 and i > 0:
                dx_l = 0.0
            if abs(x_val - x_max) < 1e-9 and i < len(xs) - 1:
                dx_r = 0.0
            dx = dx_l + dx_r
            if dx < 1e-12:
                continue
            forces.append((nid, -self.p.q * dx * self.p.bf))
        return forces


# ─────────────────────────────────────────────────────────────
#  ЛІРА COM/OLE — обгортка
# ─────────────────────────────────────────────────────────────

# ProgID для різних версій ЛІРА САПР
# Якщо з'єднання не відбувається — спробуйте наступний ProgID
LIRA_PROG_IDS = [
    "LiraSapr.Application.2024",        # ЛІРА САПР 2013–2024 (найпоширеніший)
    "LiraW.Application",       # старіші версії
    "Lira.Application.1",      # альтернативний суфікс
]

# Константи ЛІРА API
class LiraConst:
    # Типи елементів
    ELEM_TYPE_41  = 41    # чотирикутна пластина Kirchhoff/Mindlin

    # Ступені свободи (в'язі) — бітова маска
    # У ЛІРА використовується 6 DOF: UX UY UZ FX FY FZ
    DOF_UX = 1
    DOF_UY = 2
    DOF_UZ = 4
    DOF_FX = 8
    DOF_FY = 16
    DOF_FZ = 32

    # Прапорці напрямку сили
    FORCE_FY = 2   # сила по Y (глобальна)

    # Одиниці в ЛІРА за замовч.: кН + м
    UNITS_KN_M = 1


class LiraComSession:
    """
    Обгортка над COM-об'єктом ЛІРА САПР.

    Використання:
        with LiraComSession(visible=True) as lira:
            lira.create_task("MyBeam")
            lira.add_nodes(nodes)
            ...
    """

    def __init__(self, visible: bool = True):
        self.visible  = visible
        self._app     = None   # LirApp COM-об'єкт
        self._task    = None   # поточна задача
        self._task_id: Optional[int] = None

    # ── Підключення / відключення ──────────────────────────

    def connect(self):
        """Запускає ЛІРА або підключається до вже запущеної."""
        if not IS_WINDOWS:
            print("  [dry-run] connect() — пропущено (не Windows)")
            return self

        last_err = None
        for prog_id in LIRA_PROG_IDS:
            try:
                # Спробувати підключитись до запущеної копії
                try:
                    self._app = win32com.client.GetActiveObject(prog_id)
                    print(f"  [COM] Підключено до запущеної ЛІРА ({prog_id})")
                except pywintypes.com_error:
                    # Запустити нову копію
                    self._app = win32com.client.Dispatch(prog_id)
                    print(f"  [COM] Запущено ЛІРА ({prog_id})")

                if self.visible:
                    self._app.Visible = True
                return self

            except Exception as e:
                last_err = e
                continue

        raise RuntimeError(
            f"Не вдалося підключитись до ЛІРА САПР.\n"
            f"Перевірте:\n"
            f"  1. ЛІРА САПР встановлена\n"
            f"  2. COM-сервер зареєстрований (regsvr32 або перевстановити ЛІРА)\n"
            f"  3. Версія сумісна з ProgID: {LIRA_PROG_IDS}\n"
            f"Остання помилка: {last_err}"
        )

    def disconnect(self):
        self._task = None
        self._app  = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *_):
        self.disconnect()

    # ── Утиліта виклику COM-методів з обробкою помилок ────

    def _call(self, func_name: str, *args):
        if not IS_WINDOWS:
            return None   # dry-run
        try:
            return func_name(*args)
        except Exception as e:
            raise RuntimeError(f"COM-помилка '{func_name}': {e}") from e

    # ── Задача ────────────────────────────────────────────

    def create_task(self, name: str) -> None:
        """Створює нову задачу ЛІРА і робить її активною."""
        if not IS_WINDOWS:
            print(f"  [dry-run] create_task('{name}')")
            return

        tasks = self._app.Tasks
        self._task = tasks.Add(name)
        self._task_id = self._task.Id
        print(f"  [COM] Задача створена: '{name}' (id={self._task_id})")

    def save_task(self, filepath: str) -> None:
        """Зберігає задачу у .lir файл."""
        if not IS_WINDOWS:
            print(f"  [dry-run] save_task → {filepath}")
            return
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        self._task.SaveAs(filepath)
        print(f"  [COM] Збережено: {filepath}")

    # ── Матеріал ──────────────────────────────────────────

    def add_material(self, mat_id: int, E: float, nu: float, rho: float) -> None:
        """
        Додає ізотропний матеріал.
        E   — модуль пружності, кН/м²
        nu  — коефіцієнт Пуассона
        rho — питома вага, кг/м³
        """
        if not IS_WINDOWS:
            print(f"  [dry-run] add_material(id={mat_id}, E={E:.2e}, nu={nu})")
            return

        mats = self._task.Materials
        mat  = mats.Add(mat_id)
        # Властивості залежать від версії API; типові імена:
        mat.ElasticModulus  = E
        mat.PoissonRatio    = nu
        mat.Density         = rho
        print(f"  [COM] Матеріал {mat_id}: E={E:.2e} кН/м², nu={nu}")

    # ── Властивості пластини ──────────────────────────────

    def add_plate_property(self, prop_id: int, mat_id: int,
                           thickness: float, label: str = "") -> None:
        """
        Додає властивості пластинчастого елемента (тип 41).
        thickness — товщина пластини, м
        """
        if not IS_WINDOWS:
            print(f"  [dry-run] add_plate_property(id={prop_id}, t={thickness*1000:.1f} мм) [{label}]")
            return

        props = self._task.Properties
        prop  = props.Add(prop_id)
        prop.ElementType = LiraConst.ELEM_TYPE_41
        prop.MaterialId  = mat_id
        prop.Thickness   = thickness
        print(f"  [COM] Властивість {prop_id} [{label}]: тип 41, t={thickness*1000:.1f} мм")

    # ── Вузли ─────────────────────────────────────────────

    def add_nodes(self, nodes: List[Node]) -> None:
        """Масово додає вузли. Координати в метрах."""
        if not IS_WINDOWS:
            print(f"  [dry-run] add_nodes({len(nodes)} вузлів)")
            return

        nd_coll = self._task.Nodes
        for n in nodes:
            nd_coll.Add(n.id, n.x, n.y, n.z)
        print(f"  [COM] Додано {len(nodes)} вузлів")

    # ── Елементи ──────────────────────────────────────────

    def add_elements(self, elements: List[Element],
                     prop_map: Dict[str, int]) -> None:
        """
        Масово додає чотирикутні пластини (тип 41).
        prop_map: {'web': prop_id, 'top_flange': prop_id, ...}
        """
        if not IS_WINDOWS:
            print(f"  [dry-run] add_elements({len(elements)} елементів)")
            return

        el_coll = self._task.Elements
        for e in elements:
            pid = prop_map[e.part]
            # Add(id, type, n1, n2, n3, n4, prop_id)
            el_coll.Add(e.id, LiraConst.ELEM_TYPE_41,
                        e.nodes[0], e.nodes[1],
                        e.nodes[2], e.nodes[3],
                        pid)
        print(f"  [COM] Додано {len(elements)} елементів")

    # ── В'язі (граничні умови) ────────────────────────────

    def add_constraints(self,
                        node_ids_pinned: List[int],
                        node_ids_roller: List[int]) -> None:
        """
        Ліва опора  (pinned): UX + UY + UZ закріплено
        Права опора (roller): UY + UZ закріплено
        """
        if not IS_WINDOWS:
            print(f"  [dry-run] add_constraints("
                  f"pinned={len(node_ids_pinned)}, roller={len(node_ids_roller)})")
            return

        bc = self._task.Constraints
        dof_pinned = LiraConst.DOF_UX | LiraConst.DOF_UY | LiraConst.DOF_UZ
        dof_roller =                    LiraConst.DOF_UY | LiraConst.DOF_UZ

        for nid in node_ids_pinned:
            bc.Add(nid, dof_pinned)
        for nid in node_ids_roller:
            bc.Add(nid, dof_roller)

        print(f"  [COM] Граничні умови: "
              f"{len(node_ids_pinned)} шарнірних + {len(node_ids_roller)} рухомих")

    # ── Завантаження ──────────────────────────────────────

    def add_load_case(self, lc_id: int, lc_name: str,
                      forces: List[Tuple[int, float]]) -> None:
        """
        Додає завантаження як набір вузлових сил FY.
        forces: [(node_id, Fy_kN), ...]  Fy < 0 → вниз
        """
        if not IS_WINDOWS:
            total = sum(abs(f) for _, f in forces)
            print(f"  [dry-run] add_load_case(LC{lc_id} '{lc_name}', "
                  f"{len(forces)} сил, сума={total:.3f} кН)")
            return

        loads   = self._task.Loads
        lc      = loads.AddCase(lc_id, lc_name)
        for nid, fy in forces:
            # AddNodalForce(node_id, direction, value)
            lc.AddNodalForce(nid, LiraConst.FORCE_FY, fy)

        total = sum(abs(f) for _, f in forces)
        print(f"  [COM] LC{lc_id} '{lc_name}': "
              f"{len(forces)} вузл. сил, Σ|F|={total:.3f} кН")


# ─────────────────────────────────────────────────────────────
#  Головна функція — будує одну модель в ЛІРА
# ─────────────────────────────────────────────────────────────

def build_model_in_lira(p: BeamParams,
                        session: Optional[LiraComSession] = None) -> None:
    """
    Будує повну модель двотаврової балки в ЛІРА САПР через COM.

    Якщо session передано — використовує існуючу (корисно для пакетного режиму).
    Якщо session=None — відкриває нову і закриває після завершення.
    """

    print(f"\n{'='*60}")
    print(f"  Будую модель: {p.name}")
    print(f"  L={p.L} м | h1={p.h1*1000:.0f}/{p.h2*1000:.0f} мм "
          f"| tw={p.tw*1000:.0f} | tf={p.tf*1000:.0f} | bf={p.bf*1000:.0f} мм")
    print(f"  Сітка: nx={p.nx}, nw={p.nw}, nf={p.nf}")
    print(f"{'='*60}")

    # ── 1. Генерація сітки ──────────────────────────────
    mesh = IBeamMesh(p)
    nodes, elements = mesh.build()
    print(f"  Сітка: {len(nodes)} вузлів, {len(elements)} елементів")

    # ── 2. Визначення груп елементів і prop_map ──────────
    prop_map = {
        'web':        1,
        'top_flange': 2,
        'bot_flange': 3,
    }

    # ── 3. Обчислення навантажень ─────────────────────────
    forces_lc1 = mesh.nodal_forces(0.0, p.L)           # весь проліт
    forces_lc2 = mesh.nodal_forces(0.0, p.L / 2)       # ліва половина

    # ── 4. Передача в ЛІРА ───────────────────────────────
    own_session = session is None
    if own_session:
        session = LiraComSession(visible=True)
        session.connect()

    try:
        # Нова задача
        save_path = os.path.join(
            os.path.abspath(p.save_dir), f"{p.name}.lir"
        )
        session.create_task(p.name)

        # Матеріал #1 — сталь
        session.add_material(1, p.E, p.nu, p.rho)

        # Властивості пластин
        session.add_plate_property(1, 1, p.tw,  label="стінка")
        session.add_plate_property(2, 1, p.tf,  label="верхня полиця")
        session.add_plate_property(3, 1, p.tf,  label="нижня полиця")

        # Вузли та елементи
        session.add_nodes(nodes)
        session.add_elements(elements, prop_map)

        # Граничні умови
        session.add_constraints(
            node_ids_pinned = mesh.support_nodes_start(),
            node_ids_roller = mesh.support_nodes_end(),
        )

        # Завантаження
        session.add_load_case(
            1,
            f"LC1 — q={p.q} кН/м² по всьому прольоту",
            forces_lc1,
        )
        session.add_load_case(
            2,
            f"LC2 — q={p.q} кН/м² по лівій половині (0…{p.L/2:.2f} м)",
            forces_lc2,
        )

        # Збереження
        session.save_task(save_path)
        print(f"\n  ✓ Готово → {save_path}")

    finally:
        if own_session:
            session.disconnect()


# ─────────────────────────────────────────────────────────────
#  Пакетний режим
# ─────────────────────────────────────────────────────────────

def run_batch(output_dir: str = "lira_models"):
    """Генерує 7 моделей в одній сесії ЛІРА (ефективніше)."""

    MODELS = [
        BeamParams(L=8.0, h1=0.6, h2=1.0, tw=0.012, tf=0.016, bf=0.30,
                   nx=8,  nw=4, nf=3, name="model_coarse",      save_dir=output_dir),
        BeamParams(L=8.0, h1=0.6, h2=1.0, tw=0.012, tf=0.016, bf=0.30,
                   nx=16, nw=8, nf=4, name="model_medium",      save_dir=output_dir),
        BeamParams(L=8.0, h1=0.6, h2=1.0, tw=0.012, tf=0.016, bf=0.30,
                   nx=32, nw=16,nf=6, name="model_fine",        save_dir=output_dir),
        BeamParams(L=10., h1=0.4, h2=0.8, tw=0.010, tf=0.014, bf=0.25,
                   nx=20, nw=6, nf=4, name="model_h400_800",    save_dir=output_dir),
        BeamParams(L=10., h1=0.6, h2=1.2, tw=0.014, tf=0.020, bf=0.35,
                   nx=20, nw=8, nf=4, name="model_h600_1200",   save_dir=output_dir),
        BeamParams(L=6.0, h1=0.5, h2=0.9, tw=0.008, tf=0.012, bf=0.25,
                   nx=12, nw=6, nf=3, name="model_thin_walls",  save_dir=output_dir),
        BeamParams(L=6.0, h1=0.5, h2=0.9, tw=0.020, tf=0.028, bf=0.30,
                   nx=12, nw=6, nf=3, name="model_thick_walls", save_dir=output_dir),
    ]

    print(f"\nПакетна генерація: {len(MODELS)} моделей → '{output_dir}/'")

    # Відкриваємо ЛІРА один раз для всіх моделей
    with LiraComSession(visible=True) as session:
        for i, params in enumerate(MODELS, 1):
            print(f"\n[{i}/{len(MODELS)}]")
            build_model_in_lira(params, session=session)

    print(f"\n✓ Всі {len(MODELS)} моделей збережено у '{output_dir}/'")


# ─────────────────────────────────────────────────────────────
#  Інтерактивний режим
# ─────────────────────────────────────────────────────────────

def run_interactive():
    print("\n" + "="*60)
    print("  Двотаврова балка → ЛІРА САПР (COM/OLE API)")
    print("="*60)
    print("  Введіть параметри (Enter = значення за замовч.)\n")

    def ask(prompt, default):
        val = input(f"  {prompt} [{default}]: ").strip()
        return type(default)(val) if val else default

    p = BeamParams(
        L    = ask("Довжина L, м",             6.0),
        h1   = ask("Висота h1 (початок), м",   0.6),
        h2   = ask("Висота h2 (кінець), м",    1.0),
        tw   = ask("Товщина стінки tw, м",     0.012),
        tf   = ask("Товщина полиці tf, м",     0.016),
        bf   = ask("Ширина полиці bf, м",      0.3),
        nx   = ask("Ел-тів по довжині nx",     10),
        nw   = ask("Ел-тів по висоті стінки nw", 4),
        nf   = ask("Ел-тів по полиці nf",     3),
        q    = ask("Навантаження q, кН/м²",   1.0),
        name = ask("Назва моделі",             "ibeam_model"),
        save_dir = ask("Папка збереження",     "lira_output"),
    )

    build_model_in_lira(p)


# ─────────────────────────────────────────────────────────────
#  Точка входу
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Генератор двотаврової балки → ЛІРА САПР (COM/OLE API)"
    )
    parser.add_argument("--batch",   action="store_true",
                        help="Пакетна генерація 7 моделей")
    parser.add_argument("--out",     default="lira_models",
                        help="Папка для .lir файлів")
    parser.add_argument("--L",       type=float)
    parser.add_argument("--h1",      type=float)
    parser.add_argument("--h2",      type=float)
    parser.add_argument("--tw",      type=float)
    parser.add_argument("--tf",      type=float)
    parser.add_argument("--bf",      type=float)
    parser.add_argument("--nx",      type=int)
    parser.add_argument("--nw",      type=int)
    parser.add_argument("--nf",      type=int)
    parser.add_argument("--q",       type=float, default=1.0)
    parser.add_argument("--name",    type=str,   default="ibeam_model")

    args = parser.parse_args()

    if args.batch:
        run_batch(output_dir=args.out)

    elif any([args.L, args.h1, args.h2, args.tw, args.tf,
              args.bf, args.nx, args.nw, args.nf]):
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
            q    = args.q,
            name = args.name,
            save_dir = args.out,
        )
        build_model_in_lira(p)

    else:
        run_interactive()
