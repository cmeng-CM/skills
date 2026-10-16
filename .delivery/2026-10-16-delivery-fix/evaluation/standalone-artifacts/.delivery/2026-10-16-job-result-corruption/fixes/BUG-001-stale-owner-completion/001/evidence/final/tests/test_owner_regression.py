import copy
from pathlib import Path
import tempfile
import unittest

from queue_store import Queue


class OwnerRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "jobs.json"
        self.q = Queue(self.path)
        self.q.enqueue("job")

    def snapshot(self):
        return copy.deepcopy(self.q.jobs), self.path.read_bytes()

    def test_non_owner_cannot_complete_active_lease(self):
        self.q.claim("job", "worker-A", 0)
        before = self.snapshot()
        self.assertFalse(self.q.complete("job", "worker-B", "wrong"))
        self.assertEqual(self.snapshot(), before)
        self.assertTrue(self.q.complete("job", "worker-A", "correct"))
        self.assertEqual(Queue(self.path).jobs["job"]["result"], "correct")

    def test_repeated_reclaim_rejects_every_previous_owner_without_mutation(self):
        self.q.claim("job", "worker-A", 0, lease=5)
        self.q.claim("job", "worker-B", 5, lease=5)
        self.q.claim("job", "worker-C", 10, lease=5)
        before = self.snapshot()
        for owner in ("worker-A", "worker-B"):
            with self.subTest(owner=owner):
                self.assertFalse(self.q.complete("job", owner, "stale"))
                self.assertEqual(self.snapshot(), before)
        self.assertTrue(self.q.complete("job", "worker-C", "fresh"))
        self.assertEqual(Queue(self.path).jobs["job"]["result"], "fresh")

    def test_duplicate_enqueue_preserves_running_job(self):
        self.q.claim("job", "worker-A", 0, lease=15)
        before = self.snapshot()
        self.assertFalse(self.q.enqueue("job"))
        self.assertEqual(self.snapshot(), before)

    def test_pending_and_done_completion_are_rejected_without_mutation(self):
        before = self.snapshot()
        self.assertFalse(self.q.complete("job", None, "premature"))
        self.assertEqual(self.snapshot(), before)
        self.q.claim("job", "worker-A", 0)
        self.q.complete("job", "worker-A", "correct")
        before = self.snapshot()
        for owner in ("worker-A", "worker-B"):
            with self.subTest(owner=owner):
                self.assertFalse(self.q.complete("job", owner, "replacement"))
                self.assertEqual(self.snapshot(), before)
        self.assertEqual(Queue(self.path).jobs["job"]["result"], "correct")
