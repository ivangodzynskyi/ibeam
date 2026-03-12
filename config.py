"""
Конфігурація меандру — константи для генератора.
"""

from dataclasses import dataclass


@dataclass
class MeanderConfig:
    radius: float = 0.2
    length: float = 6.0
    height: float = 2.0
    periods: int = 6
    k_angle: float = 0.0
