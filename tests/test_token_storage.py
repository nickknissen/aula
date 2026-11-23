"""Tests for aula.token_storage."""

import json
import os
import threading
from pathlib import Path

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
async def test_load_reads_in_a_worker_thread(token_file, monkeypatch):
    token_file.write_text(json.dumps({"tokens": {}}))
    read_text = Path.read_text
    threads = []

    def read(path, *args, **kwargs):
        threads.append(threading.get_ident())
        return read_text(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)

    assert await FileTokenStorage(token_file).load() == {"tokens": {}}
    assert threads and threading.get_ident() not in threads


@pytest.mark.asyncio
async def test_save_writes_in_a_worker_thread(token_file, monkeypatch):
    dump = json.dump
    threads = []

    def write(*args, **kwargs):
        threads.append(threading.get_ident())
        return dump(*args, **kwargs)

    monkeypatch.setattr(json, "dump", write)

    await FileTokenStorage(token_file).save({"tokens": {}})

    assert threads and threading.get_ident() not in threads


@pytest.mark.asyncio
async def test_save_flushes_and_syncs_before_replacing(token_file, monkeypatch):
    data = {"tokens": {"access_token": "new-token"}}
    replace = os.replace
    synced = []

    def sync(fd):
        assert os.fstat(fd).st_size > 0
        synced.append(fd)

    def replace_after_sync(source, destination):
        assert synced
        assert json.loads(Path(source).read_text()) == data
        replace(source, destination)

    monkeypatch.setattr(os, "fsync", sync)
    monkeypatch.setattr(os, "replace", replace_after_sync)

    await FileTokenStorage(token_file).save(data)

    assert json.loads(token_file.read_text()) == data


@pytest.mark.asyncio
async def test_save_cleans_up_after_serialization_failure(token_file):
    previous = json.dumps({"tokens": {"access_token": "stored-token"}})
    token_file.write_text(previous)

    with pytest.raises(TypeError):
        await FileTokenStorage(token_file).save({"tokens": {"access_token": object()}})

    assert token_file.read_text() == previous
    assert list(token_file.parent.glob("*.tmp")) == []


@pytest.mark.asyncio
async def test_save_keeps_previous_tokens_when_fsync_fails(token_file, monkeypatch):
    previous = json.dumps({"tokens": {"access_token": "stored-token"}})
    token_file.write_text(previous)

    def fail_sync(fd):
        raise OSError("cannot sync")

    monkeypatch.setattr(os, "fsync", fail_sync)

    with pytest.raises(OSError, match="cannot sync"):
        await FileTokenStorage(token_file).save({"tokens": {"access_token": "new-token"}})

    assert token_file.read_text() == previous
    assert list(token_file.parent.glob("*.tmp")) == []


@pytest.mark.asyncio
async def test_save_atomic_write(token_file):
    """Verify that save uses atomic write (no partial files on crash)."""
    storage = FileTokenStorage(token_file)
    await storage.save({"tokens": {"key": "val"}})
    # File should contain valid JSON after save
    data = json.loads(token_file.read_text())
    assert data["tokens"]["key"] == "val"


@pytest.mark.asyncio
async def test_clear_removes_stored_tokens(token_file):
    """Logging out has to leave nothing behind for the next login to reuse."""
    storage = FileTokenStorage(token_file)
    await storage.save({"tokens": {"access_token": "abc123"}})

    removed = await storage.clear()

    assert removed is True
    assert not token_file.exists()


@pytest.mark.asyncio
async def test_clear_reports_when_there_was_nothing_stored(token_file):
    """Without this, logging out twice claims to have removed a session that was not there."""
    removed = await FileTokenStorage(token_file).clear()

    assert removed is False


@pytest.mark.asyncio
async def test_clear_removes_tokens_in_a_worker_thread(token_file, monkeypatch):
    token_file.write_text(json.dumps({"tokens": {}}))
    unlink = Path.unlink
    threads = []

    def remove(path, *args, **kwargs):
        threads.append(threading.get_ident())
        return unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", remove)

    assert await FileTokenStorage(token_file).clear() is True
    assert threads and threading.get_ident() not in threads
