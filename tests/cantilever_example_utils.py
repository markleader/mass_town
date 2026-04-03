import shutil
from pathlib import Path


def copy_cantilever_examples(tmp_path: Path) -> tuple[Path, Path]:
    examples_root = tmp_path / "examples"
    solid_source = Path("examples/solid_cantilever_problem")
    shell_source = Path("examples/shell_cantilever_problem")
    solid_project_dir = examples_root / "solid_cantilever_problem"
    shell_project_dir = examples_root / "shell_cantilever_problem"
    shutil.copytree(
        solid_source,
        solid_project_dir,
        ignore=shutil.ignore_patterns("results", "__pycache__"),
    )
    shutil.copytree(
        shell_source,
        shell_project_dir,
        ignore=shutil.ignore_patterns("results", "__pycache__"),
    )
    return solid_project_dir, shell_project_dir
