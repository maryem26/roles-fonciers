"""Command-line interface."""

import logging
from pathlib import Path

import psycopg
import typer

from roles_fonciers.database import get_connection
from roles_fonciers.index_loader import load_municipalities

SQL_DIR = Path(__file__).resolve().parents[2] / "sql"

app = typer.Typer(
    help="Import des rôles d'évaluation foncière du Québec dans PostgreSQL.",
    no_args_is_help=True,
)
log = logging.getLogger(__name__)


@app.callback()
def main(
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Afficher les détails."),
) -> None:
    """Configure logging for every command."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )


@app.command("init-db")
def init_db() -> None:
    """Crée les tables (sans danger si elles existent déjà)."""
    sql_files = sorted(SQL_DIR.glob("*.sql"))
    if not sql_files:
        typer.echo(f"Aucun fichier SQL trouvé dans {SQL_DIR}", err=True)
        raise typer.Exit(code=1)

    try:
        with get_connection() as conn:
            # The SQL file has its own BEGIN/COMMIT, so no automatic transaction.
            conn.autocommit = True
            for path in sql_files:
                log.info("Applying %s", path.name)
                conn.execute(path.read_text(encoding="utf-8"))
    except psycopg.OperationalError as exc:
        typer.echo(f"Connexion à la base impossible : {exc}", err=True)
        typer.echo("La base est-elle démarrée ? (docker compose up -d)", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"Base prête ({len(sql_files)} fichier(s) SQL appliqué(s)).")


@app.command("load-index")
def load_index(
    csv_path: Path = typer.Argument(
        ..., exists=True, dir_okay=False, help="Fichier CSV de l'index des rôles."
    ),
) -> None:
    """Charge les municipalités à partir de l'index CSV."""
    try:
        loaded, skipped = load_municipalities(csv_path)
    except ValueError as exc:
        typer.echo(f"Fichier d'index invalide : {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except psycopg.OperationalError as exc:
        typer.echo(f"Connexion à la base impossible : {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(f"{loaded} municipalité(s) chargée(s), {skipped} ligne(s) ignorée(s).")
    if skipped:
        typer.echo("Les lignes ignorées sont détaillées dans les avertissements ci-dessus.")