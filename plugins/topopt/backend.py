from __future__ import annotations

import json
from math import ceil, sqrt
from pathlib import Path
import time
import warnings

from mass_town.disciplines.topology import (
    TopologyBackend,
    TopologyRequest,
    TopologyResult,
    TopologyTimingResult,
)
from mass_town.storage.filesystem import ensure_directory


class StructuredPlaneStressTopologyBackend(TopologyBackend):
    name = "structured_plane_stress"

    def is_available(self) -> bool:
        try:
            self._load_dependencies()
        except ImportError:
            return False
        return True

    def availability_reason(self) -> str | None:
        try:
            self._load_dependencies()
        except ImportError as exc:
            return f"topology dependencies are unavailable: {exc}"
        return None

    def run_optimization(self, request: TopologyRequest) -> TopologyResult:
        np, plt, scipy_sparse, scipy_splinalg = self._load_dependencies()
        config = request.config
        domain = config.domain
        material = config.material
        projection = config.projection
        optimizer = config.optimizer

        report_directory = ensure_directory(request.report_directory)
        log_directory = ensure_directory(request.log_directory)
        mesh_directory = ensure_directory(request.mesh_directory)
        ensure_directory(request.solution_directory)

        summary_path = report_directory / "topology_summary.json"
        history_path = report_directory / "topology_history.json"
        density_path = report_directory / "final_density.json"
        plot_path = report_directory / "final_density.png"
        mesh_path = mesh_directory / "structured_mesh.json"
        log_path = log_directory / "topology.log"

        total_start = time.perf_counter()
        mesh_start = time.perf_counter()
        mesh = _StructuredQuadMesh(domain.nelx, domain.nely, domain.lx, domain.ly, np=np)
        mesh_seconds = time.perf_counter() - mesh_start
        mesh_path.write_text(json.dumps(mesh.metadata(), indent=2, sort_keys=True) + "\n")

        filter_operator = _DensityFilter(
            nelx=domain.nelx,
            nely=domain.nely,
            radius=config.filter.radius,
            np=np,
            scipy_sparse=scipy_sparse,
        )
        projector = _HeavisideProjection(
            enabled=projection.enabled,
            beta=projection.beta,
            beta_max=projection.beta_max,
            eta=projection.eta,
            beta_scale=projection.beta_scale,
            update_interval=projection.update_interval,
            np=np,
        )

        force_vector, fixed_dofs = mesh.load_and_boundary(
            node_selector=config.load.node_selector,
            dof=config.load.dof,
            magnitude=config.load.magnitude,
            fixed_boundary=config.boundary.fixed_boundary,
        )
        if fixed_dofs.size == 0:
            raise ValueError("topology.boundary produced no fixed degrees of freedom.")
        if np.allclose(force_vector, 0.0):
            raise ValueError("topology.load produced a zero force vector.")

        x = np.full(mesh.num_elements, float(config.volume_fraction), dtype=float)
        history: dict[str, list[float | int]] = {
            "iteration": [],
            "objective": [],
            "volume_fraction": [],
            "max_density_change": [],
            "beta": [],
        }
        log_lines = [
            (
                "topology run_id={run_id} backend={backend} nelx={nelx} nely={nely} "
                "volfrac={volfrac:.6f}"
            ).format(
                run_id=request.run_id,
                backend=self.name,
                nelx=domain.nelx,
                nely=domain.nely,
                volfrac=config.volume_fraction,
            )
        ]
        total_solve_seconds = 0.0
        converged = False
        failure_reason: str | None = None
        objective: float | None = None
        volume_fraction: float | None = None
        max_density_change: float | None = None
        x_phys = x.copy()

        try:
            for iteration in range(1, optimizer.max_iterations + 1):
                x_filt = filter_operator.apply(x)
                x_phys = projector.apply(x_filt)

                solve_start = time.perf_counter()
                objective, dc_phys = mesh.compliance_and_sensitivity(
                    densities=x_phys,
                    youngs_modulus=material.youngs_modulus,
                    poisson_ratio=material.poisson_ratio,
                    penal=material.simp_penalization,
                    density_min=material.density_min,
                    force_vector=force_vector,
                    fixed_dofs=fixed_dofs,
                    scipy_sparse=scipy_sparse,
                    scipy_splinalg=scipy_splinalg,
                    warnings_module=warnings,
                    np=np,
                )
                total_solve_seconds += time.perf_counter() - solve_start

                dprojection = projector.derivative(x_filt)
                dc = filter_operator.apply_transpose(dc_phys * dprojection)
                dv = filter_operator.apply_transpose(
                    np.full(mesh.num_elements, 1.0 / mesh.num_elements, dtype=float) * dprojection
                )

                x_new = _optimality_criteria_update(
                    densities=x,
                    objective_gradient=dc,
                    volume_gradient=dv,
                    target_volume_fraction=config.volume_fraction,
                    move_limit=optimizer.move_limit,
                    density_min=material.density_min,
                    np=np,
                )
                max_density_change = float(np.max(np.abs(x_new - x)))
                volume_fraction = float(np.mean(x_phys))

                history["iteration"].append(iteration)
                history["objective"].append(float(objective))
                history["volume_fraction"].append(volume_fraction)
                history["max_density_change"].append(max_density_change)
                history["beta"].append(float(projector.beta))
                log_lines.append(
                    (
                        f"iteration={iteration} objective={objective:.6f} "
                        f"volume_fraction={volume_fraction:.6f} "
                        f"max_density_change={max_density_change:.6f} beta={projector.beta:.6f}"
                    )
                )

                x = x_new
                if max_density_change <= optimizer.change_tolerance:
                    converged = True
                    break
                projector.update(iteration)
        except ValueError:
            raise
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"Topology optimization failed unexpectedly: {exc}") from exc

        optimization_seconds = time.perf_counter() - total_start
        if not converged:
            failure_reason = (
                "Topology optimization reached the maximum iteration count without "
                "meeting the density-change tolerance."
            )

        density_payload = {
            "shape": [domain.nely, domain.nelx],
            "densities": x_phys.reshape(domain.nely, domain.nelx).tolist(),
        }
        density_path.write_text(json.dumps(density_payload, indent=2) + "\n")
        history_path.write_text(json.dumps(history, indent=2, sort_keys=True) + "\n")
        if config.write_density_plot:
            self._write_density_plot(plot_path=plot_path, densities=x_phys, nely=domain.nely, nelx=domain.nelx)

        summary = {
            "backend": self.name,
            "converged": converged,
            "objective": objective,
            "volume_fraction": volume_fraction,
            "max_density_change": max_density_change,
            "beta": projector.beta,
            "iteration_count": len(history["iteration"]),
            "timing": {
                "mesh_seconds": mesh_seconds,
                "solve_seconds": total_solve_seconds,
                "optimization_seconds": optimization_seconds,
            },
            "failure_reason": failure_reason,
            "artifact_paths": {
                "mesh": str(mesh_path),
                "history": str(history_path),
                "density": str(density_path),
                "plot": str(plot_path) if config.write_density_plot else None,
                "log": str(log_path),
            },
            "config_snapshot": config.model_dump(mode="json"),
        }
        summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
        log_path.write_text("\n".join(log_lines) + "\n")

        result_files = [mesh_path, history_path, density_path, summary_path, log_path]
        if config.write_density_plot:
            result_files.append(plot_path)

        return TopologyResult(
            backend_name=self.name,
            converged=converged,
            objective=objective,
            volume_fraction=volume_fraction,
            max_density_change=max_density_change,
            beta=projector.beta,
            iteration_count=len(history["iteration"]),
            timing=TopologyTimingResult(
                mesh_seconds=mesh_seconds,
                solve_seconds=total_solve_seconds,
                optimization_seconds=optimization_seconds,
            ),
            result_files=result_files,
            metadata={"objective_name": "compliance", "constraint_name": "volume_fraction"},
            log_path=log_path,
            history_path=history_path,
            density_path=density_path,
            plot_path=plot_path if config.write_density_plot else None,
            summary_path=summary_path,
            failure_reason=failure_reason,
        )

    def _write_density_plot(self, plot_path: Path, densities: object, nely: int, nelx: int) -> None:
        np, plt, _, _ = self._load_dependencies()
        figure, axis = plt.subplots(figsize=(8, 3))
        axis.imshow(
            np.asarray(densities, dtype=float).reshape(nely, nelx),
            cmap="gray_r",
            origin="lower",
            vmin=0.0,
            vmax=1.0,
            aspect="auto",
        )
        axis.set_title("Final Density Field")
        axis.set_xlabel("Element i")
        axis.set_ylabel("Element j")
        figure.tight_layout()
        figure.savefig(plot_path, dpi=160)
        plt.close(figure)

    def _load_dependencies(self) -> tuple[object, object, object, object]:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
        import scipy.sparse as scipy_sparse
        import scipy.sparse.linalg as scipy_splinalg

        return np, plt, scipy_sparse, scipy_splinalg


