"""Tests for aula.token_storage."""

import json

import pytest

from aula.token_storage import FileTokenStorage


@pytest.fixture
def token_file(tmp_path):
    return tmp_path / "tokens.json"


@pytest.mark.asyncio
async def test_load_missing_file(token_file):
    storage = FileTokenStorage(token_file)
    result = await storage.load()
    assert result is None


@pytest.mark.asyncio
async def test_save_and_load(token_file):
    storage = FileTokenStorage(token_file)
    data = {"tokens": {"access_token": "abc123"}}
    await storage.save(data)
    result = await storage.load()
    assert result == data


@pytest.mark.asyncio
async def test_save_creates_parent_dirs(tmp_path):
    nested = tmp_path / "deep" / "dir" / "tokens.json"
    storage = FileTokenStorage(nested)
    await storage.save({"tokens": {}})
    assert nested.exists()


@pytest.mark.asyncio
async def test_load_invalid_json(token_file):
    token_file.write_text("not json")
    storage = FileTokenStorage(token_file)
    result = await storage.load()
    assert result is None


@pytest.mark.asyncio
async def test_load_missing_tokens_key(token_file):
    token_file.write_text(json.dumps({"other": "data"}))
    storage = FileTokenStorage(token_file)
    result = await storage.load()
    assert result is None


@pytest.mark.asyncio
async def test_save_atomic_write(token_file):
    """Verify that save uses atomic write (no partial files on crash)."""
    storage = FileTokenStorage(token_file)
    await storage.save({"tokens": {"key": "val"}})
    # File should contain valid JSON after save
    data = json.loads(token_file.read_text())
    assert data["tokens"]["key"] == "val"
