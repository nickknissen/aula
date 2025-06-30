"""Base widget classes for Aula external providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional
import httpx


@dataclass
class WidgetData:
    """Base class for widget response data."""
    widget_id: str
    raw_data: Dict[str, Any]


class BaseWidget(ABC):
    """Abstract base class for Aula widgets."""
    
    @property
    @abstractmethod
    def widget_id(self) -> str:
        """Unique widget identifier (e.g., '0019', '0030')."""
        pass
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable widget name."""
        pass
    
    @property
    @abstractmethod
    def base_url(self) -> str:
        """Base URL for the widget API."""
        pass
    
    @abstractmethod
    async def fetch_data(
        self, 
        client: httpx.AsyncClient, 
        token: str, 
        **params: Any
    ) -> WidgetData:
        """
        Fetch data from the widget API.
        
        Args:
            client: HTTP client to use for requests
            token: Authentication token from Aula
            **params: Additional parameters for the API call
            
        Returns:
            WidgetData with parsed response
        """
        pass
    
    def build_url(self, endpoint: str = "") -> str:
        """Build full API URL for this widget."""
        return f"{self.base_url.rstrip('/')}/{endpoint.lstrip('/')}" if endpoint else self.base_url


class WidgetRegistry:
    """Simple registry for managing widgets."""
    
    def __init__(self):
        self._widgets: Dict[str, BaseWidget] = {}
    
    def register(self, widget: BaseWidget) -> None:
        """Register a widget."""
        self._widgets[widget.widget_id] = widget
    
    def get_widget(self, widget_id: str) -> Optional[BaseWidget]:
        """Get a widget by ID."""
        return self._widgets.get(widget_id)
    
    def list_widgets(self) -> List[BaseWidget]:
        """List all registered widgets."""
        return list(self._widgets.values())
    
    def get_widget_ids(self) -> List[str]:
        """Get all registered widget IDs."""
        return list(self._widgets.keys())