#! python 3
"""Draw a unit circle at the world origin."""
import rhinoscriptsyntax as rs

center = (0, 0, 0)
radius = 1.0
rs.AddCircle(center, radius)
