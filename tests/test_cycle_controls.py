"""Process-isolated entry point; see tests/README.md."""
from tests.process_harness import module_suite

def load_tests(loader, tests, pattern):
    return module_suite("tests.unit_cases.test_cycle_controls")

if __name__ == "__main__":
    import unittest
    unittest.main()
