class ProcessingError(Exception):
    """The uploaded file is unreadable or invalid. The message is safe to show to API clients."""


class UploadTooLarge(Exception):
    pass


class EmptyUpload(Exception):
    pass
