class OptimizerAdapter:
    def increase_thickness(self, current: float, step: float = 0.2) -> float:
        return round(current + step, 3)
