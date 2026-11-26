from types import ModuleType

import aula.cli


def patch_get_client(monkeypatch, get_client) -> None:
    """Make every CLI command log in through ``get_client`` instead of MitID."""
    for module in vars(aula.cli).values():
        if isinstance(module, ModuleType) and hasattr(module, "_get_client"):
            monkeypatch.setattr(module, "_get_client", get_client)
