"""
Aula provider for Biblioteket (Library) data.
"""
from typing import Any, Optional

from ..base import Provider
from ..http import HTTPClientMixin


class BiblioteketProvider(Provider, HTTPClientMixin):
    """Provider for library data from Biblioteket."""

    provider_id = "biblioteket"
    name = "Biblioteket"
    description = "Provider for library data including loans and reservations"

    # Base URL for the Biblioteket API
    base_url = "https://surf.cicero-suite.com/portal-api/rest/aula/library/status/v3"

    def __init__(self, auth_token: str, **kwargs):
        """Initialize the Biblioteket provider.

        Args:
            auth_token: Aula authentication token
            **kwargs: Additional configuration
        """
        super().__init__(auth_token, **kwargs)
        HTTPClientMixin.__init__(self)

    async def fetch_data(
        self,
        institutions: Optional[list[str]] = None,
        children: Optional[list[str]] = None,
        **kwargs
    ) -> dict[str, Any]:
        """Fetch library data for the specified institutions and children.

        Args:
            institutions: List of institution IDs to filter by
            children: List of child IDs to filter by
            **kwargs: Additional parameters

        Returns:
            Dictionary containing library data with the following structure:
            {
                'loans': List[dict],  # List of active loans
                'reservations': List[dict],  # List of reservations
                'institutions': List[dict],  # List of institutions
                'children': List[dict]  # List of children
            }

        Raises:
            ValueError: If the response cannot be parsed as JSON
            Exception: For any other errors during the request
        """
        import logging
        from typing import Dict, Any, List, Optional as Opt
        
        logger = logging.getLogger(__name__)
        
        # Prepare request parameters
        params: Dict[str, Any] = {
            'institutions': institutions or [],
            'children': children or [],
            'widgetVersion': '1.6',
            'userProfile': 'guardian',
            **{k: v for k, v in kwargs.items() if v is not None}
        }
        
        # Filter out empty lists to avoid sending empty array parameters
        params = {k: v for k, v in params.items() if v != []}
        
        logger.debug("Fetching library data with params: %s", params)
        
        try:
            # Make the HTTP request using the HTTPClientMixin's get method
            # which will handle authentication, headers, and JSON parsing
            response_data = await self.get("", params=params)
            
            # Log the raw response for debugging
            logger.debug("Raw response data: %s", response_data)
            
            # Validate the response structure
            if not isinstance(response_data, dict):
                logger.error("Unexpected response format: %s", type(response_data))
                return {
                    'error': 'Invalid response format',
                    'details': f'Expected dict, got {type(response_data).__name__}'
                }
            
            # Check for error in response
            if 'error' in response_data:
                logger.error("Error in API response: %s", response_data.get('error'))
                return response_data
                
            # Ensure we have the expected structure
            result: Dict[str, Any] = {
                'loans': response_data.get('loans', []),
                'reservations': response_data.get('reservations', []),
                'institutions': response_data.get('institutions', []),
                'children': response_data.get('children', [])
            }
            
            # Log summary of data received
            logger.info(
                "Fetched library data: %d loans, %d reservations, %d institutions, %d children",
                len(result['loans']),
                len(result['reservations']),
                len(result['institutions']),
                len(result['children'])
            )
            
            return result
            
        except Exception as e:
            logger.error("Failed to fetch library data: %s", str(e), exc_info=True)
            return {
                'error': 'Failed to fetch library data',
                'details': str(e)
            }

    async def get_loans(
        self,
        institutions: Optional[list[str]] = None,
        children: Optional[list[str]] = None,
        **kwargs
    ) -> list[dict[str, Any]]:
        """Get current loans.

        Args:
            institutions: List of institution IDs to filter by
            children: List of child IDs to filter by
            **kwargs: Additional parameters

        Returns:
            List of loan items
        """
        data = await self.fetch_data(institutions=institutions, children=children, **kwargs)
        return data.get('loans', [])

    async def get_reservations(
        self,
        institutions: Optional[list[str]] = None,
        children: Optional[list[str]] = None,
        **kwargs
    ) -> list[dict[str, Any]]:
        """Get current reservations.

        Args:
            institutions: List of institution IDs to filter by
            children: List of child IDs to filter by
            **kwargs: Additional parameters

        Returns:
            List of reservation items
        """
        data = await self.fetch_data(institutions=institutions, children=children, **kwargs)
        return data.get('reservations', [])

    async def close(self):
        """Clean up resources."""
        await HTTPClientMixin.close(self)
