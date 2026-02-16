"""MitID authentication module for Aula."""

from .exceptions import (
    APIError,
    AulaAuthenticationError,
    ConfigurationError,
    MitIDError,
    NetworkError,
    OAuthError,
    SAMLError,
    TokenExpiredError,
)
from .mitid_client import MitIDAuthClient

__all__ = [
    "MitIDAuthClient",
    "AulaAuthenticationError",
    "MitIDError",
    "TokenExpiredError",
    "APIError",
    "ConfigurationError",
    "NetworkError",
    "SAMLError",
    "OAuthError",
]
