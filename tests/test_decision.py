import unittest


class PlaceholderTest(unittest.TestCase):
    def test_project_imports(self) -> None:
        import pgcollcheck

        self.assertEqual(pgcollcheck.__version__, "0.1.0")


if __name__ == "__main__":
    unittest.main()
