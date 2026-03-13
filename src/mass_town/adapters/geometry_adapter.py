from mass_town.models.result import Diagnostic


class GeometryAdapter:
    def validate(self, design_variables: dict[str, float]) -> tuple[bool, str | None]:
        thickness = design_variables.get("thickness", 0.0)
        length = design_variables.get("length", 0.0)
        width = design_variables.get("width", 0.0)
        if thickness <= 0 or length <= 0 or width <= 0:
            return False, "All geometry dimensions must be positive."
        if thickness > min(length, width):
            return False, "Thickness cannot exceed in-plane dimensions."
        return True, None

    def failure(self, message: str) -> Diagnostic:
        return Diagnostic(
            code="geometry.invalid",
            message=message,
            task="geometry",
            details={},
        )
