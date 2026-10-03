from tr_shared.contracts.availability import DatabaseOutageCode


class DatabaseUnavailableError(Exception):
    def __init__(self, message: str, *, code: DatabaseOutageCode) -> None:
        super().__init__(message)
        self.code = code


class DatabaseTimeoutError(Exception):
    pass


DATABASE_OUTAGE_ERRORS: tuple[type[Exception], ...] = (
    DatabaseUnavailableError,
    DatabaseTimeoutError,
)
