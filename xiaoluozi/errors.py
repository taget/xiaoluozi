class WorkbenchError(Exception):
    """Error the workbench can show. Nothing about the turn was invented."""


class ModelNotConfigured(WorkbenchError):
    """TYPESAFE_API_KEY is missing from .env. Do not call the model."""


class ModelError(WorkbenchError):
    """The model was called and did not return a usable completion."""


class ReplyError(WorkbenchError):
    """The turn has no reply. Do not retain it."""


class MemoryError(WorkbenchError):
    """The memory port could not retain this turn."""
