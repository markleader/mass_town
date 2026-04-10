from pathlib import Path

import typer

from mass_town.config import WorkflowConfig
from mass_town.logging_utils import configure_logging
from mass_town.orchestration.state_manager import StateManager
from mass_town.runtime.local_runtime import LocalRuntime
from mass_town.runtime.outer_loop_runtime import OuterLoopRuntime

app = typer.Typer(help="Engineering workflow supervision prototype.")


@app.command()
def run(
    project_dir: Path = typer.Argument(..., exists=True, file_okay=False, dir_okay=True),
    runtime: str = typer.Option("local", "--runtime", help="Execution runtime: local or openmdao."),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
) -> None:
    """Run the example workflow inside a project directory."""
    configure_logging(verbose)
    config = WorkflowConfig.from_file(project_dir / "config.yaml")
    runtime_name = runtime.strip().lower()
    if runtime_name == "local":
        selected_runtime = OuterLoopRuntime(config) if config.llm.enabled else LocalRuntime(config)
    elif runtime_name == "openmdao":
        if config.llm.enabled:
            typer.echo(
                "LLM outer-loop orchestration is only supported with --runtime local.",
                err=True,
            )
            raise typer.Exit(code=2)
        from mass_town.runtime.openmdao_runtime import OpenMDAORuntime

        selected_runtime = OpenMDAORuntime(config)
    else:
        raise typer.BadParameter("runtime must be one of: local, openmdao")
    state = selected_runtime.run(project_dir / "design_state.yaml", project_dir)
    typer.echo(f"run_id={state.run_id} status={state.status} iteration={state.iteration}")


@app.command()
def status(
    state_file: Path = typer.Argument(..., exists=True, dir_okay=False),
) -> None:
    """Show a concise summary of the persisted design state."""
    state = StateManager().load(state_file)
    if state.topology_state.backend is not None or state.topology_state.iteration_count > 0:
        typer.echo(
            f"run_id={state.run_id} status={state.status} "
            f"objective={state.topology_state.objective} "
            f"volume_fraction={state.topology_state.volume_fraction} "
            f"converged={state.topology_state.converged}"
        )
        return
    typer.echo(
        f"run_id={state.run_id} status={state.status} "
        f"thickness={state.design_variables.get('thickness')} "
        f"max_stress={state.analysis_state.max_stress}"
    )


if __name__ == "__main__":
    app()
