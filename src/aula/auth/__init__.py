"""MitID authentication module for Aula."""

from .exceptions import (
    AulaAuthenticationError,
    MitIDError,
    NetworkError,
    OAuthError,
    SAMLError,
)
from .mitid_client import MitIDAuthClient

__all__ = [
    "MitIDAuthClient",
    "AulaAuthenticationError",
    "MitIDError",
    "NetworkError",
    "SAMLError",
    "OAuthError",
]
