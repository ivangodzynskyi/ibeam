"""
Конфігурація меандру — константи для генератора.
"""

from dataclasses import dataclass


@dataclass
class Config:
    radius: float = 0.01
    length: float = 1.0         #довжина півбалки
    height: float = 0.07
    periods: int = 10
    k_angle: float = 0.01
    k_first: float = 3.0       # у скільки разів перший/останній сегмент довший за проміжні
    h1: float = 0.145
    h2: float = 0.085       
    bf: float = 0.12       # ширина полки (flange width, Y-direction)
    nb: int = 3           # кількість проміжків на кожній стороні полки
    tw: float = 0.0062     # товщина стінки
    tb: float = 0.0098     # товщина полки
    t_fill: float = 0.005  # товщина сітки-заповнення отворів (третя товщина)
    fillHolesNumbers: str = ""   # номери отворів для заповнення, напр. "1,2,5"
                                 # нумерація від краю (x=length) до центру (x=0);