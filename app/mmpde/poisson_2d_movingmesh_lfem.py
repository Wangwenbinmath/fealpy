import argparse
from sympy import *
import matplotlib.pyplot as plt
from fealpy.tools.show import showmultirate, show_error_table

from fealpy.backend import backend_manager as bm
from fealpy.pde.poisson_2d import LShapeRSinData
from fealpy.mesh import TriangleMesh
from fealpy.old.mesh import TriangleMesh as TM
from fealpy.mesh.lagrange_triangle_mesh import LagrangeTriangleMesh
from fealpy.functionspace import LagrangeFESpace,ParametricLagrangeFESpace
from fealpy.fem import (BilinearForm,
                        ScalarDiffusionIntegrator,
                        LinearForm,
                        ScalarSourceIntegrator,
                        DirichletBC)
from app.mmpde.harmap_mmpde import *
from fealpy.solver import cg, spsolve
from scipy.sparse import spdiags

## 参数解析
parser = argparse.ArgumentParser(description="""高阶移动网格方法""")
parser.add_argument('--mdegree', 
       default=2, type=int,
       help='网格的阶数，默认为 2 次.')

parser.add_argument('--sdegree', 
       default=2, type=int,
       help='ParametricLagrangeFESpace空间的次数，默认为 2 次.')

parser.add_argument('--itype',
        default='iso', type=str,
        help='初始网格，默认直角三角形网格.')

parser.add_argument('--n',
        default=4, type=int,
        help='初始网格剖分规格.')

parser.add_argument('--h',
        default=0.15, type=bm.float64,
        help='初始网格剖分大小.')

parser.add_argument('--beta',
        default=0.15, type=bm.float64,
        help='控制函数参数.')

parser.add_argument('--moltimes',
        default=25, type=int,
        help='磨光次数.')

parser.add_argument('--mtype',
        default='ltri', type=str,
        help='网格类型， 默认三角形网格.')

parser.add_argument('--backend',
        default='numpy', type=str,
        help="默认后端为 numpy.")

args = parser.parse_args()
bm.set_backend(args.backend)

mdegree = args.mdegree
sdegree = args.sdegree
itype = args.itype
n = args.n
h = args.h
beta = args.beta
moltimes = args.moltimes
mtype = args.mtype

pde = LShapeRSinData()

if itype == 'iso':
    def thr(p):
        x = p[...,0]
        y=  p[...,1]
        area = bm.array([0.01,1,-1,-0.01,-0.4,0.4])
        in_x = (x >= area[0]) & (x <= area[1])
        in_y = (y >= area[2]) & (y <= area[3])
        if p.shape[-1] == 3:
            z = p[...,2]
            in_z = (z >= area[4]) & (z <= area[5])
            return in_x & in_y & in_z
        return  in_x & in_y

    tmesh = TriangleMesh.from_box([-1, 1, -1, 1], nx=n, ny=n, threshold=thr)
    mesh = LagrangeTriangleMesh.from_triangle_mesh(tmesh, p=mdegree)
elif itype == 'equ':
    vertices = bm.array([[0.0,0.0],[1.0,0.0],[1.0,1.0],
                       [-1.0,1.0],[-1.0,-1.0],[0.0,-1.0]],dtype=bm.float64)
    mesh0 = TM.from_polygon_gmsh(vertices, h=h) 
    node = mesh0.entity('node')
    cell = mesh0.entity('cell')
    tmesh = TriangleMesh(node, cell)
    mesh = LagrangeTriangleMesh.from_triangle_mesh(tmesh, p=mdegree)

pro_mesh = mesh

def poisson_solver(pde, mesh, p):
    space = ParametricLagrangeFESpace(mesh, p=p)
    uh = space.function()
    bform = BilinearForm(space)
    bform.add_integrator(ScalarDiffusionIntegrator(method='isopara'))
    lform = LinearForm(space)
    lform.add_integrator(ScalarSourceIntegrator(source=pde.source, method='isopara'))
    A = bform.assembly()
    b = lform.assembly()
    A, b = DirichletBC(space, gd=pde.solution).apply(A, b)
    uh[:] = cg(A , b,maxiter=5000, atol=1e-14, rtol=1e-14)
    return uh

