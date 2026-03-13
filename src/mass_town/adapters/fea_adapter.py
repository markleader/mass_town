class FEAAdapter:
    def compute_max_stress(self, force: float, thickness: float, mesh_quality: float) -> float:
        effective_area = max(thickness * 10.0, 0.1)
        discretization_penalty = 1.0 + max(0.0, 0.8 - mesh_quality)
        return force * 10.0 / effective_area * discretization_penalty
