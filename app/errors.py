class DomainError(Exception):
    def __init__(self, code: str, message: str, field: str = "", status: int = 422):
        super().__init__(message)
        self.code = code
        self.field = field
        self.status = status

    def detail(self) -> dict:
        return {"code": self.code, "message": str(self), "field": self.field}
