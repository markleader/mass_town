from pathlib import Path

import yaml

from mass_town.models.design_state import DesignState


class StateManager:
    def load(self, path: Path) -> DesignState:
        data = yaml.safe_load(path.read_text()) or {}
        return DesignState.model_validate(data)

    def save(self, state: DesignState, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(state.model_dump(mode="json"), sort_keys=False))
