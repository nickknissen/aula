"""Exception classes for MitID authentication."""


class MitIDAuthError(Exception):
    """Base exception for MitID authentication errors."""

    pass


class MitIDError(MitIDAuthError):
    """Exception raised for MitID-specific errors."""

    pass


class NetworkError(MitIDAuthError):
    """Exception raised for network-related errors."""

    pass


class SAMLError(MitIDAuthError):
    """Exception raised for SAML-related errors."""

    pass


class OAuthError(MitIDAuthError):
    """Exception raised for OAuth-related errors."""

    pass


class TokenInvalidError(MitIDError):
    """Exception raised when a TOTP code from the hardware token is rejected."""

    pass


class PasswordInvalidError(MitIDError):
    """Exception raised when the MitID password is rejected."""

    pass
