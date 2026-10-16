import json
from pathlib import Path

class Queue:
    def __init__(self, path):
        self.path = Path(path)
        self.jobs = json.loads(self.path.read_text()) if self.path.exists() else {}

    def _save(self):
        self.path.write_text(json.dumps(self.jobs, sort_keys=True))

    def enqueue(self, key):
        if key in self.jobs:
            return False
        self.jobs[key] = {"state": "pending", "owner": None, "until": 0, "result": None}
        self._save()
        return True

    def claim(self, key, owner, now, lease=30):
        job = self.jobs[key]
        if job["state"] == "done" or (job["state"] == "leased" and now < job["until"]):
            return False
        job.update(state="leased", owner=owner, until=now + lease)
        self._save()
        return True

    def complete(self, key, owner, result):
        job = self.jobs[key]
        if job["state"] != "leased":
            return False
        job.update(state="done", result=result)
        self._save()
        return True
