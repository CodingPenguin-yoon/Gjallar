"""Safe, stable user-facing errors. Never include transport/secret exceptions."""


class ClientError(Exception):
    def __init__(self, code: str, message: str, exit_code: int = 7):
        super().__init__(message)
        self.code, self.message, self.exit_code = code, message, exit_code

    def output(self):
        return {"ok": False, "error": {"code": self.code, "message": self.message}}
