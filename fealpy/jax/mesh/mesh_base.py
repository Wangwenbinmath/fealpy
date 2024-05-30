
import numpy as np

from typing import (
    Literal, Callable, Optional, List, Union, TypeVar,
    overload, Dict, Any
)
from numpy.typing import NDArray

import jax
import jax.numpy as jnp

from .mesh_kernel import edge_to_ipoint

Array = jax.Array
Index = Union[Array, int, slice]
EntityName = Literal['cell', 'cell_location', 'face', 'face_location', 'edge']
_int_func = Callable[..., int]
_dtype = jnp.dtype
_device = jax.Device

_S = slice(None, None, None)
_T = TypeVar('_T')
_default = object()


##################################################
### Utils
##################################################

def entity_str2dim(ds, etype: str) -> int:
    if etype == 'cell':
        return ds.top_dimension()
    elif etype == 'cell_location':
        return -ds.top_dimension()
    elif etype == 'face':
        TD = ds.top_dimension()
        if TD <= 1:
            raise ValueError('the mesh has no face entity.')
        return TD - 1
    elif etype == 'face_location':
        TD = ds.top_dimension()
        if TD <= 1:
            raise ValueError('the mesh has no face location.')
        return -TD + 1
    elif etype == 'edge':
        return 1
    elif etype == 'node':
        return 0
    else:
        raise KeyError(f'{etype} is not a valid entity attribute.')


def entity_dim2array(ds, etype_dim: int, index=None, *, default=_default):
    r"""Get entity tensor by its top dimension."""
    if etype_dim in ds._entity_storage:
        et = ds._entity_storage[etype_dim]
        if index is None:
            return et
        else:
            if et.ndim == 1:
                raise RuntimeError("index is not supported for flattened entity.")
            return et[index]
    else:
        if default is not _default:
            return default
        raise ValueError(f'{etype_dim} is not a valid entity attribute index '
                         f"in {ds.__class__.__name__}.")


##################################################
### Mesh Data Structure Base
#################################################

class MeshDataStructure():
    _STORAGE_ATTR = ['cell', 'face', 'edge', 'cell_location','face_location']
    def __init__(self, NN: int, TD: int) -> None:
        self._entity_storage: Dict[int, Array] = {}
        self.NN = NN
        self.TD = TD

    @overload
    def __getattr__(self, name: EntityName) -> Array: ...
    def __getattr__(self, name: str):
        if name not in self._STORAGE_ATTR:
            return self.__dict__[name]
        etype_dim = entity_str2dim(self, name)
        return entity_dim2array(self, etype_dim)

    def __setattr__(self, name: str, value: Any) -> None:
        if name in self._STORAGE_ATTR:
            if not hasattr(self, '_entity_storage'):
                raise RuntimeError('please call super().__init__() before setting attributes.')
            etype_dim = entity_str2dim(self, name)
            self._entity_storage[etype_dim] = value
        else:
            super().__setattr__(name, value)

    ### cuda
    def to(self, device: Optional[_device]=None):
        for entity_tensor in self._entity_storage.values():
            jax.device_put(entity_tensor, device)
        return self

    ### properties
    def top_dimension(self) -> int: return self.TD
    @property
    def itype(self) -> _dtype: return self.cell.dtype

    ### counters
    number_of_nodes: _int_func = lambda self: self.NN
    number_of_edges: _int_func = lambda self: len(entity_dim2array(self, 1))
    number_of_faces: _int_func = lambda self: len(entity_dim2array(self, self.top_dimension() - 1))
    number_of_cells: _int_func = lambda self: len(entity_dim2array(self, self.top_dimension()))

    ### constructors
    def construct(self) -> None:
        raise NotImplementedError

    @overload
    def entity(self, etype: Union[int, str], index: Optional[Index]=None) -> Array: ...
    @overload
    def entity(self, etype: Union[int, str], index: Optional[Index]=None, *, default: _T) -> Union[Array, _T]: ...
    def entity(self, etype: Union[int, str], index: Optional[Index]=None, *, default=_default):
        r"""@brief Get entities in mesh structure.

        @param etype: int or str. The topology dimension of the entity, or name
        'cell' | 'face' | 'edge'. Note that 'node' is not in mesh structure.
        For polygon meshes, the names 'cell_location' | 'face_location' may also be
        available, and the `index` argument is applied on the flattened entity array.
        @param index: int, slice or Array. The index of the entity.

        @return: Array or Sequence[Array].
        """
        if isinstance(etype, str):
            etype = entity_str2dim(self, etype)
        return entity_dim2array(self, etype, index, default=default)

    def total_face(self) -> Array:
        raise NotImplementedError

    def total_edge(self) -> Array:
        raise NotImplementedError

    ### boundary
    def boundary_face_flag(self): return self.face2cell[:, 0] == self.face2cell[:, 1]
    def boundary_face_index(self): return jnp.nonzero(self.boundary_face_flag())[0]


