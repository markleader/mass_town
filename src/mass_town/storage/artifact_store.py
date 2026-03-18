from pathlib import Path

from mass_town.models.artifacts import ArtifactRecord
from mass_town.models.design_state import DesignState
from mass_town.storage.filesystem import ensure_directory


class ArtifactStore:
    def record(self, run_root: Path, state: DesignState, artifacts: list[ArtifactRecord]) -> None:
        ensure_directory(run_root / "artifacts" / state.run_id)
        for artifact in artifacts:
            artifact_path = run_root / artifact.path
            ensure_directory(artifact_path.parent)
            if not artifact_path.exists():
                artifact_path.write_text(
                    f"name: {artifact.name}\nkind: {artifact.kind}\nmetadata: {artifact.metadata}\n"
                )

            metadata_path = artifact_path.with_name(f"{artifact_path.name}.metadata.txt")
            metadata_path.write_text(
                f"name: {artifact.name}\nkind: {artifact.kind}\nmetadata: {artifact.metadata}\n"
            )
