from __future__ import annotations


class PgCollCheckError(Exception):
    pass


class UnsupportedPostgresError(PgCollCheckError):
    pass


class DatabaseOperationError(PgCollCheckError):
    def __init__(
        self,
        database_name: str,
        command: str,
        error_type: str,
        message: str,
        sqlstate: str | None = None,
    ) -> None:
        self.database_name = database_name
        self.command = command
        self.error_type = error_type
        self.message = message
        self.sqlstate = sqlstate
        super().__init__(self.__str__())

    def __str__(self) -> str:
        sqlstate = f", SQLSTATE {self.sqlstate}" if self.sqlstate else ""
        return (
            f"{self.command} failed for database {self.database_name}: "
            f"{self.error_type}: {self.message}{sqlstate}"
        )
