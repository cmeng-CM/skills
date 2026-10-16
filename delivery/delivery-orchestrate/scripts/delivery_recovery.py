"""Persistent unknown-run recovery, diagnostic attempts and readable briefs."""
from pathlib import Path

from delivery import DeliveryError, canonical, digest, fail, shape, text


LOADED_SOURCE_BYTES = Path(__file__).read_bytes()

class RecoveryMixin:
    def resolutions(self):
        latest = {}
        for event in self.data["events"]:
            p = event["payload"]
            if event["kind"] in ("run-resolution", "run-investigation"):
                latest[p["run_operation"]] = event
        return latest

    def resolution_current(self, event, config):
        if event["kind"] == "run-investigation":
            return self.investigation_bound(event, config) and self.investigation_current(event, live=True)
        p = event["payload"]
        if p["decision"] != "safe_to_retry" or not self.references_current(p["references"]) or p["config_op"] != config["op"]:
            return False
        try:
            return self.snapshot(p["snapshot"]["scopes"])["hash"] == p["snapshot"]["hash"] and self.references_current(config["payload"]["sources"])
        except (DeliveryError, ValueError, OSError):
            return False

    def investigation_current(self, event, live=False):
        """Recovery contract 2: observed safety is separate from plan validity."""
        p = event["payload"]
        if event["kind"] != "run-investigation" or p.get("recovery_contract_version") != 2 or p["decision"] != "safe_to_replan":
            return False
        config = next(e for e in self.data["events"] if e["kind"] == "configure" and e["op"] == p["config_op"])
        if not self.references_current(p["references"]) or p["orchestrate_pin"] not in self.valid_pin_hashes(config, "delivery-orchestrate"):
            return False
        if not live:
            return True
        try:
            inventory = self.inventory(config["payload"])
            return (not inventory["unsupported"] and inventory["hash"] == p["inventory_hash"]
                    and self.snapshot(p["snapshot"]["scopes"])["hash"] == p["snapshot"]["hash"])
        except (DeliveryError, ValueError, OSError):
            return False

    @staticmethod
    def investigation_bound(event, config):
        return any(t["run_operation"] == event["payload"]["run_operation"] and t["investigation_operation"] == event["op"]
                   for t in config["payload"].get("recovery_transfers", []))

    def validate_recovery_transfers(self, values, old, payload):
        if not isinstance(values, list):
            fail("recovery_transfers must be an array")
        unknowns = {u["operation"]: u for u in self.unknown_runs(old)}
        latest = self.resolutions()
        transfers = {}
        for value in values:
            shape(value, ("run_operation", "investigation_operation", "recovery_contract_version"), name="recovery transfer")
            if type(value["recovery_contract_version"]) is not int or value["recovery_contract_version"] != 2:
                fail("recovery transfer requires explicit recovery contract 2")
            operation = value["run_operation"]
            unknown, investigation = unknowns.get(operation), latest.get(operation)
            if operation in transfers or not unknown or unknown["settled"]:
                fail("transfer must name each real unsettled run at most once")
            if (not investigation or investigation["op"] != value["investigation_operation"]
                    or investigation["payload"]["config_op"] != old["op"]
                    or not self.investigation_current(investigation, live=True)):
                fail("transfer requires latest current safe_to_replan investigation in previous admission")
            owner = self.target(payload, "verification", unknown["acceptance"])
            previous = self.target(old["payload"], "verification", unknown["acceptance"])
            if (owner["method"] != "command" or not set(unknown["tasks"]) <= set(owner["tasks"])
                    or (previous["required"] and not owner["required"])
                    or (not previous.get("waivable", False) and owner.get("waivable", False))):
                fail("transfer must preserve command owner, task coverage and final acceptance threshold")
            transfers[operation] = dict(value)
        return transfers

    @staticmethod
    def recovery_operations(payload):
        operations = payload.get("recovery_operations")
        if operations is None:
            operation = payload.get("recovery_operation")
            return [operation] if operation else []
        return operations

    def valid_run_recoveries(self, run, config, live=True):
        operations = self.recovery_operations(run["payload"])
        if len(operations) != len(set(operations)):
            return False
        for operation in operations:
            resolution = next((e for e in self.data["events"] if e["kind"] in ("run-resolution", "run-investigation") and e["op"] == operation), None)
            origin = next((e for e in self.data["events"] if resolution and e["kind"] == "run-started" and e["op"] == resolution["payload"]["run_operation"]), None)
            if not origin or origin["payload"]["acceptance"] != run["payload"]["acceptance"]:
                return False
            if resolution["kind"] == "run-investigation":
                if not self.investigation_bound(resolution, config) or not self.investigation_current(resolution, live=live):
                    return False
                continue
            if resolution["payload"]["config_op"] != run["payload"]["config_op"]:
                return False
            if live:
                if not self.resolution_current(resolution, config):
                    return False
            elif resolution["payload"]["decision"] != "safe_to_retry" or not self.references_current(resolution["payload"]["references"]):
                return False
        return True

    def settled_recovery(self, resolution, replacement, binding):
        """Validate the admitted historical chain without treating later
        legitimate product/config changes as new uncertainty about an old run.
        Its actual reports/evidence must remain intact; objects are checked on
        journal load. Current delivery still needs its own current verdicts.
        """
        if not resolution or not replacement or resolution["payload"]["decision"] not in ("safe_to_retry", "safe_to_replan") or not self.references_current(resolution["payload"]["references"]):
            return False
        origin = next((e for e in self.data["events"] if e["kind"] == "run-started" and e["op"] == resolution["payload"]["run_operation"]), None)
        run = replacement["payload"]
        if not origin or run["acceptance"] != origin["payload"]["acceptance"] or resolution["op"] not in self.recovery_operations(run) or not self.valid_run_recoveries(replacement, binding, live=False):
            return False
        if run["config_op"] != binding["op"] or run["exit_code"] != 0 or run["timed_out"] or not run["sources_stable"] or run["before"]["hash"] != run["after"]["hash"]:
            return False
        pair = self.records(binding).get(("verification", run["acceptance"]))
        if pair and "skill_pin" in pair[1]:
            pin = pair[1]["skill_pin"]
            if pin["tree_hash"] not in self.valid_pin_hashes(binding, pin["name"]) or pair[1]["orchestrate_pin"] not in self.valid_pin_hashes(binding, "delivery-orchestrate"):
                return False
        return bool(pair and pair[1]["result"] == "passed" and pair[1].get("run_operation") == replacement["op"]
                    and pair[1]["snapshot"]["hash"] == run["after"]["hash"]
                    and self.references_current(pair[1]["references"]))

    def unknown_runs(self, config):
        starts = {e["op"]: e for e in self.data["events"] if e["kind"] == "run-started"}
        completed = {e["op"] for e in self.data["events"] if e["kind"] == "run"}
        configs = {e["op"]: e for e in self.data["events"] if e["kind"] == "configure"}
        resolutions = self.resolutions()
        result = []
        for op, start in starts.items():
            if op in completed:
                continue
            resolution = resolutions.get(op)
            binding = configs.get(resolution["payload"]["config_op"]) if resolution else None
            replacement = None
            if resolution:
                replacement = next((e for e in reversed(self.data["events"]) if e["kind"] == "run" and resolution["op"] in self.recovery_operations(e["payload"])
                                    and e["payload"]["acceptance"] == start["payload"]["acceptance"]
                                    and (e["payload"]["config_op"] == resolution["payload"]["config_op"]
                                         or (resolution["kind"] == "run-investigation" and self.investigation_bound(resolution, configs[e["payload"]["config_op"]])))), None)
                if replacement:
                    binding = configs[replacement["payload"]["config_op"]]
            settled = bool(binding and self.settled_recovery(resolution, replacement, binding))
            historical = bool(binding and binding["op"] != config["op"])
            valid = bool(binding and (settled if historical else self.resolution_current(resolution, binding)))
            if resolution and resolution["kind"] == "run-investigation" and not (historical and settled):
                valid = self.resolution_current(resolution, config)
            result.append({"operation": op, "acceptance": start["payload"]["acceptance"],
                           "tasks": start["payload"].get("tasks", []), "config_op": start["payload"]["config_op"],
                           "recovery_config_op": binding["op"] if binding else None,
                           "investigation": resolution["op"] if resolution and resolution["kind"] == "run-investigation" else None,
                           "resolution": resolution["op"] if valid else None,
                           "replacement": replacement["op"] if valid and replacement else None,
                           "settled": settled})
        return result

    def resolve_run(self, request, op):
        if "recovery_contract_version" in request:
            return self.investigate_run(request, op)
        self.validate_extra(request, ("run_operation", "report", "evidence", "decision", "reason"))
        if request["decision"] not in ("safe_to_retry", "unresolved"):
            fail("invalid run resolution decision")
        text(request["reason"], "reason")
        with self.locked():
            key, prior = self.duplicate(op, {"kind": "run-resolution", "input": request})
            if prior:
                return prior
            self.active()
            config = self.current_config()
            start = next((e for e in self.data["events"] if e["op"] == request["run_operation"] and e["kind"] == "run-started"), None)
            if not start or any(e["kind"] == "run" and e["op"] == start["op"] for e in self.data["events"]):
                fail("resolution requires a real incomplete run-started")
            if start["payload"]["config_op"] != config["op"]:
                # A historical recovery proof may itself become stale. Permit
                # new evidenced investigation under the current admission;
                # preserve its stable acceptance owner so a replacement exists.
                self.target(config["payload"], "verification", start["payload"]["acceptance"])
            snapshot = self.snapshot(start["payload"]["before"]["scopes"])
            return self.append("run-resolution", op, key, {**request, "config_op": config["op"],
                                "references": self.report_references(request), "snapshot": snapshot,
                                "inventory_hash": self.inventory(config["payload"])["hash"]})

    def investigate_run(self, request, op):
        self.validate_extra(request, ("run_operation", "report", "evidence", "decision", "reason", "recovery_contract_version"))
        if type(request["recovery_contract_version"]) is not int or request["recovery_contract_version"] != 2:
            fail("unsupported recovery contract")
        if request["decision"] not in ("safe_to_replan", "unresolved"):
            fail("recovery contract 2 requires safe_to_replan or unresolved")
        text(request["reason"], "reason")
        with self.locked():
            key, prior = self.duplicate(op, {"kind": "run-investigation", "input": request})
            if prior:
                return prior
            self.active()
            config = self.current_config(False)
            if any(d["name"] == "delivery-orchestrate" for d in self.source_drift(config)):
                fail("accept actual orchestrate source before recovery investigation")
            start = next((e for e in self.data["events"] if e["op"] == request["run_operation"] and e["kind"] == "run-started"), None)
            if not start or any(e["kind"] == "run" and e["op"] == start["op"] for e in self.data["events"]):
                fail("investigation requires a real incomplete run-started")
            self.target(config["payload"], "verification", start["payload"]["acceptance"])
            inventory = self.inventory(config["payload"])
            if inventory["unsupported"] and request["decision"] == "safe_to_replan":
                fail("unsupported scene entries prevent safe investigation")
            return self.append("run-investigation", op, key, {**request, "config_op": config["op"],
                "origin_config_op": start["payload"]["config_op"], "references": self.report_references(request),
                "snapshot": self.snapshot(start["payload"]["before"]["scopes"]), "inventory_hash": inventory["hash"],
                "orchestrate_pin": self.effective_pins(config)["delivery-orchestrate"]["tree_hash"]})

    def recovery_for(self, config, kind, target, closing=False, all_operations=False):
        candidates = self.unknown_runs(config)
        item = None if closing else self.target(config["payload"], kind, target)
        tasks = set() if closing else ({target} if kind == "implementation" else set(item["tasks"]))
        recovery = []
        for unknown in candidates:
            relevant = closing or target == unknown["acceptance"] or bool(tasks & set(unknown["tasks"]))
            if not relevant:
                continue
            if unknown["settled"] and unknown["recovery_config_op"] != config["op"]:
                continue
            if not unknown["resolution"]:
                fail("incomplete run requires evidenced resolve-run; releasing resources is insufficient")
            if closing:
                records = self.records(config)
                pair = records.get(("verification", unknown["acceptance"]))
                if not pair or pair[1]["result"] != "passed" or pair[1].get("run_operation") != unknown["replacement"]:
                    fail("close requires completed replacement run and passed new verdict")
            if kind == "verification" and target == unknown["acceptance"]:
                recovery.append(unknown["resolution"])
        return recovery if all_operations else (recovery[-1] if recovery else None)

    def attempt(self, request, op):
        self.validate_extra(request, ("config_operation", "target", "failure_key", "facts", "strategy", "outcome", "report"))
        if request["outcome"] not in ("failed", "changed", "unknown"):
            fail("invalid attempt outcome")
        for key in ("failure_key", "strategy"):
            text(request[key], key)
        if not isinstance(request["facts"], list) or not request["facts"]:
            fail("attempt requires nonempty factual evidence")
        with self.locked():
            key, prior = self.duplicate(op, {"kind": "attempt", "input": request})
            if prior:
                return prior
            self.active()
            config = self.match_config(request)
            self.validate_targets([request["target"]], config)
            references = {"report": self.reference(request["report"]), "facts": [self.reference(f) for f in request["facts"]]}
            return self.append("attempt", op, key, {**request, "config_op": config["op"], "references": references})

    def diagnosis_state(self, config):
        # A new admission is not new diagnostic evidence. Follow stable targets
        # and the same known bug across task handoffs without rewriting history.
        targets = {}
        for kind, group in (("implementation", "tasks"), ("review", "reviews"), ("verification", "acceptance")):
            for item in config["payload"]["spec"][group]:
                targets[(kind, item["id"])] = (self.implementation_tasks([item["id"]])
                                                if kind == "implementation" else {item["id"]})
        groups = {}
        for event in self.data["events"]:
            p = event["payload"]
            if event["kind"] == "attempt":
                for (kind, target), aliases in targets.items():
                    if p["target"]["kind"] == kind and p["target"]["id"] in aliases:
                        groups.setdefault((kind, target, p["failure_key"]), []).append(p)
        blocked = []
        for key, values in groups.items():
            fingerprint, failures, pending = None, 0, False
            for value in values:
                observed = (sorted({v["object_hash"] for v in value["references"]["facts"]}), value["strategy"].strip())
                changed = observed != fingerprint
                if pending and (not changed or not self.references_current(value["references"])):
                    continue
                if changed:
                    # A stale non-failure cannot erase a prior failure streak.
                    if value["outcome"] != "failed" and not self.references_current(value["references"]):
                        continue
                    fingerprint, failures, pending = observed, 0, False
                if value["outcome"] == "failed":
                    failures += 1
                    pending = failures >= 2
            if pending:
                blocked.append({"kind": key[0], "id": key[1], "failure_key": key[2]})
        return blocked

    def brief(self, kind, target):
        with self.locked():
            config = self.current_config(False)
            state = self.state()
            item = self.target(config["payload"], kind, target)
            tasks = [target] if kind == "implementation" else item["tasks"]
            authors = self.implementation_authors(tasks)
            result = {"kind": kind, "target": target, "definition": item, "tasks": tasks,
                    "requirements": [r for r in config["payload"]["requirements"] if set(r["tasks"]) & set(tasks)],
                    "required_sources": config["payload"]["sources"],
                    "skill_pins": {name: {k: value for k, value in pin.items() if k != "files"} for name, pin in self.effective_pins(config).items()}, "excluded_implementation_authors": authors,
                    "writable_scope": self.target_scope(config["payload"], kind, target) if kind == "implementation" else [],
                    "resources": self.required_resources(config, kind, target),
                    "report_location": {"implementation": "implementation/", "review": "review/", "verification": "verification/"}[kind],
                    "state": state, "note": "Read full referenced requirements and constraints; this derived brief is not a second task authority."}
            if self.fix_enabled():
                result["skill"] = self.activity_skill(config, kind, target)
                if kind == "implementation":
                    result["implementation_route"] = self.implementation_route(config, target)
                    if result["skill"] == "delivery-fix":
                        result["report_location"] = result["implementation_route"]["bug_path"] + "/NNN/fix.md"
            return result
