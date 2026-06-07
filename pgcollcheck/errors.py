from __future__ import annotations


class PgCollCheckError(Exception):
    pass


class UnsupportedPostgresError(PgCollCheckError):
    pass


class DatabaseOperationError(PgCollCheckError):
    def __init__(
        self,
        databaseName: str,
        command: str,
        errorType: str,
        message: str,
        sqlstate: str | None = None,
    ) -> None:
        self.databaseName = databaseName
        self.command = command
        self.errorType = errorType
        self.message = message
        self.sqlstate = sqlstate
        super().__init__(self.__str__())

    def __str__(self) -> str:
        sqlstate = f", SQLSTATE {self.sqlstate}" if self.sqlstate else ""
        return (
            f"{self.command} failed for database {self.databaseName}: "
            f"{self.errorType}: {self.message}{sqlstate}"
        )
