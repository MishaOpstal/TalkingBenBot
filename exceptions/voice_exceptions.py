from .base import BenException


class VoiceException(BenException):
    """Base exception for voice-related errors"""
    pass


class VoiceJoinFailed(VoiceException):
    """Raised when joining a voice channel fails"""
    pass


class VoiceNotConnected(VoiceException):
    """Raised when attempting an operation that requires voice connection"""
    pass


class RecordingStartFailed(VoiceException):
    """Raised when starting audio recording fails"""
    pass