"""MitID authentication module for Aula."""

from .exceptions import (
    AulaAuthenticationError,
    MitIDError,
    TokenExpiredError,
    APIError,
    ConfigurationError,
    NetworkError,
    SAMLError,
    OAuthError,
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
