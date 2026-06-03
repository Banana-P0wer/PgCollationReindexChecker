import json
import os
import subprocess
import sys
import unittest
from pathlib import Path


def integration_enabled() -> bool:
    return os.environ.get("PGCOLLCHECK_INTEGRATION") == "1"


@unittest.skipUnless(integration_enabled(), "set PGCOLLCHECK_INTEGRATION=1 to run PostgreSQL integration tests")
class PostgresIntegrationTest(unittest.TestCase):
    schema_name = f"pgcollcheck_itest_{os.getpid()}"

    @classmethod
    def setUpClass(cls) -> None:
        cls.database = os.environ.get("PGCOLLCHECK_TEST_DB") or os.environ.get("PGDATABASE")
        if not cls.database:
            raise unittest.SkipTest("set PGCOLLCHECK_TEST_DB or PGDATABASE for integration tests")
        try:
            import psycopg
        except ImportError as exc:
            raise unittest.SkipTest("psycopg is required for integration tests") from exc

        cls.psycopg = psycopg
        cls.conn = psycopg.connect(dbname=cls.database, autocommit=True)
        try:
            cls._setup_objects()
        except Exception as exc:
            cls._drop_schema()
            raise unittest.SkipTest(f"could not create integration objects: {exc}") from exc

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "conn"):
            cls._drop_schema()
            cls.conn.close()

    @classmethod
    def _setup_objects(cls) -> None:
        with cls.conn.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS "{cls.schema_name}" CASCADE')
            cur.execute(f'CREATE SCHEMA "{cls.schema_name}"')
            cur.execute(
                f"""
                CREATE COLLATION "{cls.schema_name}".und_icu_mismatch (
                    provider = icu,
                    locale = 'und',
                    version = '0'
                )
                """
            )
            cur.execute(
                f"""
                CREATE TABLE "{cls.schema_name}".sample_strings (
                    id integer PRIMARY KEY,
                    name text NOT NULL
                )
                """
            )
            cur.execute(
                f"""
                INSERT INTO "{cls.schema_name}".sample_strings (id, name)
                VALUES (1, 'Ёлка'), (2, 'Ель'), (3, 'ångström'), (4, 'apple')
                """
            )
            cur.execute(
                f"""
                CREATE INDEX sample_strings_name_icu_mismatch_idx
                ON "{cls.schema_name}".sample_strings
                (name COLLATE "{cls.schema_name}".und_icu_mismatch)
                """
            )

    @classmethod
    def _drop_schema(cls) -> None:
        with cls.conn.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS "{cls.schema_name}" CASCADE')

    def test_scan_provider_icu_reports_version_mismatch(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        command = [
            sys.executable,
            "-m",
            "pgcollcheck",
            "scan",
            "--database",
            self.database,
            "--schema",
            self.schema_name,
            "--provider",
            "icu",
            "--format",
            "json",
            "--strict-exit-code",
        ]

        completed = subprocess.run(
            command,
            cwd=project_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(completed.returncode, 2, completed.stderr)
        report = json.loads(completed.stdout)
        results = report["results"]
        self.assertEqual(report["command"], "scan")
        self.assertEqual(report["summary"]["reindex_count"], 1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["decision"], "REINDEX_RECOMMENDED_BY_COLLATION_VERSION")
        self.assertEqual(results[0]["index_name"], "sample_strings_name_icu_mismatch_idx")
        self.assertEqual(results[0]["dependencies"][0]["provider_name"], "icu")
        self.assertEqual(results[0]["dependencies"][0]["status"], "VERSION_MISMATCH")


if __name__ == "__main__":
    unittest.main()
