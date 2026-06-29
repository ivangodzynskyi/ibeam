"""
Конфігурація меандру — константи для генератора.
"""

from dataclasses import dataclass


@dataclass
class Config:
    H: float = 240              # висота сортаментної балки, мм
    Bf: float = 120             # ширина сортаментної балки, мм
    Tw: float = 6.2             # товщина стінки сортаментної балки, мм
    Tb: float = 9.8             # товщина полиць сортаментної балки, мм
    Lb: float = 2000            # довжина балки, мм
    Tfill: float = 6            # товщина заповнюючих елементів, мм
    Bfill_center: float = 100   # довжина заповнюючого ребра посередині, мм

    periods: int = 8           # кількість отворів (парна кількість)   
    toothZ: float = 60          # висота зубів, мм
    toothX: float = 20          # нахил зубів (проекція нахиленої частини зуба на поздовжню вісь), мм
    k_first: float = 3.0        # у скільки разів перший/останній сегмент довший за проміжні
    Hsupport: float = 200       # висота перфорованої балки на опорі, мм
    Radius: float = 10          # радіус скруглення, мм
    t_slit: float = 3           # товщина лазерного різу, мм


    radius: float = Radius / 1000
    length: float = Lb / 2000                   #довжина півбалки
    height: float = toothZ / 1000
    k_angle: float = toothX / 2000
    h1: float = (H - Hsupport/2 - t_slit - Tb/2 + toothZ) / 1000
    h2: float = (Hsupport-Tb)/2000  
    bf: float = Bf / 1000                       # ширина полки (flange width, Y-direction)
    nb: int = 3                                 # кількість проміжків на кожній стороні полки
    tw: float = Tw / 1000                       # товщина стінки
    tb: float = Tb / 1000                       # товщина полки
    t_fill: float = Tfill / 1000                # товщина сітки-заповнення отворів (третя товщина)
    fillHolesNumbers: str = ""                  # номери отворів для заповнення, напр. "1,2,5"
                                                # нумерація від краю (x=length) до центру (x=0);
    to_add_fill_to_the_center: bool = True
    b_center: float = Bfill_center/2000         # X-розмір центральної вставки


    # run ibeam_gmsh_sli.py to generate the i-beam with web-openings