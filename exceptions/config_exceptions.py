from .base import BenException


class ConfigException(BenException):
    pass


class InvalidWeight(ConfigException):
    pass


class InvalidChance(ConfigException):
    pass
