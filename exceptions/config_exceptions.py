from .base import BenException


class ConfigException(BenException):
    """Base exception for configuration-related errors"""
    pass


class InvalidWeight(ConfigException):
    """Raised when an invalid weight value is provided"""
    pass


class InvalidChance(ConfigException):
    """Raised when an invalid chance value is provided"""
    pass