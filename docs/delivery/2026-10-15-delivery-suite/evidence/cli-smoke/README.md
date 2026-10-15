# Real CLI smoke evidence

This isolated fixture actually executed every CLI command recorded in transcript.json. Synthetic authorization and reviewer identities are explicitly labeled and are not real approvals or independent reviews.

Result: passed. Normal init/configure/implementation/review/run/verification/close completed; check/status confirmed closure. A new record while closed was rejected. After explicit reopen and a fixture product change, implementation/review/verification became stale, close was rejected, and the original close event stayed identical.

Files: run_smoke.py retains the driver; engine-snapshot.py and SHA bind the tested executable; commands/ retains every stdout/stderr; fixture-project/ retains exact Markdown, JSON, product files and runtime objects. The fixture is intentionally left active with stale results to show invalidation. It is not a pending production task.

Do not rerun in place: the driver refuses to overwrite existing evidence. Copy to a fresh evidence directory and adjust the repository locator when replaying elsewhere.
