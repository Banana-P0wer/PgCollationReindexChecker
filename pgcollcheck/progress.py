from __future__ import annotations

import sys


class ProgressReporter:
    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled

    def write(self, message: str) -> None:
        if self.enabled:
            print(f"pgcollcheck: {message}", file=sys.stderr)

    def database(self, action: str, database: str) -> None:
        self.write(f"{action} database {database}")
