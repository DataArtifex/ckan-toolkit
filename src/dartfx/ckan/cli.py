"""Command line interface for dartfx-ckan."""

import logging

import typer

from dartfx.ckan.ecosystem.manager import EcosystemManager

app = typer.Typer(help="dartfx-ckan command line interface")

ecosystem_app = typer.Typer(help="Commands for the CKAN Ecosystem")
app.add_typer(ecosystem_app, name="ecosystem")


@ecosystem_app.command("sync")
def ecosystem_sync(
    force: bool = typer.Option(
        False,
        "--force",
        "-f",
        help="Force a synchronization even if data is up-to-date",
    ),
    verbose: bool = typer.Option(
        False,
        "--verbose",
        "-v",
        help="Enable verbose logging",
    ),
) -> None:
    """Synchronize the CKAN Ecosystem datasets to local Parquet files."""
    if verbose:
        logging.basicConfig(level=logging.INFO)
    else:
        logging.basicConfig(level=logging.WARNING)

    try:
        manager = EcosystemManager()
        manager.sync(force=force)
        typer.echo("Sync completed successfully.")
    except Exception as e:
        typer.secho(f"Error during sync: {e}", fg=typer.colors.RED)
        raise typer.Exit(code=1) from None


if __name__ == "__main__":
    app()
