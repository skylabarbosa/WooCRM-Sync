from pathlib import Path
import os

import pytest

os.environ.setdefault("APP_ENV", "demo")


def pytest_runtest_teardown(item):
    from app import main

    production_database = (Path(__file__).parents[1] / "woocrm.db").resolve()
    if Path(main.DATABASE_PATH).resolve() == production_database:
        pytest.fail("Tests must use a temporary database, not backend/woocrm.db")
