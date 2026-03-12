"""
Скруглення (fillet) для ламаної лінії.
"""

import math
from dataclasses import dataclass
from typing import List, Tuple, Union

from meander_generator import Point

Coord = Union[Tuple[float, float], Point]


def _to_xy(p) -> Tuple[float, float]:
    if hasattr(p, 'x') and hasattr(p, 'y'):
        return (p.x, p.y)
    return (float(p[0]), float(p[1]))


@dataclass
class FilletResult:
    R1: Point
    R2: Point
    RC: Point


def compute_fillet(a: Coord, b: Coord, c: Coord, radius: float) -> FilletResult:
    """Обчислює скруглення для одного кута ABC.

    Args:
        a: попередня точка (tuple або Point).
        b: точка кута (tuple або Point).
        c: наступна точка (tuple або Point).
        radius: радіус скруглення.

    Returns:
        FilletResult з полями R1, R2, RC.
    """
    ax, ay = _to_xy(a)
    bx, by = _to_xy(b)
    cx, cy = _to_xy(c)

    # Вектори від B до A та від B до C
    v1x, v1y = ax - bx, ay - by
    v2x, v2y = cx - bx, cy - by

    len1 = math.hypot(v1x, v1y)
    len2 = math.hypot(v2x, v2y)

    if len1 == 0 or len2 == 0:
        raise ValueError("Дві точки співпадають — неможливо обчислити fillet.")

    # Одиничні вектори
    u1x, u1y = v1x / len1, v1y / len1
    u2x, u2y = v2x / len2, v2y / len2

    # Кут між напрямками
    dot = max(-1.0, min(1.0, u1x * u2x + u1y * u2y))
    angle = math.acos(dot)
    half = angle / 2.0

    if abs(math.sin(half)) < 1e-12:
        raise ValueError("Точки колінеарні — неможливо обчислити fillet.")

    # Відстань від вершини до точки дотику
    d = radius / math.tan(half)

    r1 = Point(round(bx + d * u1x, 10), round(by + d * u1y, 10))
    r2 = Point(round(bx + d * u2x, 10), round(by + d * u2y, 10))

    # Центр кола — на бісектрисі
    bisect_x, bisect_y = u1x + u2x, u1y + u2y
    bisect_len = math.hypot(bisect_x, bisect_y)
    bisect_x, bisect_y = bisect_x / bisect_len, bisect_y / bisect_len

    dist_center = radius / math.sin(half)
    rc = Point(round(bx + dist_center * bisect_x, 10),
               round(by + dist_center * bisect_y, 10))

    return FilletResult(R1=r1, R2=r2, RC=rc)


def compute_fillets(points, radius: float):
    """Обчислює скруглення для всіх кутів ламаної.

    Returns:
        (перша точка, список FilletResult, остання точка).
    """
    if len(points) < 3:
        return (points[0], [], points[-1])

    fillets = [
        compute_fillet(points[i - 1], points[i], points[i + 1], radius)
        for i in range(1, len(points) - 1)
    ]

    return (points[0], fillets, points[-1])
