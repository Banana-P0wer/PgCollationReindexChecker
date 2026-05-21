class PgCollCheckError(Exception):
    pass


class UnsupportedPostgresError(PgCollCheckError):
    pass
