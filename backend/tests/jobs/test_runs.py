"""Tests for file-backed job run status resilience."""

import unittest
from unittest.mock import patch


class JobRunsTests(unittest.TestCase):
    def test_list_job_runs_fails_open_when_runs_root_is_unavailable(self):
        from app.jobs import runs as runs_module

        class UnavailableRunsRoot:
            def glob(self, pattern):
                raise OSError("NFS mount is unavailable")

        with patch.object(runs_module, "runs_root", return_value=UnavailableRunsRoot()):
            self.assertEqual([], runs_module.list_job_runs())


if __name__ == "__main__":
    unittest.main()
