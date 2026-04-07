import importlib
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from mass_town.disciplines.contracts import (
    MaterialReference,
    MeshToFEAManifest,
    NamedRegion,
    PropertyAssignment,
    write_mesh_to_fea_manifest,
)
from mass_town.disciplines.meshing import MeshingBackend, MeshingRequest, MeshingResult
from mass_town.storage.filesystem import ensure_directory

from .exporters import export_msh, write_bdf
from .extraction import parse_gmsh_msh2
from .mesh_model import NormalizedMesh

logger = logging.getLogger(__name__)

_STEP_SUFFIXES = {".step", ".stp"}
_FACE_SELECTOR_AXES = {
    "min_x": ("x", "min"),
    "max_x": ("x", "max"),
    "min_y": ("y", "min"),
    "max_y": ("y", "max"),
    "min_z": ("z", "min"),
    "max_z": ("z", "max"),
}


class GmshMeshingBackend(MeshingBackend):
    name = "gmsh"

    def __init__(self, executable: str = "gmsh") -> None:
        self.executable = executable

    def is_available(self) -> bool:
        return self._python_api_available() or self._executable_available()

    def availability_reason(self) -> str | None:
        if self.is_available():
            return None
        return (
            "Neither the gmsh Python package nor the configured gmsh executable "
            f"'{self.executable}' was available."
        )

    def generate_mesh(self, request: MeshingRequest) -> MeshingResult:
        if request.geometry_input_path is None:
            raise ValueError("The gmsh backend requires a STEP geometry input path.")

        geometry_path = request.geometry_input_path
        if geometry_path.suffix.lower() not in _STEP_SUFFIXES:
            raise ValueError(
                "The gmsh backend only supports STEP geometry input files "
                "(.step or .stp)."
            )
        if not geometry_path.exists():
            raise FileNotFoundError(f"Geometry input does not exist: {geometry_path}")

        mesh_directory = ensure_directory(request.mesh_directory)
        log_directory = ensure_directory(request.log_directory)
        intermediate_mesh_path = mesh_directory / f"{geometry_path.stem}.msh"
        log_path = log_directory / f"{geometry_path.stem}.gmsh.log"

        if request.mesh_dimension == 2 and request.step_face_selector is not None:
            if not self._python_api_available():
                raise RuntimeError(
                    "Selector-based STEP face meshing requires the gmsh Python package."
                )
            metadata = self._generate_planar_face_mesh(
                geometry_path=geometry_path,
                request=request,
                intermediate_mesh_path=intermediate_mesh_path,
                log_path=log_path,
            )
        elif request.mesh_dimension == 3 and self._python_api_available():
            metadata = self._generate_volume_mesh(
                geometry_path=geometry_path,
                request=request,
                intermediate_mesh_path=intermediate_mesh_path,
                log_path=log_path,
            )
        else:
            metadata = self._generate_with_executable(
                geometry_path=geometry_path,
                request=request,
                intermediate_mesh_path=intermediate_mesh_path,
                log_path=log_path,
            )

        output_path = export_msh(intermediate_mesh_path)
        element_count = 0
        mesh_manifest = None
        mesh_manifest_path = None
        metadata["mesh_format"] = request.output_format
        metadata["intermediate_msh_path"] = str(intermediate_mesh_path)

        if request.output_format == "bdf":
            normalized_mesh = parse_gmsh_msh2(intermediate_mesh_path)
            output_path = write_bdf(normalized_mesh, mesh_directory / f"{geometry_path.stem}.bdf")
            mesh_manifest = self._build_mesh_to_fea_manifest(
                normalized_mesh=normalized_mesh,
                mesh_path=output_path,
                source_mesh_path=intermediate_mesh_path,
                metadata=metadata,
            )
            mesh_manifest_path = mesh_directory / f"{geometry_path.stem}.mesh_to_fea_manifest.json"
            write_mesh_to_fea_manifest(mesh_manifest, mesh_manifest_path)
            metadata.update(normalized_mesh.metadata)
            metadata["mesh_manifest_path"] = str(mesh_manifest_path)
            element_count = len(normalized_mesh.elements)

        return MeshingResult(
            backend_name=self.name,
            mesh_path=output_path,
            mesh_manifest_path=mesh_manifest_path,
            mesh_manifest=mesh_manifest,
            quality=max(request.target_quality, 0.9),
            element_count=element_count,
            metadata=metadata,
            log_path=log_path,
        )

    def _build_mesh_to_fea_manifest(
        self,
        *,
        normalized_mesh: NormalizedMesh,
        mesh_path: Path,
        source_mesh_path: Path,
        metadata: dict[str, str | float | int | bool],
    ) -> MeshToFEAManifest:
        material = MaterialReference(
            id="default_structural_material",
            name="Default Structural Material",
            model="implicit_solver_default",
            metadata={"source": "gmsh_bdf_export_placeholder"},
        )
        regions = [
            NamedRegion(
                id=region.name,
                name=region.name,
                element_kind=region.element_kind,
                source="gmsh_physical_group",
                source_id=(
                    str(region.gmsh_physical_id)
                    if region.gmsh_physical_id is not None
                    else None
                ),
                export_pid=region.pid,
                entity_dimension=region.entity_dim,
                metadata={
                    key: value
                    for key, value in {
                        "raw_name": region.raw_name or "",
                        "gmsh_physical_id": region.gmsh_physical_id,
                    }.items()
                    if value is not None
                },
            )
            for region in normalized_mesh.regions
        ]
        property_assignments = [
            PropertyAssignment(
                id=f"{region.name}_property",
                region_id=region.name,
                element_kind=region.element_kind,
                material_id=material.id,
                thickness=1.0 if region.element_kind == "shell" else None,
                metadata={
                    "export_pid": region.pid,
                    "source": "gmsh_bdf_export_placeholder",
                },
            )
            for region in normalized_mesh.regions
        ]
        return MeshToFEAManifest(
            mesh_path=mesh_path,
            source_mesh_path=source_mesh_path,
            regions=regions,
            materials=[material],
            property_assignments=property_assignments,
            metadata=dict(metadata),
        )

    def _generate_volume_mesh(
        self,
        *,
        geometry_path: Path,
        request: MeshingRequest,
        intermediate_mesh_path: Path,
        log_path: Path,
    ) -> dict[str, str | float | int | bool]:
        gmsh = self._load_gmsh_python_module()
        log_lines: list[str] = [
            f"geometry={geometry_path}",
            "mode=python-api-volume",
            f"mesh_dimension={request.mesh_dimension}",
            f"volume_element_preference={request.volume_element_preference}",
        ]
        metadata: dict[str, str | float | int | bool]

        try:
            gmsh.initialize()
            self._configure_python_api_session(gmsh)
            if request.volume_element_preference == "hex_preferred":
                try:
                    metadata = self._generate_hex_volume_mesh(
                        gmsh=gmsh,
                        geometry_path=geometry_path,
                        intermediate_mesh_path=intermediate_mesh_path,
                    )
                    log_lines.append("volume_meshing_result=hex")
                except Exception as exc:
                    log_lines.append(f"hex_preferred_failed={exc}")
                    gmsh.clear()
                    metadata = self._generate_tet_volume_mesh(
                        gmsh=gmsh,
                        geometry_path=geometry_path,
                        intermediate_mesh_path=intermediate_mesh_path,
                    )
                    metadata["volume_meshing_fallback_reason"] = str(exc)
                    metadata["volume_meshing_result"] = "tetrahedral_fallback"
                    log_lines.append("volume_meshing_result=tetrahedral_fallback")
            else:
                metadata = self._generate_tet_volume_mesh(
                    gmsh=gmsh,
                    geometry_path=geometry_path,
                    intermediate_mesh_path=intermediate_mesh_path,
                )
                metadata["volume_meshing_result"] = "tetrahedral"
                log_lines.append("volume_meshing_result=tetrahedral")
            metadata["volume_element_preference"] = request.volume_element_preference
        except Exception as exc:
            log_lines.append(f"error={exc}")
            raise RuntimeError(f"gmsh 3D meshing failed. See log: {log_path}") from exc
        finally:
            log_path.write_text("\n".join(log_lines) + "\n")
            gmsh.finalize()

        if not intermediate_mesh_path.exists():
            raise RuntimeError(
                f"gmsh completed without producing a mesh file: {intermediate_mesh_path}"
            )
        return metadata

    def _generate_with_executable(
        self,
        *,
        geometry_path: Path,
        request: MeshingRequest,
        intermediate_mesh_path: Path,
        log_path: Path,
    ) -> dict[str, str | float | int | bool]:
        if not self._executable_available():
            raise RuntimeError(
                "The gmsh executable is required for this meshing mode and was not found on PATH."
            )

        command = [
            self.executable,
            str(geometry_path),
            f"-{request.mesh_dimension}",
            "-format",
            "msh2",
            "-o",
            str(intermediate_mesh_path),
        ]
        logger.info("Running gmsh meshing command: %s", " ".join(command))
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        log_path.write_text(completed.stdout + completed.stderr)

        if completed.returncode != 0:
            raise RuntimeError(
                f"gmsh failed with exit code {completed.returncode}. See log: {log_path}"
            )
        if not intermediate_mesh_path.exists():
            raise RuntimeError(
                f"gmsh completed without producing a mesh file: {intermediate_mesh_path}"
            )

        return {
            "command": " ".join(command),
            "mesh_generation_mode": "gmsh_executable",
            "meshing_dimension": request.mesh_dimension,
            "step_face_selector": request.step_face_selector or "none",
            "volume_element_preference": request.volume_element_preference,
        }

    def _generate_planar_face_mesh(
        self,
        *,
        geometry_path: Path,
        request: MeshingRequest,
        intermediate_mesh_path: Path,
        log_path: Path,
    ) -> dict[str, str | float | int | bool]:
        gmsh = self._load_gmsh_python_module()
        log_lines: list[str] = [
            f"geometry={geometry_path}",
            "mode=python-api-planar-face",
            f"mesh_dimension={request.mesh_dimension}",
            f"selector={request.step_face_selector}",
        ]

        try:
            gmsh.initialize()
            self._configure_python_api_session(gmsh)
            gmsh.model.add(geometry_path.stem)
            gmsh.model.occ.importShapes(str(geometry_path))
            gmsh.model.occ.synchronize()

            target_tag, target_area, target_center = self._select_planar_face(
                gmsh,
                request.step_face_selector or "largest_planar",
            )
            physical_id = gmsh.model.addPhysicalGroup(2, [target_tag], 1)
            gmsh.model.setPhysicalName(2, physical_id, "selected_face")
            self._restrict_visibility_to_face(gmsh, target_tag)
            gmsh.model.mesh.generate(2)
            gmsh.write(str(intermediate_mesh_path))

            log_lines.extend(
                [
                    f"selected_face_tag={target_tag}",
                    f"selected_face_area={target_area}",
                    f"selected_face_center={target_center}",
                    f"physical_group={physical_id}",
                    f"output={intermediate_mesh_path}",
                ]
            )
        except Exception as exc:
            log_lines.append(f"error={exc}")
            raise RuntimeError(f"gmsh planar-face meshing failed. See log: {log_path}") from exc
        finally:
            log_path.write_text("\n".join(log_lines) + "\n")
            gmsh.finalize()

        if not intermediate_mesh_path.exists():
            raise RuntimeError(
                f"gmsh completed without producing a mesh file: {intermediate_mesh_path}"
            )

        return {
            "command": "python:gmsh",
            "mesh_generation_mode": "python_api_planar_face",
            "meshing_dimension": 2,
            "step_face_selector": request.step_face_selector or "largest_planar",
            "selected_face_area": round(float(target_area), 6),
        }

    def _configure_python_api_session(self, gmsh: Any) -> None:
        gmsh.option.setNumber("General.Terminal", 1)
        gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
        gmsh.option.setNumber("Mesh.MeshOnlyVisible", 1)
        gmsh.clear()

    def _generate_hex_volume_mesh(
        self,
        *,
        gmsh: Any,
        geometry_path: Path,
        intermediate_mesh_path: Path,
    ) -> dict[str, str | float | int | bool]:
        volume_tags = self._import_step_volumes(gmsh, geometry_path)
        self._apply_transfinite_hex_controls(gmsh, volume_tags)
        gmsh.model.mesh.generate(3)
        volume_types, _, _ = gmsh.model.mesh.getElements(3)
        if not volume_types:
            raise RuntimeError("No 3D elements were generated for the STEP volume.")
        if any(int(element_type) != 5 for element_type in volume_types):
            type_summary = ",".join(str(int(element_type)) for element_type in volume_types)
            raise RuntimeError(
                "Hex-preferred meshing did not produce an all-hexahedral volume mesh. "
                f"Encountered gmsh element types: {type_summary}."
            )
        gmsh.write(str(intermediate_mesh_path))
        return {
            "command": "python:gmsh",
            "mesh_generation_mode": "python_api_hex_volume",
            "meshing_dimension": 3,
            "volume_element_preference": "hex_preferred",
            "volume_meshing_strategy": "transfinite_recombine",
            "volume_count": len(volume_tags),
        }

    def _generate_tet_volume_mesh(
        self,
        *,
        gmsh: Any,
        geometry_path: Path,
        intermediate_mesh_path: Path,
    ) -> dict[str, str | float | int | bool]:
        volume_tags = self._import_step_volumes(gmsh, geometry_path)
        gmsh.model.mesh.generate(3)
        gmsh.write(str(intermediate_mesh_path))
        return {
            "command": "python:gmsh",
            "mesh_generation_mode": "python_api_tet_volume",
            "meshing_dimension": 3,
            "volume_element_preference": "tet_only",
            "volume_meshing_strategy": "unstructured_tetrahedral",
            "volume_count": len(volume_tags),
        }

    def _import_step_volumes(self, gmsh: Any, geometry_path: Path) -> list[int]:
        gmsh.model.add(geometry_path.stem)
        gmsh.model.occ.importShapes(str(geometry_path))
        gmsh.model.occ.synchronize()
        volume_tags = [tag for dim, tag in gmsh.model.getEntities(3) if dim == 3]
        if not volume_tags:
            raise ValueError("No STEP volumes were found for 3D solid meshing.")
        for index, volume_tag in enumerate(volume_tags, start=1):
            physical_id = gmsh.model.addPhysicalGroup(3, [volume_tag], index)
            gmsh.model.setPhysicalName(3, physical_id, f"volume_{index}")
        return volume_tags

    def _apply_transfinite_hex_controls(self, gmsh: Any, volume_tags: list[int]) -> None:
        vertices = gmsh.model.getEntities(0)
        curves = gmsh.model.getEntities(1)
        surfaces = gmsh.model.getEntities(2)
        if len(volume_tags) != 1 or len(vertices) != 8 or len(curves) != 12 or len(surfaces) != 6:
            raise RuntimeError(
                "Hex-preferred meshing currently supports single-volume box-like solids only."
            )

        curve_lengths = [
            self._entity_length_from_bbox(gmsh.model.getBoundingBox(dim, tag))
            for dim, tag in curves
        ]
        positive_lengths = [length for length in curve_lengths if length > 0.0]
        if not positive_lengths:
            raise RuntimeError("Could not determine STEP curve lengths for transfinite meshing.")
        base_length = min(positive_lengths)
        for dim, tag in curves:
            length = self._entity_length_from_bbox(gmsh.model.getBoundingBox(dim, tag))
            point_count = max(3, int(round(length / base_length)) * 2 + 1)
            gmsh.model.mesh.setTransfiniteCurve(tag, point_count)

        for _, tag in surfaces:
            gmsh.model.mesh.setTransfiniteSurface(tag)
            gmsh.model.mesh.setRecombine(2, tag)

        for volume_tag in volume_tags:
            gmsh.model.mesh.setTransfiniteVolume(volume_tag)

    def _select_planar_face(
        self,
        gmsh: Any,
        selector: str,
    ) -> tuple[int, float, tuple[float, float, float]]:
        planar_faces: list[tuple[int, float, tuple[float, float, float], tuple[float, float, float, float, float, float]]] = []
        for dim, tag in gmsh.model.getEntities(2):
            entity_type = str(gmsh.model.getType(dim, tag)).lower()
            if "plane" not in entity_type:
                continue
            area = float(gmsh.model.occ.getMass(dim, tag))
            bbox = tuple(float(value) for value in gmsh.model.getBoundingBox(dim, tag))
            center = (
                0.5 * (bbox[0] + bbox[3]),
                0.5 * (bbox[1] + bbox[4]),
                0.5 * (bbox[2] + bbox[5]),
            )
            planar_faces.append((tag, area, center, bbox))

        if not planar_faces:
            raise ValueError("No planar STEP faces were found for shell meshing.")

        if selector == "largest_planar":
            planar_faces.sort(key=lambda item: (item[1], item[0]), reverse=True)
            tag, area, center, _ = planar_faces[0]
            return tag, area, center

        axis_name, extreme = _FACE_SELECTOR_AXES[selector]
        axis_index = {"x": 0, "y": 1, "z": 2}[axis_name]
        reverse = extreme == "max"
        planar_faces.sort(
            key=lambda item: (
                item[2][axis_index],
                -(item[3][axis_index + 3] - item[3][axis_index]),
                item[1],
                item[0],
            ),
            reverse=reverse,
        )
        tag, area, center, _ = planar_faces[0]
        return tag, area, center

    def _restrict_visibility_to_face(self, gmsh: Any, face_tag: int) -> None:
        all_entities = gmsh.model.getEntities()
        gmsh.model.setVisibility(all_entities, 0, recursive=False)
        visible_entities = [(2, face_tag)]
        visible_entities.extend(
            gmsh.model.getBoundary([(2, face_tag)], combined=False, oriented=False, recursive=True)
        )
        gmsh.model.setVisibility(_unique_dim_tags(visible_entities), 1, recursive=True)

    def _load_gmsh_python_module(self) -> Any:
        try:
            return importlib.import_module("gmsh")
        except ImportError as exc:
            raise RuntimeError(
                "The gmsh Python package is required for selector-driven STEP meshing."
            ) from exc

    def _python_api_available(self) -> bool:
        try:
            importlib.import_module("gmsh")
        except ImportError:
            return False
        return True

    def _executable_available(self) -> bool:
        executable_path = Path(self.executable)
        if executable_path.is_absolute():
            return executable_path.exists() and os.access(executable_path, os.X_OK)
        return shutil.which(self.executable) is not None

    def _entity_length_from_bbox(self, bbox: tuple[float, float, float, float, float, float]) -> float:
        return max(
            float(bbox[3]) - float(bbox[0]),
            float(bbox[4]) - float(bbox[1]),
            float(bbox[5]) - float(bbox[2]),
        )


def _unique_dim_tags(dim_tags: list[tuple[int, int]]) -> list[tuple[int, int]]:
    seen: set[tuple[int, int]] = set()
    ordered: list[tuple[int, int]] = []
    for dim_tag in dim_tags:
        if dim_tag in seen:
            continue
        seen.add(dim_tag)
        ordered.append(dim_tag)
    return ordered
