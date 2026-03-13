from pathlib import Path

from mass_town.models.artifacts import ArtifactRecord
from mass_town.models.design_state import DesignState
from mass_town.storage.filesystem import ensure_directory


class ArtifactStore:
    def record(self, run_root: Path, state: DesignState, artifacts: list[ArtifactRecord]) -> None:
        artifact_dir = ensure_directory(run_root / "artifacts" / state.run_id)
        for artifact in artifacts:
            artifact_path = artifact_dir / Path(artifact.path).name
            artifact_path.write_text(
                f"name: {artifact.name}\nkind: {artifact.kind}\nmetadata: {artifact.metadata}\n"
            )
