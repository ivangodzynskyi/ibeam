"""
Конфігурація меандру — константи для генератора.
"""

from dataclasses import dataclass


@dataclass
class Config:
    radius: float = 0.2
    length: float = 6.0
    height: float = 0.1
    periods: int = 6
    k_angle: float = 0.1
    h1: float = 0.2
    h2: float = 0.3