class HomoMeshDataStructure(MeshDataStructure):
    ccw: Array
    localEdge: Array
    localFace: Array

    def __init__(self, NN: int, TD: int, cell: Array) -> None:
        super().__init__(NN, TD)
        self.cell = cell

    number_of_vertices_of_cells: _int_func = lambda self: self.cell.shape[-1]
    number_of_nodes_of_cells = number_of_vertices_of_cells
    number_of_edges_of_cells: _int_func = lambda self: self.localEdge.shape[0]
    number_of_faces_of_cells: _int_func = lambda self: self.localFace.shape[0]
    number_of_vertices_of_faces: _int_func = lambda self: self.localFace.shape[-1]
    number_of_vertices_of_edges: _int_func = lambda self: self.localEdge.shape[-1]

    def total_face(self) -> Array:
        NVF = self.number_of_faces_of_cells()
        cell = self.entity(self.TD)
        local_face = self.localFace
        total_face = cell[..., local_face].reshape(-1, NVF)
        return total_face

    def total_edge(self) -> Array:
        NVE = self.number_of_vertices_of_edges()
        cell = self.entity(self.TD)
        local_edge = self.localEdge
        total_edge = cell[..., local_edge].reshape(-1, NVE)
        return total_edge

    def construct(self) -> None:
        raise NotImplementedError


##################################################
### Mesh Base
##################################################

