"""Manager for CKAN Ecosystem datasets."""

import json
import logging
import urllib.request
from pathlib import Path
from tempfile import NamedTemporaryFile

import polars as pl

from dartfx.ckan.ecosystem.models import EcosystemExtensions, EcosystemSites
from dartfx.ckan.server import CKANServer

logger = logging.getLogger(__name__)


class EcosystemManager:
    """Manages the fetching, caching, and querying of CKAN Ecosystem datasets."""

    def __init__(self, data_dir: Path | None = None) -> None:
        """Initialize the EcosystemManager.

        Args:
            data_dir: Optional override for the local data cache directory.
        """
        self.server = CKANServer("https://ecosystem.ckan.org")
        if data_dir is None:
            self.data_dir = self._resolve_data_dir()
        else:
            self.data_dir = data_dir
            self.data_dir.mkdir(parents=True, exist_ok=True)

        self.state_file = self.data_dir / "sync_state.json"

    def _resolve_data_dir(self) -> Path:
        """Resolve the best data directory, falling back to ~/.dartfx/ckan/ecosystem if needed."""
        # Primary: inside package
        primary_dir = Path(__file__).parent / "data"

        # Test if we can write to the primary dir
        try:
            primary_dir.mkdir(parents=True, exist_ok=True)
            test_file = primary_dir / ".write_test"
            test_file.touch()
            test_file.unlink()
            return primary_dir
        except (PermissionError, OSError):
            logger.debug("Primary cache dir %s is not writable. Falling back.", primary_dir)

        # Fallback
        fallback_dir = Path.home() / ".dartfx" / "ckan" / "ecosystem"
        fallback_dir.mkdir(parents=True, exist_ok=True)
        return fallback_dir

    def _get_sync_state(self) -> dict[str, str]:
        if self.state_file.exists():
            try:
                with open(self.state_file, encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                return {}
        return {}

    def _save_sync_state(self, state: dict[str, str]) -> None:
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)

    def sync(self, force: bool = False) -> None:
        """Fetch latest ecosystem datasets if outdated.

        Args:
            force: If True, bypass the out-of-date check and force a download.
        """
        logger.info("Starting ecosystem sync to %s", self.data_dir)
        state = self._get_sync_state()

        self._sync_dataset("ckan-sites-metadata", state, force)
        self._sync_dataset("ckan-extensions-metadata", state, force)

        self._save_sync_state(state)
        logger.info("Ecosystem sync complete.")

    def _sync_dataset(self, dataset_name: str, state: dict[str, str], force: bool) -> None:
        logger.info("Checking dataset: %s via package_show API...", dataset_name)
        dataset = self.server.get_dataset(dataset_name)
        if not dataset.resources:
            logger.warning("No resources found for dataset %s", dataset_name)
            return

        # Find the CSV resource
        csv_resource = next(
            (r for r in dataset.resources if r.format and r.format.lower() == "csv"),
            dataset.resources[0],
        )

        remote_modified = ""
        if csv_resource.metadata_modified:
            remote_modified = csv_resource.metadata_modified.isoformat()
        elif dataset.metadata_modified:
            remote_modified = dataset.metadata_modified.isoformat()

        local_modified = state.get(dataset_name)
        parquet_path = self.data_dir / f"{dataset_name}.parquet"

        if (
            not force
            and local_modified
            and remote_modified
            and local_modified >= remote_modified
            and parquet_path.exists()
        ):
            logger.info("Dataset %s is up-to-date.", dataset_name)
            return

        logger.info("Downloading dataset %s from %s...", dataset_name, csv_resource.url)
        if not csv_resource.url:
            logger.warning("Resource URL missing for %s", dataset_name)
            return

        with NamedTemporaryFile(suffix=".csv", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            # Download file with User-Agent
            req = urllib.request.Request(
                csv_resource.url,
                headers={"User-Agent": "dartfx-ckan/0.1.0 (https://github.com/DataArtifex/dartfx-ckan)"},
            )
            with urllib.request.urlopen(req) as response, open(tmp_path, "wb") as out_file:
                out_file.write(response.read())

            # Load into polars, handling potential type parsing issues
            df = pl.read_csv(tmp_path, infer_schema_length=10000, ignore_errors=True)

            # Save to parquet
            df.write_parquet(parquet_path)

            if remote_modified:
                state[dataset_name] = remote_modified

            logger.info("Saved %s to parquet (%d records).", dataset_name, len(df))
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def get_sites_dataframe(self) -> pl.DataFrame:
        """Return the sites dataset as a Polars DataFrame."""
        path = self.data_dir / "ckan-sites-metadata.parquet"
        if not path.exists():
            raise FileNotFoundError(f"Parquet file {path} not found. Run sync() first.")
        return pl.read_parquet(path)

    def get_extensions_dataframe(self) -> pl.DataFrame:
        """Return the extensions dataset as a Polars DataFrame."""
        path = self.data_dir / "ckan-extensions-metadata.parquet"
        if not path.exists():
            raise FileNotFoundError(f"Parquet file {path} not found. Run sync() first.")
        return pl.read_parquet(path)

    def get_sites(self) -> list[EcosystemSites]:
        """Return a list of parsed EcosystemSites models."""
        df = self.get_sites_dataframe()
        return [EcosystemSites(**row) for row in df.to_dicts()]

    def get_extensions(self) -> list[EcosystemExtensions]:
        """Return a list of parsed EcosystemExtensions models."""
        df = self.get_extensions_dataframe()
        return [EcosystemExtensions(**row) for row in df.to_dicts()]
