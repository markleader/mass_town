class MeshAdapter:
    def generate_quality(self, base_quality: float, refinement_bonus: float = 0.2) -> float:
        return min(1.0, base_quality + refinement_bonus)

    def estimate_elements(self, quality: float) -> int:
        return int(1000 + quality * 4000)
