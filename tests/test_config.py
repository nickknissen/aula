"""Tests for aula.config."""

import json
import logging
import os
import stat
import sys
from unittest.mock import patch

import pytest

from aula.config import load_config, save_config


def test_load_config_missing_file(tmp_path):
    config_file = tmp_path / "config.json"
    with patch("aula.config.CONFIG_FILE", config_file), patch("aula.config.CONFIG_DIR", tmp_path):
        result = load_config()
    assert result == {}


def test_load_config_valid(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"username": "test"}))
    with patch("aula.config.CONFIG_FILE", config_file), patch("aula.config.CONFIG_DIR", tmp_path):
        result = load_config()
    assert result == {"username": "test"}


def test_load_config_invalid_json(tmp_path, caplog):
    config_file = tmp_path / "config.json"
    config_file.write_text("not json")
    with patch("aula.config.CONFIG_FILE", config_file), patch("aula.config.CONFIG_DIR", tmp_path):
        result = load_config()
    assert result == {}
    assert any(record.levelno == logging.WARNING for record in caplog.records)
    assert str(config_file) in caplog.text


def test_save_config_keeps_previous_file_after_serialization_failure(tmp_path):
    config_file = tmp_path / "config.json"
    previous = json.dumps({"username": "barn0001"})
    config_file.write_text(previous)
    with (
        patch("aula.config.CONFIG_FILE", config_file),
        patch("aula.config.CONFIG_DIR", tmp_path),
        pytest.raises(TypeError),
    ):
        save_config({"username": object()})

    assert config_file.read_text() == previous
    assert list(tmp_path.glob("*.tmp")) == []


def test_save_config_keeps_previous_file_when_fsync_fails(tmp_path, monkeypatch, capsys):
    config_file = tmp_path / "config.json"
    previous = json.dumps({"username": "barn0001"})
    config_file.write_text(previous)

    def fail_sync(fd):
        raise OSError("cannot sync")

    monkeypatch.setattr(os, "fsync", fail_sync)
    with patch("aula.config.CONFIG_FILE", config_file), patch("aula.config.CONFIG_DIR", tmp_path):
        save_config({"username": "barn0002"})

    assert config_file.read_text() == previous
    assert list(tmp_path.glob("*.tmp")) == []
    assert "Error saving configuration: cannot sync" in capsys.readouterr().err


def test_save_config(tmp_path):
    config_file = tmp_path / "config.json"
    with patch("aula.config.CONFIG_FILE", config_file), patch("aula.config.CONFIG_DIR", tmp_path):
        save_config({"username": "test"})
    data = json.loads(config_file.read_text())
    assert data == {"username": "test"}


owner_only_modes = pytest.mark.skipif(
    sys.platform == "win32", reason="Windows has no owner-only file mode"
)


@owner_only_modes
def test_save_config_creates_owner_only_file(tmp_path):
    config_file = tmp_path / "config.json"
    with patch("aula.config.CONFIG_FILE", config_file), patch("aula.config.CONFIG_DIR", tmp_path):
        save_config({"username": "test"})
    assert stat.S_IMODE(config_file.stat().st_mode) == 0o600


@owner_only_modes
def test_save_config_tightens_existing_file(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text("{}")
    config_file.chmod(0o644)
    with patch("aula.config.CONFIG_FILE", config_file), patch("aula.config.CONFIG_DIR", tmp_path):
        save_config({"username": "test"})
    assert stat.S_IMODE(config_file.stat().st_mode) == 0o600
    assert json.loads(config_file.read_text()) == {"username": "test"}


def test_save_config_does_not_require_chmod(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text("{}")
    with (
        patch("aula.config.CONFIG_FILE", config_file),
        patch("aula.config.CONFIG_DIR", tmp_path),
        patch("os.fchmod", side_effect=OSError("not permitted")),
    ):
        save_config({"username": "test"})
    assert json.loads(config_file.read_text()) == {"username": "test"}
