import gmsh
gmsh.initialize()
gmsh.model.add("region")
geo = gmsh.model.geo

p1 = geo.addPoint(0, 0, 0, 0.1)
p2 = geo.addPoint(1, 0, 0, 0.1)
p3 = geo.addPoint(1, 1, 0, 0.1)
p4 = geo.addPoint(0, 1, 0, 0.1)
# Три прямі лінії (частина прямокутника)
l1 = geo.addLine(p1, p2)
l2 = geo.addLine(p2, p3)
l3 = geo.addLine(p3, p4)
# Крива по функції (сплайн)
curve = geo.addSpline([p4, p1])  # або через проміжні точки
loop = geo.addCurveLoop([l1, l2, l3, curve])
surf = geo.addPlaneSurface([loop])
geo.synchronize()
gmsh.model.mesh.generate(2)
gmsh.write("region.msh")
gmsh.finalize()