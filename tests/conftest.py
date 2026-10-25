from pathlib import Path

import click.testing
import pytest
from dotenv import load_dotenv

# Work around Click 8.2.2 bug where _NamedTextIOWrapper and StreamMixer.__del__
# prematurely close the underlying BytesIO buffers during garbage collection cycles.
if hasattr(click.testing, "_NamedTextIOWrapper"):
    click.testing._NamedTextIOWrapper.close = lambda _self: None  # type: ignore[method-assign]

if hasattr(click.testing, "StreamMixer"):
    click.testing.StreamMixer.__del__ = lambda self: None  # noqa: ARG005


@pytest.fixture(scope="session", autouse=True)
def load_env():
    dotenv_path = Path(__file__).parent / "../.env"  # Construct path from current test file dir
    load_dotenv(dotenv_path=dotenv_path)
