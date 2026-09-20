class DomainError(Exception):
    def __init__(self, code: str, message: str, field: str = "", status: int = 422, *, details=None):
        super().__init__(message)
        self.code = code
        self.field = field
        self.status = status
        self.details = details or {}

    def detail(self) -> dict:
        result = {"code": self.code, "message": str(self), "field": self.field}
        if self.details:
            result["details"] = self.details
        return result
