class BenException(Exception):
    """Base exception for all Ben-related errors"""
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message