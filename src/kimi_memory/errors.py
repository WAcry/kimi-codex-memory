"""Public errors contain safe operational context, never HTTP bodies or secrets."""


class MemoryErrorBase(Exception):
    code = "memory_error"


class ConfigurationError(MemoryErrorBase):
    code = "configuration_error"


class CompatibilityError(MemoryErrorBase):
    code = "incompatible_kimi"


class IncompleteHistoryError(MemoryErrorBase):
    code = "incomplete_history"


class TransportError(MemoryErrorBase):
    code = "transport_error"
    status: int | None = None
    api_code: int | None = None
    unavailable = False


class MissingSessionError(TransportError):
    code = "session_unavailable"


class ModelError(MemoryErrorBase):
    code = "model_error"


class ExtractionOutputError(ModelError):
    code = "invalid_extraction_output"


class LeaseLostError(MemoryErrorBase):
    code = "lease_lost"


class BusyError(MemoryErrorBase):
    code = "busy"


class UnsafePathError(MemoryErrorBase):
    code = "unsafe_path"


class ResyncRequired(MemoryErrorBase):
    code = "pending_citations"
