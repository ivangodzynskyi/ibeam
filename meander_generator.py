"""
Генератор прямокутного імпульсу (меандр).
"""

from dataclasses import dataclass
from typing import List, Tuple, Union

@dataclass
class Point:
    x: float
    y: float

    def __eq__(self, other):
        if isinstance(other, tuple) and len(other) == 2:
            return (self.x, self.y) == other
        return isinstance(other, Point) and self.x == other.x and self.y == other.y

    def __repr__(self):
        return f"({self.x}, {self.y})"


@dataclass
class Fillet:
    p1: Point
    p2: Point
    p_center: Point

    def __repr__(self):
        return f"Fillet(p1={self.p1}, p2={self.p2}, pCenter={self.p_center})"


class MeanderGenerator:
    """Генератор прямокутного імпульсу (меандр).

    Генерує масив точок, що описують прямокутний сигнал,
    який чергує горизонтальні сегменти на рівні y=0 та y=-height.
    """

    @staticmethod
    def generate(length: float, height: float, periods: int,
                 k_angle: float = 0.0) -> List[Point]:
        """Генерує точки прямокутного імпульсу.

        Args:
            length:  довжина по координаті X.
            height:  висота перепаду по Y (сигнал опускається на -height).
            periods: кількість напівперіодів (сегментів).
            k_angle: зсув по X для нахилу вертикальних переходів.

        Returns:
            Список точок (x, y), що описують меандр.
        """
        if periods <= 0:
            return []

        step = length / periods
        points: List[Point] = [Point(0.0, -height)]

        for i in range(periods):
            y_level = -height if i % 2 == 0 else 0.0
            x_end = round((i + 1) * step, 10)

            # Вертикальний перехід (якщо рівень змінився)
            if points[-1].y != y_level:
                points.append(Point(points[-1].x, y_level))

            # Горизонтальний сегмент
            points.append(Point(x_end, y_level))

        # Застосувати нахил до вертикальних переходів
        if k_angle != 0.0:
            for i in range(1, len(points) - 1):
                if i % 2 == 1:
                    points[i].x -= k_angle
                else:
                    points[i].x += k_angle

        return points

    @staticmethod
    def generate_with_fillets(length: float, height: float, periods: int,
                              radius: float,
                              k_angle: float = 0.0) -> List[Union[Point, Fillet]]:
        """Генерує меандр зі скругленнями у кутових точках.

        Кожна проміжна точка (кут) замінюється на об'єкт Fillet,
        який описує дугу скруглення трьома параметрами:
        p1, p2 — точки дотику, p_center — центр кола.

        Args:
            length:  довжина по координаті X.
            height:  висота перепаду по Y.
            periods: кількість напівперіодів.
            radius:  радіус скруглення.
            k_angle: зсув по X для нахилу вертикальних переходів.

        Returns:
            Список, де перша та остання точки залишаються Point,
            а кожна проміжна кутова точка замінена на Fillet.
        """
        from fillet import compute_fillet

        points = MeanderGenerator.generate(length, height, periods, k_angle)
        if len(points) < 3:
            return list(points)

        result: List[Union[Point, Fillet]] = [points[0]]

        for i in range(1, len(points) - 1):
            fr = compute_fillet(points[i - 1], points[i], points[i + 1], radius=radius)
            result.append(Fillet(p1=fr.R1, p2=fr.R2, p_center=fr.RC))

        result.append(points[-1])
        return result


if __name__ == "__main__":
    pts = MeanderGenerator.generate(length=6, height=2, periods=6)
    print("k_angle=0:  ", ", ".join(str(p) for p in pts))

    pts = MeanderGenerator.generate(length=6, height=2, periods=6, k_angle=0.1)
    print("k_angle=0.1:", ", ".join(str(p) for p in pts))

    print("\nWith fillets (radius=0.2):")
    items = MeanderGenerator.generate_with_fillets(length=6, height=2, periods=6, radius=0.2)
    for item in items:
        print(f"  {item}")
