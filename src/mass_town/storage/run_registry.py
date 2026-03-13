from pathlib import Path

import yaml

from mass_town.storage.filesystem import ensure_directory


class RunRegistry:
    def start_run(self, run_id: str, run_root: Path) -> None:
        registry_path = ensure_directory(run_root) / "run_registry.yaml"
        data = self._read(registry_path)
        data[run_id] = {"status": "running"}
        registry_path.write_text(yaml.safe_dump(data, sort_keys=False))

    def finish_run(self, run_id: str, run_root: Path, status: str) -> None:
        registry_path = ensure_directory(run_root) / "run_registry.yaml"
        data = self._read(registry_path)
        data[run_id] = {"status": status}
        registry_path.write_text(yaml.safe_dump(data, sort_keys=False))

    def _read(self, path: Path) -> dict[str, dict[str, str]]:
        if not path.exists():
            return {}
        return yaml.safe_load(path.read_text()) or {}
