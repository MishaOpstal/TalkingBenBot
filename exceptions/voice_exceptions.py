from .base import BenException


class VoiceException(BenException):
    pass


class VoiceJoinFailed(VoiceException):
    pass


class VoiceNotConnected(VoiceException):
    pass


class RecordingStartFailed(VoiceException):
    pass
