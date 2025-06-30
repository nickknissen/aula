"""Python client for Aula."""

__version__ = "0.1.0"  # Or fetch dynamically from pyproject.toml

from .api_client import AulaApiClient
from .models import (
    CalendarEvent,
    # Add other commonly used models if desired
    Child,
    DailyOverview,
    Message,
    MessageThread,
    Profile,
    # Widget data classes
    WidgetData,
    BibliotekData,
    LibraryLoan,
    MinUddannelseOpgaverData,
    Opgave,
    Hold,
    Forloeb,
)
from .widgets import widget_registry

__all__ = [
    "AulaApiClient",
    "Profile",
    "Child",
    "DailyOverview",
    "MessageThread",
    "Message",
    "CalendarEvent",
    "widget_registry",
    "WidgetData",
    "BibliotekData", 
    "LibraryLoan",
    "MinUddannelseOpgaverData",
    "Opgave",
    "Hold",
    "Forloeb",
    "__version__",
]
