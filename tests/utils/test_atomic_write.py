"""Tests for aula.utils.atomic_write."""

import os
from unittest.mock import patch

import pytest

from aula.utils.atomic_write import write_json_atomic


def test_serialisation_failure_leaves_no_temp_file_and_reraises(tmp_path):
    target = tmp_path / "out.json"
    with pytest.raises(TypeError):
        write_json_atomic(target, {"bad": object()})
    assert list(tmp_path.iterdir()) == []


def test_fsync_runs_before_replace(tmp_path):
    calls = []
    real_replace = os.replace

    def replace(src, dst):
        calls.append("replace")
        real_replace(src, dst)

    with (
        patch("os.fsync", side_effect=lambda fd: calls.append("fsync")),
        patch("os.replace", side_effect=replace),
    ):
        write_json_atomic(tmp_path / "out.json", {"a": 1})
    assert calls == ["fsync", "replace"]
