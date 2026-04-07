from pathlib import Path

from mass_town.constraints import AggregatedStressConstraint, ConstraintSet
from mass_town.disciplines.cad import CADBackend, CADRequest, CADResult
from mass_town.disciplines.contracts import (
    MaterialReference,
    MeshToFEAManifest,
    NamedRegion,
    PropertyAssignment,
    read_mesh_to_fea_manifest,
    write_mesh_to_fea_manifest,
)
from mass_town.disciplines.fea import FEALoadCase, FEALoadCaseResult, FEARequest, FEAResult
from mass_town.disciplines.optimization import (
    OptimizationBackend,
    OptimizationRequest,
    OptimizationResult,
)
from mass_town.disciplines.postprocessing import (
    PostProcessingRequest,
    StructuralPostProcessingBackend,
)
from plugins.tacs.backend import TacsFEABackend


class MinimalCADBackend(CADBackend):
    name = "minimal_cad"

    def is_available(self) -> bool:
        return True

    def availability_reason(self) -> str | None:
        return None

    def prepare_geometry(self, request: CADRequest) -> CADResult:
        return CADResult(
            backend_name=self.name,
            regions=[
                NamedRegion(
                    id="skin",
                    name="skin",
                    element_kind="shell",
                    source="fixture",
                )
            ],
            metadata={"run_id": request.run_id},
        )


class MinimalOptimizationBackend(OptimizationBackend):
    name = "minimal_optimizer"

    def is_available(self) -> bool:
        return True

    def availability_reason(self) -> str | None:
        return None

    def optimize(self, request: OptimizationRequest) -> OptimizationResult:
        return OptimizationResult(
            backend_name=self.name,
            design_variables=dict(request.design_variables),
            converged=True,
            iteration_count=1,
        )


def test_new_discipline_interfaces_accept_minimal_backend_implementations(tmp_path: Path) -> None:
    cad_backend = MinimalCADBackend()
    cad_result = cad_backend.prepare_geometry(
        CADRequest(run_id="contract-run", output_directory=tmp_path)
    )

    optimizer_backend = MinimalOptimizationBackend()
    optimization_result = optimizer_backend.optimize(
        OptimizationRequest(
            run_id="contract-run",
            design_variables={"thickness": 1.0},
            responses={"mass": 2.0},
            report_directory=tmp_path,
        )
    )

    assert cad_result.regions[0].name == "skin"
    assert optimization_result.converged
    assert optimization_result.design_variables["thickness"] == 1.0


def test_mesh_to_fea_manifest_round_trips_named_regions_and_properties(tmp_path: Path) -> None:
    manifest_path = tmp_path / "mesh_to_fea.json"
    manifest = MeshToFEAManifest(
        mesh_path=tmp_path / "model.bdf",
        regions=[
            NamedRegion(
                id="skin",
                name="skin",
                element_kind="shell",
                source="gmsh_physical_group",
                source_id="10",
                export_pid=7,
                entity_dimension=2,
            )
        ],
        materials=[
            MaterialReference(
                id="aluminum",
                name="Aluminum",
                model="isotropic",
            )
        ],
        property_assignments=[
            PropertyAssignment(
                id="skin_property",
                region_id="skin",
                element_kind="shell",
                material_id="aluminum",
                thickness=1.0,
            )
        ],
    )

    write_mesh_to_fea_manifest(manifest, manifest_path)
    loaded = read_mesh_to_fea_manifest(manifest_path)

    assert loaded.regions[0].id == "skin"
    assert loaded.regions[0].export_pid == 7
    assert loaded.property_assignments[0].region_id == "skin"


def test_tacs_region_lookup_prefers_mesh_manifest_over_bdf_comments(tmp_path: Path) -> None:
    bdf_path = tmp_path / "model.bdf"
    bdf_path.write_text(
        "\n".join(
            [
                "CEND",
                "BEGIN BULK",
                "MAT1,1,70000.0,,0.3,1.0",
                "PSHELL,42,1,1.0",
                "GRID,1,,0.0,0.0,0.0",
                "GRID,2,,1.0,0.0,0.0",
                "GRID,3,,0.0,1.0,0.0",
                "CTRIA3,1,42,1,2,3",
                "ENDDATA",
            ]
        )
        + "\n"
    )
    manifest = MeshToFEAManifest(
        mesh_path=bdf_path,
        regions=[
            NamedRegion(
                id="skin",
                name="skin",
                element_kind="shell",
                source="gmsh_physical_group",
                export_pid=42,
            )
        ],
    )

    mapping = TacsFEABackend()._parse_region_pid_map(
        bdf_path,
        mesh_manifest=manifest,
    )

    assert mapping == {"skin": 42}


def test_tacs_region_lookup_falls_back_to_bdf_region_comments(tmp_path: Path) -> None:
    bdf_path = tmp_path / "model.bdf"
    bdf_path.write_text(
        "\n".join(
            [
                "$ REGION pid=3 gmsh_id=10 kind=shell name=skin",
                "CEND",
                "BEGIN BULK",
                "MAT1,1,70000.0,,0.3,1.0",
                "PSHELL,3,1,1.0",
                "ENDDATA",
            ]
        )
        + "\n"
    )

    mapping = TacsFEABackend()._parse_region_pid_map(bdf_path)

    assert mapping == {"skin": 3}


def test_structural_postprocessing_selects_worst_case_and_aggregates_stress(
    tmp_path: Path,
) -> None:
    fea_request = FEARequest(
        report_directory=tmp_path,
        log_directory=tmp_path,
        solution_directory=tmp_path,
        run_id="post-run",
        allowable_stress=100.0,
        case_name="center_shear",
        load_cases={
            "center_shear": FEALoadCase(loads={"force": 1.0}),
            "center_bending": FEALoadCase(loads={"force": 2.0}),
        },
        constraints=ConstraintSet(
            aggregated_stress=AggregatedStressConstraint(
                method="ks",
                source="load_cases",
                allowable=100.0,
                ks_weight=10.0,
            )
        ),
    )
    fea_result = FEAResult(
        backend_name="stub",
        passed=True,
        load_cases={
            "center_shear": FEALoadCaseResult(
                passed=True,
                max_stress=90.0,
                mass=1.0,
            ),
            "center_bending": FEALoadCaseResult(
                passed=True,
                max_stress=120.0,
                mass=1.0,
            ),
        },
    )

    result = StructuralPostProcessingBackend().process(
        PostProcessingRequest(
            fea_request=fea_request,
            fea_result=fea_result,
        )
    )

    assert result.worst_case_name == "center_bending"
    assert result.aggregated_stress is not None
    assert result.aggregated_stress.controlling_case == "center_bending"
    assert not result.passed
