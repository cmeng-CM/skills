"""Read existing Queue behavior; all generated data stays beside this probe.

Purpose: distinguish missing completion-owner validation from persistence or
lease-boundary errors. These are diagnostic observations, not acceptance tests.
Run with: python3 -B <this-file> <project-root>
"""
import copy
import json
from pathlib import Path
import sys

sys.path.insert(0, sys.argv[1])
from queue_store import Queue

data_dir = Path(__file__).parent / "probe-data"
data_dir.mkdir(exist_ok=False)
observations = []

def snapshot(q):
    return {"memory": copy.deepcopy(q.jobs), "disk": q.path.read_text()}

def queue(name):
    q = Queue(data_dir / (name + ".json"))
    q.enqueue("job")
    return q

for lease in (10, 1000000):
    q = queue("reclaimed-" + str(lease))
    claims = [q.claim("job", "A", 0, lease=lease),
              q.claim("job", "B", lease, lease=lease)]
    before = snapshot(q)
    stale_return = q.complete("job", "A", "stale")
    after = snapshot(q)
    fresh_return = q.complete("job", "B", "fresh")
    observations.append({"case": "reclaimed", "lease": lease,
        "claims": claims, "before_stale": before,
        "stale_return": stale_return, "after_stale": after,
        "memory_changed": before["memory"] != after["memory"],
        "disk_changed": before["disk"] != after["disk"],
        "fresh_return": fresh_return, "restarted": Queue(q.path).jobs})

q = queue("wrong-owner-active")
q.claim("job", "A", 10)
before = snapshot(q)
wrong_return = q.complete("job", "unrelated", "wrong")
observations.append({"case": "wrong-owner-active", "before": before,
    "return": wrong_return, "after": snapshot(q)})

q = queue("pending")
before = snapshot(q)
pending_return = q.complete("job", "A", "premature")
observations.append({"case": "pending", "return": pending_return,
    "unchanged": before == snapshot(q)})

q = queue("valid-completion")
q.claim("job", "A", 10)
before_duplicate = snapshot(q)
leased_duplicate = q.enqueue("job")
leased_unchanged = before_duplicate == snapshot(q)
correct_return = q.complete("job", "A", "correct")
completed = snapshot(q)
done_duplicate = q.enqueue("job")
done_unchanged = completed == snapshot(q)
observations.append({"case": "valid-completion", "leased_duplicate": leased_duplicate,
    "leased_duplicate_unchanged": leased_unchanged,
    "correct_return": correct_return, "done_duplicate": done_duplicate,
    "done_duplicate_unchanged": done_unchanged,
    "restarted": Queue(q.path).jobs})

print(json.dumps(observations, indent=2))
