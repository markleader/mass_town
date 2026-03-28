import importlib
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from mass_town.disciplines.meshing import MeshingBackend, MeshingRequest, MeshingResult
from mass_town.storage.filesystem import ensure_directory

from .exporters import export_msh, write_bdf
from .extraction import parse_gmsh_msh2

logger = logging.getLogger(__name__)

_STEP_SUFFIXES = {".step", ".stp"}


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

        if request.mesh_dimension == 2 and request.step_face_selector == "largest_planar":
            metadata = self._generate_planar_face_mesh(
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
        metadata["mesh_format"] = request.output_format
        metadata["intermediate_msh_path"] = str(intermediate_mesh_path)

        if request.output_format == "bdf":
            normalized_mesh = parse_gmsh_msh2(intermediate_mesh_path)
            output_path = write_bdf(normalized_mesh, mesh_directory / f"{geometry_path.stem}.bdf")
            metadata.update(normalized_mesh.metadata)
            element_count = len(normalized_mesh.elements)

        return MeshingResult(
            backend_name=self.name,
            mesh_path=output_path,
            quality=max(request.target_quality, 0.9),
            element_count=element_count,
            metadata=metadata,
            log_path=log_path,
        )

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
            "meshing_dimension": request.mesh_dimension,
            "step_face_selector": request.step_face_selector or "none",
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
            gmsh.option.setNumber("General.Terminal", 1)
            gmsh.option.setNumber("Mesh.MshFileVersion", 2.2)
            gmsh.option.setNumber("Mesh.MeshOnlyVisible", 1)
            gmsh.clear()
            gmsh.model.add(geometry_path.stem)
            gmsh.model.occ.importShapes(str(geometry_path))
            gmsh.model.occ.synchronize()

            target_tag, target_area = self._select_largest_planar_face(gmsh)
            physical_id = gmsh.model.addPhysicalGroup(2, [target_tag], 1)
            gmsh.model.setPhysicalName(2, physical_id, "selected_face")
            self._restrict_visibility_to_face(gmsh, target_tag)
            gmsh.model.mesh.generate(2)
            gmsh.write(str(intermediate_mesh_path))

            log_lines.extend(
                [
                    f"selected_face_tag={target_tag}",
                    f"selected_face_area={target_area}",
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
            "meshing_dimension": 2,
            "step_face_selector": "largest_planar",
            "selected_face_area": round(float(target_area), 6),
        }

    def _select_largest_planar_face(self, gmsh: Any) -> tuple[int, float]:
        planar_faces: list[tuple[int, float]] = []
        for dim, tag in gmsh.model.getEntities(2):
            entity_type = str(gmsh.model.getType(dim, tag)).lower()
            if "plane" not in entity_type:
                continue
            area = float(gmsh.model.occ.getMass(dim, tag))
            planar_faces.append((tag, area))

        if not planar_faces:
            raise ValueError("No planar STEP faces were found for shell meshing.")

        planar_faces.sort(key=lambda item: (item[1], item[0]), reverse=True)
        return planar_faces[0]

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
                "The gmsh Python package is required for planar-face STEP meshing."
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


def _unique_dim_tags(dim_tags: list[tuple[int, int]]) -> list[tuple[int, int]]:
    seen: set[tuple[int, int]] = set()
    ordered: list[tuple[int, int]] = []
    for dim_tag in dim_tags:
        if dim_tag in seen:
            continue
        seen.add(dim_tag)
        ordered.append(dim_tag)
    return ordered