class _HeavisideProjection:
    def __init__(
        self,
        *,
        enabled: bool,
        beta: float,
        beta_max: float,
        eta: float,
        beta_scale: float,
        update_interval: int,
        np: object,
    ) -> None:
        self.enabled = enabled
        self.beta = float(beta)
        self.beta_max = float(beta_max)
        self.eta = float(eta)
        self.beta_scale = float(beta_scale)
        self.update_interval = int(update_interval)
        self._np = np

    def apply(self, densities: object) -> object:
        np = self._np
        values = np.asarray(densities, dtype=float)
        if not self.enabled:
            return values
        t1 = np.tanh(self.beta * self.eta)
        t2 = np.tanh(self.beta * (1.0 - self.eta))
        denom = t1 + t2
        if abs(float(denom)) < 1e-12:
            return values
        return (t1 + np.tanh(self.beta * (values - self.eta))) / denom

    def derivative(self, densities: object) -> object:
        np = self._np
        values = np.asarray(densities, dtype=float)
        if not self.enabled:
            return np.ones_like(values, dtype=float)
        t1 = np.tanh(self.beta * self.eta)
        t2 = np.tanh(self.beta * (1.0 - self.eta))
        denom = t1 + t2
        if abs(float(denom)) < 1e-12:
            return np.ones_like(values, dtype=float)
        t = np.tanh(self.beta * (values - self.eta))
        return (self.beta * (1.0 - t * t)) / denom

    def update(self, iteration: int) -> None:
        if not self.enabled:
            return
        if iteration % self.update_interval != 0:
            return
        self.beta = min(self.beta_max, self.beta * self.beta_scale)


