import logging
import os
import shutil
import subprocess
from pathlib import Path

from mass_town.disciplines.meshing import MeshingBackend, MeshingRequest, MeshingResult
from mass_town.storage.filesystem import ensure_directory

logger = logging.getLogger(__name__)


class GmshMeshingBackend(MeshingBackend):
    name = "gmsh"

    def __init__(self, executable: str = "gmsh") -> None:
        self.executable = executable

    def is_available(self) -> bool:
        executable_path = Path(self.executable)
        if executable_path.is_absolute():
            return executable_path.exists() and os.access(executable_path, os.X_OK)
        return shutil.which(self.executable) is not None

    def availability_reason(self) -> str | None:
        if self.is_available():
            return None
        return f"Executable '{self.executable}' was not found on PATH."

    def generate_mesh(self, request: MeshingRequest) -> MeshingResult:
        if request.geometry_input_path is None:
            raise ValueError("The gmsh backend requires a STEP geometry input path.")

        geometry_path = request.geometry_input_path
        if geometry_path.suffix.lower() != ".step":
            raise ValueError("The gmsh backend only supports .step geometry input files.")
        if not geometry_path.exists():
            raise FileNotFoundError(f"Geometry input does not exist: {geometry_path}")

        output_directory = ensure_directory(request.output_directory)
        mesh_path = output_directory / f"{geometry_path.stem}.msh"
        log_path = output_directory / f"{geometry_path.stem}.gmsh.log"
        command = [self.executable, str(geometry_path), "-3", "-o", str(mesh_path)]
        logger.info("Running gmsh meshing command: %s", " ".join(command))
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        log_path.write_text(completed.stdout + completed.stderr)

        if completed.returncode != 0:
            raise RuntimeError(
                f"gmsh failed with exit code {completed.returncode}. See log: {log_path}"
            )
        if not mesh_path.exists():
            raise RuntimeError(f"gmsh completed without producing a mesh file: {mesh_path}")

        return MeshingResult(
            backend_name=self.name,
            mesh_path=mesh_path,
            quality=max(request.target_quality, 0.9),
            element_count=0,
            metadata={"command": " ".join(command), "meshing_dimension": 3},
            log_path=log_path,
        )
