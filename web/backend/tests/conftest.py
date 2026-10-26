"""Keep task accounting produced by workflow tests out of real user storage."""
import pytest

import task_usage


@pytest.fixture(autouse=True)
def isolate_task_accounting(tmp_path, monkeypatch):
    monkeypatch.setattr(task_usage, "STORAGE_ROOT", tmp_path / "accounting-storage")