def interplote_error(pde, mesh, p):
    space = ParametricLagrangeFESpace(mesh=mesh, p=p)
    uI = space.interpolate(pde.solution)
    error = mesh.error(pde.solution , uI)
    return error

# 可视化
def high_order_meshploter(mesh , uh = None , model = 'mesh'):
    nodes = mesh.node
    cells = mesh.cell
    def lagrange_interpolation(points, num_points=100):
        """
        利用拉格朗日插值构造曲线
        :param points: 插值点的列表 [(x0, y0), (x1, y1), ..., (xp, yp)]
        :param num_points: 曲线上点的数量
        :return: 曲线上点的坐标数组
        """
        n = len(points) - 1  # 插值多项式的次数
        t = bm.linspace(0, n, num_points)
        
        def L(k, t):
            Lk = bm.ones_like(t)
            for i in range(n + 1):
                if i != k:
                    Lk *= (t - i) / (k - i)
            return Lk
        
        curve_x = bm.zeros_like(t)
        curve_y = bm.zeros_like(t)
        
        for k in range(n + 1):
            xk, yk = points[k]
            Lk = L(k, t)
            curve_x += xk * Lk
            curve_y += yk * Lk
        
        return curve_x, curve_y  
    

    if model == 'mesh':
        plt.figure()
        for cell in cells:
            # 绘制三角形的每条边
            p = nodes[cell]  # 中间节点
            curve0x, curve0y = lagrange_interpolation(p[[0,1,3]])
            plt.plot(curve0x, curve0y, 'b-',linewidth=0.5)
            curve1x, curve1y = lagrange_interpolation(p[[0,2,5]])
            plt.plot(curve1x, curve1y, 'b-',linewidth=0.5)
            curve2x, curve2y = lagrange_interpolation(p[[3,4,5]])
            plt.plot(curve2x, curve2y, 'b-',linewidth=0.5)

        plt.scatter(nodes[:, 0], nodes[:, 1],s = 5, color='r')  # 绘制节点
        plt.gca().set_aspect('equal')
        plt.xlabel('X')
        plt.ylabel('Y')
    
    elif model == 'surface':
        if uh.all() == None:
            raise ValueError("uh is none")
        cells = bm.concat([cells[:,0:3],cells[:,[1,3,4]],cells[:,[1,4,2]],cells[:,[2,4,5]]],axis = 0)
        fig = plt.figure()
        ax1 = fig.add_subplot(111, projection='3d')
        ax1.plot_trisurf(nodes[:, 0], nodes[:, 1], uh,
                            triangles = cells, cmap='viridis', 
                            edgecolor='b',linewidth=0.2)
    plt.show()

# Poisson eqution 求解
uh = poisson_solver(pde=pde, mesh=mesh, p=sdegree)

error0 = interplote_error(pde=pde, mesh=pro_mesh, p=sdegree)
print("移动网格前的误差error0:", error0)

# 网格移动前图像
high_order_meshploter(mesh)

# 网格移动
Vertex = bm.array([[0.0,0.0],[1.0,0.0],[1.0,1.0],
                   [-1.0,1.0],[-1.0,-1.0],[0.0,-1.0]],dtype=bm.float64)
MDH = Mesh_Data_Harmap(pro_mesh, Vertex)
Vertex_idx , Bdinnernode_idx ,sort_BdNode_idx= MDH.get_basic_infom()
HMP = Harmap_MMPDE(pro_mesh, uh, beta, Vertex_idx, Bdinnernode_idx, sort_BdNode_idx=sort_BdNode_idx, alpha = 0.25, mol_times=moltimes)
M = HMP.M
logic_mesh = HMP.logic_mesh
pro_mesh, uh = HMP.mesh_redistribution(uh, pde=pde)

error = interplote_error(pde=pde, mesh=pro_mesh, p=sdegree)
print("移动网格后的误差error：", error)

# 网格移动后图像
high_order_meshploter(pro_mesh)
