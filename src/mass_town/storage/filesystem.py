from dataclasses import dataclass
from pathlib import Path


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


@dataclass(frozen=True)
class RunLayout:
    root: Path
    logs_dir: Path
    mesh_dir: Path
    reports_dir: Path
    solver_dir: Path


def ensure_run_layout(run_root: Path, run_id: str) -> RunLayout:
    root = ensure_directory(run_root / "results" / run_id)
    return RunLayout(
        root=root,
        logs_dir=ensure_directory(root / "logs"),
        mesh_dir=ensure_directory(root / "mesh"),
        reports_dir=ensure_directory(root / "reports"),
        solver_dir=ensure_directory(root / "solver"),
    )
