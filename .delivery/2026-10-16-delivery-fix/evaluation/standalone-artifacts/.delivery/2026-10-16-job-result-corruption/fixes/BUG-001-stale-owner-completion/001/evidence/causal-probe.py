import copy
import json
from pathlib import Path
import tempfile
from queue_store import Queue

with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / "jobs.json"
    q = Queue(path)
    q.enqueue("job")
    q.claim("job", "worker-A", 0, lease=10)
    q.claim("job", "worker-B", 10, lease=10)
    before = {"memory": copy.deepcopy(q.jobs), "durable": path.read_text()}
    stale_return = q.complete("job", "worker-A", "stale")
    after_stale = {"memory": copy.deepcopy(q.jobs), "durable": path.read_text()}
    current_return = q.complete("job", "worker-B", "fresh")
    print(json.dumps({"before": before, "stale_return": stale_return, "after_stale": after_stale, "current_return": current_return, "restart": Queue(path).jobs}, indent=2))