class MeshBase():
    """
    @brief The base class for mesh.
    """
    ds: MeshDataStructure
    node: Array

    def geo_dimension(self) -> int:
        """
        @brief Get geometry dimension of the mesh.
        """
        return self.node.shape[-1]

    def top_dimension(self) -> int:
        """
        @brief Get topology dimension of the mesh.
        """
        return self.ds.TD

    def number_of_nodes(self) -> int:
        return len(self.node)

    def number_of_faces(self) -> int:
        return len(self.ds.face)

    def number_of_edges(self) -> int:
        return len(self.ds.edge)

    def number_of_cells(self) -> int:
        return len(self.ds.cell)

    @staticmethod
    def multi_index_matrix(p: int, etype: int):
        """
        @brief 获取 p 次的多重指标矩阵

        @param[in] p 正整数

        @return multiIndex  ndarray with shape (ldof, TD+1)
        """
        if etype == 3:
            ldof = (p+1)*(p+2)*(p+3)//6
            idx = np.arange(1, ldof)
            idx0 = (3*idx + np.sqrt(81*idx*idx - 1/3)/3)**(1/3)
            idx0 = np.floor(idx0 + 1/idx0/3 - 1 + 1e-4) # a+b+c
            idx1 = idx - idx0*(idx0 + 1)*(idx0 + 2)/6
            idx2 = np.floor((-1 + np.sqrt(1 + 8*idx1))/2) # b+c
            multiIndex = np.zeros((ldof, 4), dtype=np.int_)
            multiIndex[1:, 3] = idx1 - idx2*(idx2 + 1)/2
            multiIndex[1:, 2] = idx2 - multiIndex[1:, 3]
            multiIndex[1:, 1] = idx0 - idx2
            multiIndex[:, 0] = p - np.sum(multiIndex[:, 1:], axis=1)
            return jnp.array(multiIndex)
        elif etype == 2:
            ldof = (p+1)*(p+2)//2
            idx = np.arange(0, ldof)
            idx0 = np.floor((-1 + np.sqrt(1 + 8*idx))/2)
            multiIndex = np.zeros((ldof, 3), dtype=np.int_)
            multiIndex[:,2] = idx - idx0*(idx0 + 1)/2
            multiIndex[:,1] = idx0 - multiIndex[:,2]
            multiIndex[:,0] = p - multiIndex[:, 1] - multiIndex[:, 2]
            return jnp.array(multiIndex)
        elif etype == 1:
            ldof = p+1
            multiIndex = np.zeros((ldof, 2), dtype=np.int_)
            multiIndex[:, 0] = np.arange(p, -1, -1)
            multiIndex[:, 1] = p - multiIndex[:, 0]
            return jnp.array(multiIndex)

    def entity(self, etype: Union[int, str], index=np.s_[:]):
        """
        @brief Get entities.

        @param etype: Type of entities. Accept dimension or name.
        @param index: Index for entities.

        @return: A tensor representing the entities in this mesh.
        """
        TD = self.top_dimension()
        GD = self.geo_dimension()
        if etype in {'cell', TD}:
            return self.ds.cell[index]
        elif etype in {'edge', 1}:
            return self.ds.edge[index]
        elif etype in {'node', 0}:
            return self.node.reshape(-1, GD)[index]
        elif etype in {'face', TD-1}: # Try 'face' in the last
            return self.ds.face[index]
        raise ValueError(f"Invalid etype '{etype}'.")

    def entity_barycenter(self, etype: Union[int, str], index=jnp.s_[:]):
        """
        @brief Calculate barycenters of entities.
        """
        node = self.entity('node')
        TD = self.ds.TD
        if etype in {'cell', TD}:
            cell = self.ds.cell
            return jnp.sum(node[cell[index], :], axis=1) / cell.shape[1]
        elif etype in {'edge', 1}:
            edge = self.ds.edge
            return jnp.sum(node[edge[index], :], axis=1) / edge.shape[1]
        elif etype in {'node', 0}:
            return node[index]
        elif etype in {'face', TD-1}: # Try 'face' in the last
            face = self.ds.face
            return jnp.sum(node[face[index], :], axis=1) / face.shape[1]
        raise ValueError(f"Invalid entity type '{etype}'.")

    def bc_to_point(self, bcs, index=jnp.s_[:]):
        """
        @brief Convert barycenter coordinate points to cartesian coordinate points\
               on mesh entities.

        @param bc: Barycenter coordinate points array, with shape (NQ, NVC), where\
                   NVC is the number of nodes in each entity.
        @param etype: Specify the type of entities on which the coordinates be converted.
        @param index: Index to slice entities.

        @note: To get the correct result, the order of bc must match the order of nodes\
               in the entity.

        @return: Cartesian coordinate points array, with shape (NQ, GD).
        """
        node = self.entity('node')
        TD = bcs.shape[-1] - 1
        entity = self.entity(TD, index=index)
        p = jnp.einsum('...j, ijk -> ...ik', bcs, node[entity])
        return p

    def edge_to_ipoint(self, p: int, index=np.s_[:]):
        """
        @brief 获取网格边与插值点的对应关系
        """
        if isinstance(index, slice) and index == slice(None):
            NE = self.number_of_edges()
            index = np.arange(NE)
        elif isinstance(index, np.ndarray) and (index.dtype == np.bool_):
            index, = np.nonzero(index)
            NE = len(index)
        elif isinstance(index, list) and (type(index[0]) is np.bool_):
            index, = np.nonzero(index)
            NE = len(index)
        else:
            NE = len(index)
        NN = self.number_of_nodes()
        edges = self.entity('edge')[index]
        return edge_to_ipoint(edges, index, p)

    def edge_unit_tangent(self, index=jnp.s_[:], node: Optional[NDArray]=None):
        """
        @brief Calculate the tangent vector with unit length of each edge.\
               See `Mesh.edge_tangent`.
        """
        node = self.entity('node') if node is None else node
        edge = self.entity('edge', index=index)
        v = node[edge[:, 1], :] - node[edge[:, 0], :]
        length = jnp.sqrt(jnp.square(v).sum(axis=1))
        return v/length.reshape(-1, 1)

