from .base import BenException


class AudioException(BenException):
    pass


class SoundNotFound(AudioException):
    pass


class AudioPlaybackFailed(AudioException):
    pass
