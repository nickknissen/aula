"""Biblioteket (Library) widget implementation."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional
import httpx

from .base import BaseWidget, WidgetData


@dataclass
class LibraryLoan:
    """Represents a library loan."""
    title: str
    author: str
    cover_image_url: str
    patron_display_name: str
    id: int
    due_date: str
    number_of_loans: int


@dataclass
class BibliotekData(WidgetData):
    """Biblioteket widget data."""
    loans: List[LibraryLoan]
    longterm_loans: List[LibraryLoan]
    reservations: List[Dict[str, Any]]  # Structure not clear from example
    branch_ids: List[str]


class BibliotekWidget(BaseWidget):
    """Widget for library status from Biblioteket system."""
    
    @property
    def widget_id(self) -> str:
        return "0019"
    
    @property
    def name(self) -> str:
        return "Biblioteket"
    
    @property
    def base_url(self) -> str:
        return "https://surf.cicero-suite.com/portal-api/rest/aula/library/status/v3"
    
    async def fetch_data(
        self, 
        client: httpx.AsyncClient, 
        token: str, 
        institutions: Optional[List[str]] = None,
        children: Optional[List[str]] = None,
        cover_image_height: int = 160,
        widget_version: str = "1.6",
        user_profile: str = "guardian",
        session_uuid: Optional[str] = None,
        **params: Any
    ) -> BibliotekData:
        """
        Fetch library status data.
        
        Args:
            client: HTTP client
            token: Authentication token
            institutions: List of institution IDs (defaults to profile institutions)
            children: List of child IDs (defaults to profile children)
            cover_image_height: Height for cover images
            widget_version: Widget version
            user_profile: User profile type
            session_uuid: Session UUID
            **params: Additional parameters
        """
        # Validate required parameters  
        if not institutions:
            raise ValueError(
                "Biblioteket widget requires 'institutions' parameter. "
                "This should be automatically provided from your profile, "
                "but no institution IDs were found."
            )
        if not children:
            raise ValueError(
                "Biblioteket widget requires 'children' parameter. "
                "This should be automatically provided from your profile, "
                "but no children were found."
            )
        # Build query parameters
        query_params = {
            "coverImageHeight": cover_image_height,
            "widgetVersion": widget_version,
            "userProfile": user_profile,
        }
        
        if institutions:
            for inst in institutions:
                query_params.setdefault("institutions", []).append(inst)
        
        if children:
            for child in children:
                query_params.setdefault("children", []).append(child)
        
        if session_uuid:
            query_params["sessionUUID"] = session_uuid
        
        # Add any additional parameters
        query_params.update(params)
        
        # Make request
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Authorization": f"Bearer {token}",
            "Origin": "https://www.aula.dk",
            "Referer": "https://www.aula.dk/",
        }
        
        # Debug: print the full URL being requested
        import logging
        _LOGGER = logging.getLogger(__name__)
        _LOGGER.info(f"Requesting URL: {self.base_url} with params: {query_params}")
        
        response = await client.get(
            self.base_url,
            params=query_params,
            headers=headers
        )
        
        # Debug: print response details if error
        if response.status_code != 200:
            _LOGGER.error(f"Request failed with status {response.status_code}: {response.text}")
        
        response.raise_for_status()
        
        data = response.json()
        
        # Parse loans
        loans = []
        for loan_data in data.get("loans", []):
            loans.append(LibraryLoan(
                title=loan_data["title"],
                author=loan_data["author"],
                cover_image_url=loan_data["coverImageUrl"],
                patron_display_name=loan_data["patronDisplayName"],
                id=loan_data["id"],
                due_date=loan_data["dueDate"],
                number_of_loans=loan_data["numberOfLoans"]
            ))
        
        # Parse longterm loans (same structure)
        longterm_loans = []
        for loan_data in data.get("longtermLoans", []):
            longterm_loans.append(LibraryLoan(
                title=loan_data["title"],
                author=loan_data["author"],
                cover_image_url=loan_data["coverImageUrl"],
                patron_display_name=loan_data["patronDisplayName"],
                id=loan_data["id"],
                due_date=loan_data["dueDate"],
                number_of_loans=loan_data["numberOfLoans"]
            ))
        
        return BibliotekData(
            widget_id=self.widget_id,
            raw_data=data,
            loans=loans,
            longterm_loans=longterm_loans,
            reservations=data.get("reservations", []),
            branch_ids=data.get("branchIds", [])
        )