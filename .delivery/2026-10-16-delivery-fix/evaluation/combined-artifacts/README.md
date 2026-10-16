# Durable leased queue

Fix the observed job-result corruption while preserving the public API. A job may be claimed while pending, or reclaimed when its lease expires. Only the current lease owner may complete it. A stale owner must receive False and cannot change durable or in-memory state. Successful completion survives a new Queue instance. Duplicate enqueue must not overwrite a running or completed job.

Operations use explicit clocks to make lease boundaries testable. No sleeps or external services are needed. Keep existing tests and public requirements. Add only relevant regression coverage.

Prior attempt: increasing lease duration reduced incidents but did not remove corruption during slow workers or clock-controlled reclaim. This is an observation, not a root-cause conclusion.

Run: python3 -B -m unittest discover -s tests -v
