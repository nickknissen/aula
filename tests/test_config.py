"""Tests for aula.config."""

import json
from unittest.mock import patch

from aula.config import load_config, save_config


def test_load_config_missing_file(tmp_path):
    config_file = tmp_path / "config.json"
    with patch("aula.config.CONFIG_FILE", config_file), patch(
        "aula.config.CONFIG_DIR", tmp_path
    ):
        result = load_config()
    assert result == {}


def test_load_config_valid(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text(json.dumps({"username": "test"}))
    with patch("aula.config.CONFIG_FILE", config_file), patch(
        "aula.config.CONFIG_DIR", tmp_path
    ):
        result = load_config()
    assert result == {"username": "test"}


def test_load_config_invalid_json(tmp_path):
    config_file = tmp_path / "config.json"
    config_file.write_text("not json")
    with patch("aula.config.CONFIG_FILE", config_file), patch(
        "aula.config.CONFIG_DIR", tmp_path
    ):
        result = load_config()
    assert result == {}


def test_save_config(tmp_path):
    config_file = tmp_path / "config.json"
    with patch("aula.config.CONFIG_FILE", config_file), patch(
        "aula.config.CONFIG_DIR", tmp_path
    ):
        save_config({"username": "test"})
    data = json.loads(config_file.read_text())
    assert data == {"username": "test"}
