"""MinUddannelse Opgaver (Assignments) widget implementation."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional
import httpx

from .base import BaseWidget, WidgetData


@dataclass
class Hold:
    """Represents a class/hold."""
    id: int
    navn: str
    fag_id: int
    fag_navn: str


@dataclass
class Forloeb:
    """Represents a course/forløb."""
    navn: str
    ikon: str
    id: str
    aarsplan_id: str
    farve: Optional[str]
    url: Optional[str]
    hold: List[Hold]


@dataclass
class Opgave:
    """Represents an assignment/opgave."""
    id: str
    opgave_type: str
    title: str
    afleveringsdato: str  # Raw date string from API
    ugedag: str
    ugenummer: int
    er_faerdig: bool
    url: str
    hold: List[Hold]
    forloeb: Optional[Forloeb]
    unilogin: str
    kuvertnavn: str
    antal_elever: Optional[int]
    antal_faerdige: Optional[int]
    placering: str
    placering_tidspunkt: Optional[str]


@dataclass
class MinUddannelseOpgaverData(WidgetData):
    """MinUddannelse Opgaver widget data."""
    opgaver: List[Opgave]


class MinUddannelseOpgaverWidget(BaseWidget):
    """Widget for assignments from MinUddannelse system."""
    
    @property
    def widget_id(self) -> str:
        return "0030"
    
    @property
    def name(self) -> str:
        return "MinUddannelse Opgaver"
    
    @property
    def base_url(self) -> str:
        return "https://api.minuddannelse.net/aula/opgaveliste"
    
    async def fetch_data(
        self, 
        client: httpx.AsyncClient, 
        token: str, 
        placement: str = "narrow",
        session_uuid: Optional[str] = None,
        user_profile: str = "guardian",
        current_week_number: Optional[str] = None,
        child_filter: Optional[List[str]] = None,
        is_mobile_app: bool = False,
        institution_filter: Optional[List[str]] = None,
        **params: Any
    ) -> MinUddannelseOpgaverData:
        """
        Fetch assignments data.
        
        Args:
            client: HTTP client
            token: Authentication token
            placement: Placement type (e.g., "narrow")
            session_uuid: Session UUID
            user_profile: User profile type
            current_week_number: Current week number (e.g., "2025-W24")
            child_filter: List of child IDs to filter (defaults to profile children)
            is_mobile_app: Whether request is from mobile app
            institution_filter: List of institution IDs to filter (defaults to profile institutions)
            **params: Additional parameters
        """
        # Build query parameters
        query_params = {
            "placement": placement,
            "userProfile": user_profile,
            "isMobileApp": str(is_mobile_app).lower(),
        }
        
        if session_uuid:
            query_params["sessionUUID"] = session_uuid
        
        if current_week_number:
            query_params["currentWeekNumber"] = current_week_number
        
        if child_filter:
            for child in child_filter:
                query_params.setdefault("childFilter[]", []).append(child)
        
        if institution_filter:
            for inst in institution_filter:
                query_params.setdefault("institutionFilter[]", []).append(inst)
        
        # Add any additional parameters
        query_params.update(params)
        
        # Make request
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {token}",
            "Origin": "https://www.aula.dk",
            "Referer": "https://www.aula.dk/",
        }
        
        response = await client.get(
            self.base_url,
            params=query_params,
            headers=headers
        )
        response.raise_for_status()
        
        data = response.json()
        
        # Parse opgaver
        opgaver = []
        for opgave_data in data.get("opgaver", []):
            # Parse hold
            hold_list = []
            for hold_data in opgave_data.get("hold", []):
                hold_list.append(Hold(
                    id=hold_data["id"],
                    navn=hold_data["navn"],
                    fag_id=hold_data["fagId"],
                    fag_navn=hold_data["fagNavn"]
                ))
            
            # Parse forloeb if present
            forloeb = None
            if opgave_data.get("forloeb"):
                forloeb_data = opgave_data["forloeb"]
                forloeb = Forloeb(
                    navn=forloeb_data["navn"],
                    ikon=forloeb_data["ikon"],
                    id=forloeb_data["id"],
                    aarsplan_id=forloeb_data["aarsplanId"],
                    farve=forloeb_data.get("farve"),
                    url=forloeb_data.get("url"),
                    hold=[]  # Assuming empty for now
                )
            
            opgaver.append(Opgave(
                id=opgave_data["id"],
                opgave_type=opgave_data["opgaveType"],
                title=opgave_data["title"],
                afleveringsdato=opgave_data["afleveringsdato"],
                ugedag=opgave_data["ugedag"],
                ugenummer=opgave_data["ugenummer"],
                er_faerdig=opgave_data["erFaerdig"],
                url=opgave_data["url"],
                hold=hold_list,
                forloeb=forloeb,
                unilogin=opgave_data["unilogin"],
                kuvertnavn=opgave_data["kuvertnavn"],
                antal_elever=opgave_data.get("antalElever"),
                antal_faerdige=opgave_data.get("antalFaerdige"),
                placering=opgave_data["placering"],
                placering_tidspunkt=opgave_data.get("placeringTidspunkt")
            ))
        
        return MinUddannelseOpgaverData(
            widget_id=self.widget_id,
            raw_data=data,
            opgaver=opgaver
        )