"""
Конфігурація меандру — константи для генератора.
"""

from dataclasses import dataclass


@dataclass
class Config:
    radius: float = 0.01
    length: float = 3.0
    height: float = 0.1
    periods: int = 12
    k_angle: float = 0.0
    h1: float = 0.5
    h2: float = 0.2
    bf: float = 0.2       # ширина полки (flange width, Y-direction)
    nb: int = 8           # кількість проміжків на кожній стороні полки
    tw: float = 0.008     # товщина стінки
    tb: float = 0.012     # товщина полки
