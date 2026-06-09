"""
Конфігурація меандру — константи для генератора.
"""

from dataclasses import dataclass


@dataclass
class Config:
    radius: float = 0.01
    length: float = 1.0         #довжина півбалки
    height: float = 0.07
    periods: int = 8
    k_angle: float = 0.02
    h1: float = 0.182
    h2: float = 0.112       
    bf: float = 0.12       # ширина полки (flange width, Y-direction)
    nb: int = 3           # кількість проміжків на кожній стороні полки
    tw: float = 0.0062     # товщина стінки
    tb: float = 0.0098     # товщина полки