class _DensityFilter:
    def __init__(self, *, nelx: int, nely: int, radius: float, np: object, scipy_sparse: object) -> None:
        self._np = np
        self._weights = self._build_weights(
            nelx=nelx,
            nely=nely,
            radius=radius,
            np=np,
            scipy_sparse=scipy_sparse,
        )
        self._weight_sums = np.asarray(self._weights.sum(axis=1)).reshape(-1)
        self._weight_sums[self._weight_sums <= 1e-12] = 1.0

    def apply(self, densities: object) -> object:
        np = self._np
        values = np.asarray(densities, dtype=float).reshape(-1)
        return self._weights.dot(values) / self._weight_sums

    def apply_transpose(self, sensitivities: object) -> object:
        np = self._np
        values = np.asarray(sensitivities, dtype=float).reshape(-1) / self._weight_sums
        return self._weights.transpose().dot(values)

    def _build_weights(
        self, *, nelx: int, nely: int, radius: float, np: object, scipy_sparse: object
    ) -> object:
        rows: list[int] = []
        cols: list[int] = []
        data: list[float] = []
        search_radius = int(ceil(radius))
        for ey in range(nely):
            for ex in range(nelx):
                element_index = ey * nelx + ex
                for ny in range(max(0, ey - search_radius), min(nely, ey + search_radius + 1)):
                    for nx in range(max(0, ex - search_radius), min(nelx, ex + search_radius + 1)):
                        neighbor_index = ny * nelx + nx
                        distance = sqrt((ex - nx) ** 2 + (ey - ny) ** 2)
                        weight = max(0.0, radius - distance)
                        if weight <= 0.0:
                            continue
                        rows.append(element_index)
                        cols.append(neighbor_index)
                        data.append(weight)
        size = nelx * nely
        return scipy_sparse.csr_matrix((np.asarray(data), (rows, cols)), shape=(size, size))


