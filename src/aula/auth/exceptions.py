"""Exception classes for MitID authentication."""


class AulaAuthenticationError(Exception):
    """Base exception for Aula authentication errors."""

    pass


class MitIDError(AulaAuthenticationError):
    """Exception raised for MitID-specific errors."""

    pass


class NetworkError(AulaAuthenticationError):
    """Exception raised for network-related errors."""

    pass


class SAMLError(AulaAuthenticationError):
    """Exception raised for SAML-related errors."""

    pass


class OAuthError(AulaAuthenticationError):
    """Exception raised for OAuth-related errors."""

    pass
