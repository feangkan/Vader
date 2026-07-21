#! python 3
"""Scatter random points in a cube around the origin."""
import random
import rhinoscriptsyntax as rs

count = 25
size = 10.0
half = size / 2.0

for _ in range(count):
    x = random.uniform(-half, half)
    y = random.uniform(-half, half)
    z = random.uniform(-half, half)
    rs.AddPoint((x, y, z))
