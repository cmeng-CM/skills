# Queue result corruption repair plan

Requirement Q1: restore all README public behavior for durable leased jobs; preserve the public API and existing tests. T1 investigates and repairs queue_store.py; necessary new regression tests are allowed. Initial implementation may transfer to delivery-fix when the failure needs deeper diagnosis.

Scope: queue_store.py and tests. Authorization: local implementation, selfchecks and .delivery records; no README weakening, commits or push. Bug BUG-001 uses fixes/BUG-001-stale-result/ and all numbered round evidence stays there.

R1 is an independent whole-delivery spec and quality review of T1. A1 is required, non-waivable command verification: python3 -B -m unittest discover -s tests -v, with the verifier judging actual behavior and collected tests. Mapping and route changes are independently reviewed. Selfcheck, review, verification and close remain separate.

Route update transfers T1 to delivery-fix without changing requirements, product scope, R1 or A1. Diagnose-only handoff is allowed but cannot count as implementation passed. All actual authors and prior reports carry forward. No unknown process may be replayed.
