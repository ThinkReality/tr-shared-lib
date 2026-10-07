from tr_shared.contracts.availability import DatabaseOutageCode


class DatabaseUnavailableError(Exception):
    def __init__(self, message: str, code: DatabaseOutageCode) -> None:
        self.code = DatabaseOutageCode(code)
        super().__init__(message, self.code)

    def __str__(self) -> str:
        return str(self.args[0])


class DatabaseTimeoutError(Exception):
    pass


DATABASE_OUTAGE_ERRORS: tuple[type[Exception], ...] = (
    DatabaseUnavailableError,
    DatabaseTimeoutError,
)
