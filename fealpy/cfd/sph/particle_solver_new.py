#!/usr/bin/python3
'''!    	
	@Author: wpx
	@File Name: particle_solver_new.py
	@Mail: wpx15673207315@gmail.com 
	@Created Time: Tue 14 Jan 2025 03:44:28 PM CST
	@bref 
	@ref 
'''  
from fealpy.backend import backend_manager as bm
from fealpy.backend import TensorLike

import numpy as np
import jax
import jax.numpy as jnp
import torch

# Types
Box = TensorLike
f32 = bm.float32

class Space:
    def raw_transform(self, box:Box, R:TensorLike):
        if box.ndim == 0 or box.size == 1:
            
            return R * box
        elif box.ndim == 1:
            indices = self._get_free_indices(R.ndim - 1) + "i"
            
            return bm.einsum(f"i,{indices}->{indices}", box, R)
        elif box.ndim == 2:
            free_indices = self._get_free_indices(R.ndim - 1)
            left_indices = free_indices + "j"
            right_indices = free_indices + "i"
            
            return bm.einsum(f"ij,{left_indices}->{right_indices}", box, R)
        raise ValueError(
            ("Box must be either: a scalar, a vector, or a matrix. " f"Found {box}.")
        )

    def _get_free_indices(self, n: int):
        
        return "".join([chr(ord("a") + i) for i in range(n)])

    def pairwise_displacement(self, Ra: TensorLike, Rb: TensorLike):
        if len(Ra.shape) != 1:
            msg = (
				"Can only compute displacements between vectors. To compute "
				"displacements between sets of vectors use vmap or TODO."
				)
            raise ValueError(msg)

        if Ra.shape != Rb.shape:
            msg = "Can only compute displacement between vectors of equal dimension."
            raise ValueError(msg)

        return Ra - Rb

    def periodic_displacement(self, side: Box, dR: TensorLike):
        _dR = ((dR + side * f32(0.5)) % side) - f32(0.5) * side
        
        return _dR

    def periodic_shift(self, side: Box, R: TensorLike, dR: TensorLike):

        return (R + dR) % side

    def periodic(self, side: Box, wrapped: bool = True):
        def displacement_fn( Ra: TensorLike, Rb: TensorLike, perturbation = None, **unused_kwargs):
            if "box" in unused_kwargs:
                raise UnexpectedBoxException(
                    (
                        "`space.periodic` does not accept a box "
                        "argument. Perhaps you meant to use "
                        "`space.periodic_general`?"
                    )
                )
            dR = self.periodic_displacement(side, self.pairwise_displacement(Ra, Rb))
            if perturbation is not None:
                dR = self.raw_transform(perturbation, dR)
            
            return dR
        if wrapped:
            def shift_fn(R: TensorLike, dR: TensorLike, **unused_kwargs):
                if "box" in unused_kwargs:
                    raise UnexpectedBoxException(
                        (
                            "`space.periodic` does not accept a box "
                            "argument. Perhaps you meant to use "
                            "`space.periodic_general`?"
                        )
                    )

                return self.periodic_shift(side, R, dR)
        else:
                def shift_fn(R: TensorLike, dR: TensorLike, **unused_kwargs):
                    if "box" in unused_kwargs:
                        raise UnexpectedBoxException(
                            (
                                "`space.periodic` does not accept a box "
                                "argument. Perhaps you meant to use "
                                "`space.periodic_general`?"
                            )
                        )
                    return R + dR

        return displacement_fn, shift_fn

class VmapBackend:
    def __init__(self):
        current_backend = bm.backend_name

        # 根据当前后端设置 vmap 函数
        if current_backend == 'jax':
            # 使用 JAX 的 vmap
            self.vmap_func = jax.vmap
        elif current_backend == 'numpy':
            # 使用 NumPy 的 vectorize
            self.vmap_func = np.vectorize
        elif current_backend == 'pytorch':
            # 使用 PyTorch 的 vmap
            self.vmap_func = torch.vmap
        else:
            raise ValueError(f"Unsupported backend: {current_backend}")

    def apply(self, func, *args, **kwargs):
        # 返回已经适配的 vmap 函数
        return self.vmap_func(func)(*args, **kwargs)

class SPHSolver:
    def __init__(self, mesh):
        self.mesh = mesh 
    