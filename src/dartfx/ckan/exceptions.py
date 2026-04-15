"""Custom exceptions for the CKAN toolkit."""


class CKANError(Exception):
    """Base exception for all CKAN toolkit errors."""


class CKANConnectionError(CKANError):
    """Raised when a connection to the CKAN server cannot be established."""


class CKANAPIRequestError(CKANError):
    """Raised when a CKAN Action API request fails."""


class CKANValidationError(CKANError):
    """Raised when CKAN API data fails model validation."""
