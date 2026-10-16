import tempfile
from pathlib import Path
import unittest
from queue_store import Queue

class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "jobs.json"
        self.q = Queue(self.path)
        self.q.enqueue("job")

    def test_success_persists_and_duplicate_enqueue_preserves_result(self):
        self.assertTrue(self.q.claim("job", "worker-A", 0))
        self.assertTrue(self.q.complete("job", "worker-A", "correct"))
        restarted = Queue(self.path)
        self.assertFalse(restarted.enqueue("job"))
        self.assertEqual(restarted.jobs["job"]["result"], "correct")

    def test_active_lease_and_boundary_reclaim(self):
        self.assertTrue(self.q.claim("job", "worker-A", 10, lease=30))
        self.assertFalse(self.q.claim("job", "worker-B", 39))
        self.assertTrue(self.q.claim("job", "worker-B", 40))

    def test_stale_completion_cannot_corrupt_reclaimed_job(self):
        self.q.claim("job", "worker-A", 0, lease=10)
        self.q.claim("job", "worker-B", 10, lease=10)
        before = self.path.read_text()
        self.assertFalse(self.q.complete("job", "worker-A", "stale"))
        self.assertEqual(self.path.read_text(), before)
        self.assertEqual(self.q.jobs["job"]["state"], "leased")
        self.assertTrue(self.q.complete("job", "worker-B", "fresh"))
        self.assertEqual(Queue(self.path).jobs["job"]["result"], "fresh")
