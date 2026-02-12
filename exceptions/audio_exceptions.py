from .base import BenException


class AudioException(BenException):
    """Base exception for audio-related errors"""
    pass


class SoundNotFound(AudioException):
    """Raised when a sound file cannot be found"""
    pass


class AudioPlaybackFailed(AudioException):
    """Raised when audio playback fails"""
    pass