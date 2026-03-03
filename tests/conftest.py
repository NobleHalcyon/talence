import os
import tempfile
import pytest

@pytest.fixture(scope="session", autouse=True)
def isolated_test_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        os.environ["TALENCE_DB_PATH"] = db_path
        os.environ["TALENCE_DISABLE_STARTUP_SET_CHECK"] = "1"
        yield
