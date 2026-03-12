"""
Конфігурація меандру — константи для генератора.
"""

from dataclasses import dataclass


@dataclass
class Config:
    radius: float = 0.03
    length: float = 6.0
    height: float = 0.1
    periods: int = 12
    k_angle: float = 0.04
    h1: float = 0.2
    h2: float = 0.3
    bf: float = 0.2       # ширина полки (flange width, Y-direction)
    nb: int = 4           # кількість проміжків на кожній стороні полки
