"""
Генератор прямокутного імпульсу (меандр).
"""

from dataclasses import dataclass
from typing import List, Tuple


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


class MeanderGenerator:
    """Генератор прямокутного імпульсу (меандр).

    Генерує масив точок, що описують прямокутний сигнал,
    який чергує горизонтальні сегменти на рівні y=0 та y=-height.
    """

    @staticmethod
    def generate(length: float, height: float, periods: int) -> List[Point]:
        """Генерує точки прямокутного імпульсу.

        Args:
            length:  довжина по координаті X.
            height:  висота перепаду по Y (сигнал опускається на -height).
            periods: кількість напівперіодів (сегментів).

        Returns:
            Список точок (x, y), що описують меандр.
        """
        if periods <= 0:
            return []

        step = length / periods
        points: List[Point] = [Point(0.0, 0.0)]

        for i in range(periods):
            y_level = 0.0 if i % 2 == 0 else -height
            x_end = round((i + 1) * step, 10)

            # Вертикальний перехід (якщо рівень змінився)
            if points[-1].y != y_level:
                points.append(Point(points[-1].x, y_level))

            # Горизонтальний сегмент
            points.append(Point(x_end, y_level))

        return points


if __name__ == "__main__":
    pts = MeanderGenerator.generate(length=6, height=2, periods=6)
    print(", ".join(str(p) for p in pts))