class _StructuredQuadMesh:
    def __init__(self, nelx: int, nely: int, lx: float, ly: float, *, np: object) -> None:
        self.nelx = nelx
        self.nely = nely
        self.lx = lx
        self.ly = ly
        self.hx = lx / nelx
        self.hy = ly / nely
        self._np = np
        self.node_coordinates = self._build_node_coordinates(np=np)
        self.connectivity = self._build_connectivity()
        self.element_dofs = self._build_element_dofs()
        self.num_nodes = self.node_coordinates.shape[0]
        self.num_elements = self.connectivity.shape[0]
        self.ndof = self.num_nodes * 2
        self._ke_cache: dict[tuple[float, float], object] = {}
        self._assembly_rows, self._assembly_cols = self._build_assembly_indices(np=np)

    def metadata(self) -> dict[str, object]:
        return {
            "mesh_type": "structured_quad",
            "nelx": self.nelx,
            "nely": self.nely,
            "lx": self.lx,
            "ly": self.ly,
            "num_nodes": self.num_nodes,
            "num_elements": self.num_elements,
        }

    def load_and_boundary(
        self,
        *,
        node_selector: str,
        dof: str,
        magnitude: float,
        fixed_boundary: str,
    ) -> tuple[object, object]:
        np = self._np
        force_vector = np.zeros(self.ndof, dtype=float)
        fixed_nodes = self._boundary_nodes(fixed_boundary)
        fixed_dofs = np.sort(np.concatenate([2 * fixed_nodes, 2 * fixed_nodes + 1]))

        load_node = self._selected_load_node(node_selector)
        dof_index = 0 if dof == "x" else 1
        target_dof = int(2 * load_node + dof_index)
        if np.any(fixed_dofs == target_dof):
            raise ValueError("topology.load selects a node constrained by topology.boundary.")
        force_vector[target_dof] = magnitude
        return force_vector, fixed_dofs

    def compliance_and_sensitivity(
        self,
        *,
        densities: object,
        youngs_modulus: float,
        poisson_ratio: float,
        penal: float,
        density_min: float,
        force_vector: object,
        fixed_dofs: object,
        scipy_sparse: object,
        scipy_splinalg: object,
        warnings_module: object,
        np: object,
    ) -> tuple[float, object]:
        density_values = np.asarray(densities, dtype=float).reshape(self.num_elements)
        if np.any(density_values < 0.0) or np.any(density_values > 1.0 + 1e-9):
            raise ValueError("Topology densities must remain within [0, 1].")

        ke = self._element_stiffness(youngs_modulus, poisson_ratio, np=np)
        element_moduli = density_min + (1.0 - density_min) * density_values**penal
        stiffness_data = (ke.reshape(1, -1) * element_moduli.reshape(-1, 1)).reshape(-1)
        stiffness = scipy_sparse.coo_matrix(
            (stiffness_data, (self._assembly_rows, self._assembly_cols)),
            shape=(self.ndof, self.ndof),
        ).tocsc()

        all_dofs = np.arange(self.ndof, dtype=int)
        free_dofs = np.setdiff1d(all_dofs, fixed_dofs)
        if free_dofs.size == 0:
            raise RuntimeError("Topology solve is singular because no free degrees of freedom remain.")

        reduced_stiffness = stiffness[free_dofs][:, free_dofs]
        reduced_force = np.asarray(force_vector, dtype=float)[free_dofs]
        displacements = np.zeros(self.ndof, dtype=float)

        with warnings_module.catch_warnings():
            warnings_module.simplefilter("error", category=getattr(scipy_splinalg, "MatrixRankWarning", Warning))
            try:
                displacements[free_dofs] = scipy_splinalg.spsolve(reduced_stiffness, reduced_force)
            except Exception as exc:
                raise RuntimeError(
                    "Topology solve failed or became singular. Check the topology boundary and load setup."
                ) from exc

        if not np.all(np.isfinite(displacements)):
            raise RuntimeError("Topology solve produced non-finite displacements.")

        element_displacements = displacements[self.element_dofs]
        strain_energy = np.einsum("bi,ij,bj->b", element_displacements, ke, element_displacements)
        compliance = float(np.asarray(force_vector, dtype=float).dot(displacements))
        sensitivity = -(1.0 - density_min) * penal * density_values ** (penal - 1.0) * strain_energy
        return compliance, sensitivity

    def _build_node_coordinates(self, *, np: object) -> object:
        coordinates = []
        for iy in range(self.nely + 1):
            y = iy * self.hy
            for ix in range(self.nelx + 1):
                x = ix * self.hx
                coordinates.append((x, y))
        return np.asarray(coordinates, dtype=float)

    def _build_connectivity(self) -> object:
        np = self._np
        elements = []
        for iy in range(self.nely):
            for ix in range(self.nelx):
                n1 = iy * (self.nelx + 1) + ix
                n2 = n1 + 1
                n4 = n1 + self.nelx + 1
                n3 = n4 + 1
                elements.append((n1, n2, n3, n4))
        return np.asarray(elements, dtype=int)

    def _build_element_dofs(self) -> object:
        np = self._np
        dofs = np.zeros((self.connectivity.shape[0], 8), dtype=int)
        for idx, element in enumerate(self.connectivity):
            element_dofs = []
            for node in element:
                element_dofs.extend([2 * int(node), 2 * int(node) + 1])
            dofs[idx, :] = element_dofs
        return dofs

    def _build_assembly_indices(self, *, np: object) -> tuple[object, object]:
        row_blocks = np.repeat(self.element_dofs, 8, axis=1)
        col_blocks = np.tile(self.element_dofs, (1, 8))
        return row_blocks.reshape(-1), col_blocks.reshape(-1)

    def _boundary_nodes(self, boundary: str) -> object:
        np = self._np
        if boundary == "min_x":
            mask = np.isclose(self.node_coordinates[:, 0], 0.0)
        elif boundary == "max_x":
            mask = np.isclose(self.node_coordinates[:, 0], self.lx)
        elif boundary == "min_y":
            mask = np.isclose(self.node_coordinates[:, 1], 0.0)
        elif boundary == "max_y":
            mask = np.isclose(self.node_coordinates[:, 1], self.ly)
        else:
            raise ValueError(f"Unsupported topology boundary selector '{boundary}'.")
        nodes = np.where(mask)[0]
        if nodes.size == 0:
            raise ValueError(f"Topology boundary selector '{boundary}' matched no nodes.")
        return nodes.astype(int)

    def _selected_load_node(self, selector: str) -> int:
        np = self._np
        if selector == "max_x_mid":
            boundary_nodes = self._boundary_nodes("max_x")
            target_y = self.ly * 0.5
            return int(boundary_nodes[np.argmin(np.abs(self.node_coordinates[boundary_nodes, 1] - target_y))])
        if selector == "max_x_min_y":
            boundary_nodes = self._boundary_nodes("max_x")
            return int(boundary_nodes[np.argmin(self.node_coordinates[boundary_nodes, 1])])
        if selector == "max_x_max_y":
            boundary_nodes = self._boundary_nodes("max_x")
            return int(boundary_nodes[np.argmax(self.node_coordinates[boundary_nodes, 1])])
        raise ValueError(f"Unsupported topology load selector '{selector}'.")

    def _element_stiffness(self, youngs_modulus: float, poisson_ratio: float, *, np: object) -> object:
        cache_key = (youngs_modulus, poisson_ratio)
        cached = self._ke_cache.get(cache_key)
        if cached is not None:
            return cached

        gauss_points = (-1.0 / sqrt(3.0), 1.0 / sqrt(3.0))
        constitutive = (youngs_modulus / (1.0 - poisson_ratio**2)) * np.asarray(
            [
                [1.0, poisson_ratio, 0.0],
                [poisson_ratio, 1.0, 0.0],
                [0.0, 0.0, (1.0 - poisson_ratio) * 0.5],
            ],
            dtype=float,
        )
        node_coordinates = np.asarray(
            [
                [0.0, 0.0],
                [self.hx, 0.0],
                [self.hx, self.hy],
                [0.0, self.hy],
            ],
            dtype=float,
        )
        ke = np.zeros((8, 8), dtype=float)

        for xi in gauss_points:
            for eta in gauss_points:
                dndxi = 0.25 * np.asarray(
                    [
                        [-(1.0 - eta), -(1.0 - xi)],
                        [1.0 - eta, -(1.0 + xi)],
                        [1.0 + eta, 1.0 + xi],
                        [-(1.0 + eta), 1.0 - xi],
                    ],
                    dtype=float,
                )
                jacobian = dndxi.T @ node_coordinates
                det_jacobian = float(np.linalg.det(jacobian))
                if det_jacobian <= 0.0:
                    raise RuntimeError("Structured topology mesh produced a non-positive element Jacobian.")
                dndxy = dndxi @ np.linalg.inv(jacobian)
                b_matrix = np.zeros((3, 8), dtype=float)
                for node_index in range(4):
                    b_matrix[0, 2 * node_index] = dndxy[node_index, 0]
                    b_matrix[1, 2 * node_index + 1] = dndxy[node_index, 1]
                    b_matrix[2, 2 * node_index] = dndxy[node_index, 1]
                    b_matrix[2, 2 * node_index + 1] = dndxy[node_index, 0]
                ke += b_matrix.T @ constitutive @ b_matrix * det_jacobian

        self._ke_cache[cache_key] = ke
        return ke


