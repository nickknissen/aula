from ..utils.qr import TerminalQRDisplay
from ..widgets import easyiq_child_user_ids
from . import (  # noqa: F401  importing a module registers its commands on `cli`
    absence,
    account,
    agent,
    calendar,
    daily_summary,
    downloads,
    messages,
    presence,
    school,
    weekly_summary,
    widgets,
)
from ._app import cli

# Kept for library consumers that imported the private names before they moved.
_easyiq_child_user_ids = easyiq_child_user_ids
_TerminalQRDisplay = TerminalQRDisplay

__all__ = ["cli"]
