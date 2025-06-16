"""
Aula provider for MinUddanelse Opgaver (Assignments) data.
"""
from datetime import datetime
from typing import Any, Optional

from ..base import Provider
from ..http import HTTPClientMixin


class MinUddanelseProvider(Provider, HTTPClientMixin):
    """Provider for assignment data from MinUddanelse."""

    provider_id = "minuddannelse"
    name = "MinUddanelse Opgaver"
    description = "Provider for assignment and homework data from MinUddanelse"

    # Base URL for the MinUddanelse API
    base_url = "https://api.minuddannelse.net/aula"

    def __init__(self, auth_token: str, **kwargs):
        """Initialize the MinUddanelse provider.

        Args:
            auth_token: Aula authentication token
            **kwargs: Additional configuration
        """
        super().__init__(auth_token, **kwargs)
        HTTPClientMixin.__init__(self)

    async def fetch_assignments(
        self,
        child_filter: Optional[list[str]] = None,
        institution_filter: Optional[list[str]] = None,
        current_week_number: Optional[str] = None,
        placement: str = "narrow",
        **kwargs
    ) -> dict[str, Any]:
        """Fetch assignments for the specified children and institutions.

        Args:
            child_filter: List of child IDs to filter by
            institution_filter: List of institution IDs to filter by
            current_week_number: Week number in format 'YYYY-Www' (e.g., '2025-W24')
            placement: Placement type (e.g., 'narrow')
            **kwargs: Additional parameters

        Returns:
            Dictionary containing assignment data
        """
        if current_week_number is None:
            # Default to current week if not specified
            current_week_number = datetime.now().strftime("%Y-W%V")

        params = {
            'placement': placement,
            'currentWeekNumber': current_week_number,
            'userProfile': 'guardian',
            'isMobileApp': 'false',
            **kwargs
        }

        # Add list parameters if provided
        if child_filter:
            for i, child_id in enumerate(child_filter):
                params[f'childFilter[{i}]'] = child_id

        if institution_filter:
            for i, inst_id in enumerate(institution_filter):
                params[f'institutionFilter[{i}]'] = inst_id

        return await self.get("opgaveliste", params=params)

    async def get_assignments(
        self,
        child_filter: Optional[list[str]] = None,
        institution_filter: Optional[list[str]] = None,
        current_week_number: Optional[str] = None,
        **kwargs
    ) -> list[dict[str, Any]]:
        """Get assignments.

        Args:
            child_filter: List of child IDs to filter by
            institution_filter: List of institution IDs to filter by
            current_week_number: Week number in format 'YYYY-Www'
            **kwargs: Additional parameters

        Returns:
            List of assignment items
        """
        data = await self.fetch_assignments(
            child_filter=child_filter,
            institution_filter=institution_filter,
            current_week_number=current_week_number,
            **kwargs
        )
        return data.get('opgaver', [])

    async def fetch_data(self, **kwargs) -> dict[str, Any]:
        """Fetch assignment data (implements Provider interface).

        Args:
            **kwargs: Parameters to pass to fetch_assignments

        Returns:
            Dictionary containing assignment data
        """
        return await self.fetch_assignments(**kwargs)

    async def close(self):
        """Clean up resources."""
        await HTTPClientMixin.close(self)
