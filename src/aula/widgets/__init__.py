"""Widget system for Aula external providers."""

from .base import BaseWidget, WidgetRegistry
from .biblioteket import BibliotekWidget
from .minuddannelse_opgaver import MinUddannelseOpgaverWidget

# Initialize the widget registry
widget_registry = WidgetRegistry()

# Register widgets
widget_registry.register(BibliotekWidget())
widget_registry.register(MinUddannelseOpgaverWidget())

__all__ = [
    "BaseWidget",
    "WidgetRegistry", 
    "widget_registry",
    "BibliotekWidget",
    "MinUddannelseOpgaverWidget",
]