def _optimality_criteria_update(
    *,
    densities: object,
    objective_gradient: object,
    volume_gradient: object,
    target_volume_fraction: float,
    move_limit: float,
    density_min: float,
    np: object,
) -> object:
    current = np.asarray(densities, dtype=float).reshape(-1)
    dc = np.asarray(objective_gradient, dtype=float).reshape(-1)
    dv = np.asarray(volume_gradient, dtype=float).reshape(-1)

    if np.any(dv <= 0.0):
        raise RuntimeError("Topology volume sensitivities must remain positive for OC updates.")

    lower_lambda = 0.0
    upper_lambda = 1e9
    updated = current.copy()
    target_sum = target_volume_fraction * current.size
    for _ in range(80):
        midpoint = 0.5 * (lower_lambda + upper_lambda)
        ratio = np.maximum(0.0, -dc / (dv * max(midpoint, 1e-12)))
        candidate = current * np.sqrt(ratio)
        candidate = np.clip(candidate, current - move_limit, current + move_limit)
        candidate = np.clip(candidate, density_min, 1.0)
        if float(candidate.sum()) > target_sum:
            lower_lambda = midpoint
        else:
            upper_lambda = midpoint
        updated = candidate
        if upper_lambda - lower_lambda <= 1e-9 * (upper_lambda + lower_lambda + 1.0):
            break
    return updated
