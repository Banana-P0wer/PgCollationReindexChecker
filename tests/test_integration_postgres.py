import json
import os
import subprocess
import sys
import unittest
from pathlib import Path


def integrationEnabled() -> bool:
    return os.environ.get("PGCOLLCHECK_INTEGRATION") == "1"


@unittest.skipUnless(integrationEnabled(), "set PGCOLLCHECK_INTEGRATION=1 to run PostgreSQL integration tests")
class PostgresIntegrationTest(unittest.TestCase):
    schemaName = f"pgcollcheck_itest_{os.getpid()}"

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
            cls._setupObjects()
        except Exception as exc:
            cls._dropSchema()
            raise unittest.SkipTest(f"could not create integration objects: {exc}") from exc

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "conn"):
            cls._dropSchema()
            cls.conn.close()

    @classmethod
    def _setupObjects(cls) -> None:
        with cls.conn.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS "{cls.schemaName}" CASCADE')
            cur.execute(f'CREATE SCHEMA "{cls.schemaName}"')
            cur.execute(
                f"""
                CREATE COLLATION "{cls.schemaName}".und_icu_mismatch (
                    provider = icu,
                    locale = 'und',
                    version = '0'
                )
                """
            )
            cur.execute(
                f"""
                CREATE TABLE "{cls.schemaName}".sample_strings (
                    id integer PRIMARY KEY,
                    name text NOT NULL,
                    nickname text NOT NULL
                )
                """
            )
            cur.execute(
                f"""
                INSERT INTO "{cls.schemaName}".sample_strings (id, name, nickname)
                VALUES
                    (1, 'Ёлка', 'elka'),
                    (2, 'Ель', 'yel'),
                    (3, 'ångström', 'angstrom'),
                    (4, 'apple', 'apple')
                """
            )
            cur.execute(
                f"""
                CREATE INDEX sample_strings_name_icu_mismatch_idx
                ON "{cls.schemaName}".sample_strings
                (name COLLATE "{cls.schemaName}".und_icu_mismatch)
                """
            )
            cur.execute(
                f"""
                CREATE INDEX sample_strings_id_partial_icu_mismatch_idx
                ON "{cls.schemaName}".sample_strings (id)
                WHERE name COLLATE "{cls.schemaName}".und_icu_mismatch > 'm'
                """
            )
            cur.execute(
                f"""
                CREATE INDEX sample_strings_nickname_default_idx
                ON "{cls.schemaName}".sample_strings (nickname)
                """
            )

    @classmethod
    def _dropSchema(cls) -> None:
        with cls.conn.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS "{cls.schemaName}" CASCADE')

    def testScanProviderIcuReportsKeyAndPartialVersionMismatches(self) -> None:
        projectRoot = Path(__file__).resolve().parents[1]
        command = [
            sys.executable,
            "-m",
            "pgcollcheck",
            "scan",
            "--database",
            self.database,
            "--schema",
            self.schemaName,
            "--provider",
            "icu",
            "--format",
            "json",
            "--strict-exit-code",
        ]

        completed = subprocess.run(
            command,
            cwd=projectRoot,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(completed.returncode, 2, completed.stderr)
        report = json.loads(completed.stdout)
        results = report["results"]
        self.assertEqual(report["command"], "scan")
        self.assertEqual(report["summary"]["reindex_count"], 2)
        self.assertEqual(len(results), 2)
        byName = {result["index_name"]: result for result in results}
        self.assertEqual(
            byName["sample_strings_name_icu_mismatch_idx"]["decision"],
            "REINDEX_RECOMMENDED_BY_COLLATION_VERSION",
        )
        self.assertEqual(
            byName["sample_strings_id_partial_icu_mismatch_idx"]["dependencies"][0]["dependency_source"],
            "pg_depend",
        )
        self.assertIn(
            "name COLLATE",
            byName["sample_strings_id_partial_icu_mismatch_idx"]["dependencies"][0]["key_expression"],
        )
        for result in results:
            self.assertEqual(result["dependencies"][0]["provider_name"], "icu")
            self.assertEqual(result["dependencies"][0]["status"], "VERSION_MISMATCH")

    def testScanReportsDefaultCollationIndex(self) -> None:
        projectRoot = Path(__file__).resolve().parents[1]
        command = [
            sys.executable,
            "-m",
            "pgcollcheck",
            "scan",
            "--database",
            self.database,
            "--schema",
            self.schemaName,
            "--format",
            "json",
        ]

        completed = subprocess.run(
            command,
            cwd=projectRoot,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        byName = {result["index_name"]: result for result in report["results"]}
        defaultIndex = byName["sample_strings_nickname_default_idx"]
        self.assertEqual(defaultIndex["decision"], "OK")
        self.assertEqual(defaultIndex["dependencies"][0]["collation_name"], "default")
        self.assertEqual(defaultIndex["dependencies"][0]["version_source"], "pg_database.datcollversion")


if __name__ == "__main__":
    unittest.main()
