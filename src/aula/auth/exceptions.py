"""Exception classes for MitID authentication."""


class AulaAuthenticationError(Exception):
    """Base exception for Aula authentication errors."""
    pass


class MitIDError(AulaAuthenticationError):
    """Exception raised for MitID-specific errors."""
    pass


class TokenExpiredError(AulaAuthenticationError):
    """Exception raised when authentication token has expired."""
    pass


class APIError(AulaAuthenticationError):
    """Exception raised for API-related errors."""
    pass


class ConfigurationError(AulaAuthenticationError):
    """Exception raised for configuration errors."""
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
