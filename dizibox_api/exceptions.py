"""Custom exceptions for Dizibox API Client."""

class DiziboxAPIError(Exception):
    """Base exception for all Dizibox API errors."""
    pass

class CloudflareBlockedError(DiziboxAPIError):
    """Raised when request is challenged or blocked by Cloudflare."""
    pass

class NotFoundError(DiziboxAPIError):
    """Raised when requested resource (series, episode, video) is not found."""
    pass

class ParseError(DiziboxAPIError):
    """Raised when DOM or JS structure cannot be parsed."""
    pass

class DecryptionError(DiziboxAPIError):
    """Raised when embedded video player cipher fails to decrypt."""
    pass
