"""Explicit v2 admission; reuses the unchanged v1 evidence and graph checks."""
from contextlib import contextmanager
from pathlib import Path
import math
import os
import signal
import subprocess

from delivery import Engine, DeliveryError, actor, canonical, digest, fail, safe_path, shape, strings, text
from delivery_sources import SourcesMixin
from delivery_monitor import MonitorMixin
from delivery_recovery import RecoveryMixin

KINDS = {"implementation": "implement", "review": "review", "verification": "verify"}
GATES = {"plan_review", "design_review", "mapping_review", "change_review"}
CONFIG_EXTRA = ("source_authors", "requirements", "admission_policy", "change", "monitor", "skill_sources")
CONFIG_OPTIONAL = ("resources", "transition", "recovery_transfers")
CONFIG_CORE = ("actor", "plan", "authorization", "mapping_reason", "tasks", "reviews", "acceptance")
RECORD_CORE = ("kind", "target", "actor", "report", "result", "summary", "evidence")
RECORD_OPTIONAL = ("issues", "resolutions", "run_operation", "confirmation", "supersedes", "reason")


LOADED_SOURCE_BYTES = Path(__file__).read_bytes()

class EngineV2(SourcesMixin, MonitorMixin, RecoveryMixin, Engine):
    def __init__(self, work):
        super().__init__(work)
        self._original = None
        self._activity = None
        self._computed = None

    def load(self):
        super().load()
        if self.data["events"][0]["payload"].get("contract_version") != 2:
            fail("v2 engine cannot operate a v1 work")
        allowed = {"init", "configure", "record", "run-started", "run", "close", "reopen", "gate", "impact", "source-update", "resource", "attempt", "run-resolution", "run-investigation"}
        if any(e["kind"] not in allowed for e in self.data["events"]):
            fail("unknown v2 journal event kind")

    @staticmethod
    def v2(request):
        if type(request.get("schema_version")) is not int or type(request.get("contract_version")) is not int or request["schema_version"] != 2 or request["contract_version"] != 2:
            fail("v2 work requires schema_version=2 and contract_version=2")

    @staticmethod
    def same_actor(a, b, exact=False):
        return a == b if exact else a["id"] == b["id"] or a["context"] == b["context"]

    def validate_extra(self, request, fields):
        shape(request, ("schema_version", "contract_version", "actor") + tuple(fields))
        self.v2(request)
        actor(request["actor"])

    def match_config(self, request):
        config = self.current_config()
        if request["config_operation"] != config["op"]:
            fail("request belongs to another configuration")
        return config

    def report_references(self, request):
        if not isinstance(request["evidence"], list) or not request["evidence"]:
            fail("nonempty factual evidence required")
        return {"report": self.reference(request["report"]), "evidence": [self.reference(e) for e in request["evidence"]]}

    @contextmanager
    def adapting(self, original, activity=None):
        if self._original is not None:
            fail("nested adapter invocation")
        self._original, self._activity = original, activity
        try:
            yield
        finally:
            self._original = self._activity = None
            self._computed = None

    def duplicate(self, op, request):
        # The idempotency identity binds the complete v2 request, including all
        # extension fields, rather than only its v1-compatible projection.
        if self._original is not None:
            request = {"kind": request["kind"], "input": self._original}
        key, prior = super().duplicate(op, request)
        if not prior and self._activity:
            kind, target, who = self._activity
            self.assert_ready(kind, target, who)
        return key, prior

    def init(self, project, title, op):
        with self.adapting({"schema_version": 2, "contract_version": 2, "project": str(Path(project).absolute()), "title": title}):
            return super().init(project, title, op)

    def append(self, kind, op, request_hash, payload):
        if kind == "init":
            payload = {**payload, "contract_version": 2}
        elif kind == "configure":
            payload = self.configure_payload(payload, self._original)
        elif kind == "record":
            payload = dict(payload)
            payload.pop("skill_revision", None)
            payload["schema_version"] = payload["contract_version"] = 2
            config = self.current_config(False)
            name = "delivery-" + KINDS[payload["kind"]]
            payload["skill_pin"] = self.effective_pins(config)[name]
            payload["orchestrate_pin"] = self.effective_pins(config)["delivery-orchestrate"]["tree_hash"]
        return super().append(kind, op, request_hash, payload)

    def configure(self, request, op):
        shape(request, ("schema_version", "contract_version") + CONFIG_CORE + CONFIG_EXTRA,
              ("design", "reuse") + CONFIG_OPTIONAL)
        self.v2(request)
        core = {k: v for k, v in request.items() if k in CONFIG_CORE + ("design", "reuse")}
        core.update(schema_version=1, contract_version=1, skill_revision="actual source pins captured by v2")
        with self.adapting(request):
            return super().configure(core, op)

    def configure_payload(self, payload, request):
        old_configs = [e for e in self.data["events"] if e["kind"] == "configure"]
        if old_configs:
            old_config = old_configs[-1]
            latest = self.records(old_config)
            for reuse in request.get("reuse", []):
                original = next((e for e in self.data["events"] if e["kind"] == "record" and e["op"] == reuse["operation_id"]), None)
                pair = latest.get((original["payload"]["kind"], original["payload"]["target"])) if original else None
                if not pair or pair[0] != reuse["operation_id"] or not self.record_current(pair[1], old_config, ignore_config=True):
                    fail("cannot reuse stale latest rebound result from current admission")
            inherited = self.impact_state(old_config)["extra_context"]
            for identity in inherited:
                kind, target = identity.split(":", 1)
                self.target(payload, kind, target)
            payload["inherited_context"] = {key: sorted(value) for key, value in inherited.items()}
            transfers = self.validate_recovery_transfers(request.get("recovery_transfers", []), old_config, payload)
            for unknown in self.unknown_runs(old_config):
                if not unknown["settled"] and unknown["operation"] not in transfers:
                    fail("recover incomplete run or explicitly transfer a current investigation before reconfiguration")
                owner = self.target(payload, "verification", unknown["acceptance"])
                if not set(unknown["tasks"]) <= set(owner["tasks"]):
                    fail("preserve historical unknown-run acceptance owner and task coverage")
            payload["recovery_transfers"] = list(transfers.values())
        elif request.get("recovery_transfers"):
            fail("recovery transfers require a previous configuration")
        authors = request["source_authors"]
        expected = ("plan", "mapping", "design") if "design" in request else ("plan", "mapping")
        shape(authors, expected, name="source_authors")
        merged = {}
        for kind, values in authors.items():
            if not isinstance(values, list) or not values:
                fail("nonempty source author list required")
            for value in values:
                actor(value)
            merged[kind] = list(values)
        merged["mapping"].append(request["actor"])
        for event in self.data["events"]:
            if event["kind"] == "configure":
                for kind, values in event["payload"].get("source_authors", {}).items():
                    merged.setdefault(kind, []).extend(values)
        for kind in merged:
            merged[kind] = list({(v["id"], v["context"]): v for v in merged[kind]}.values())
        policy = request["admission_policy"]
        shape(policy, ("plan_review", "design_review", "reason", "scale", "significant_replan"), name="admission_policy")
        for key in ("plan_review", "design_review", "significant_replan"):
            if type(policy[key]) is not bool:
                fail("admission policy values must be bool")
        text(policy["reason"], "policy.reason")
        if policy["scale"] not in ("small", "large") or ((policy["scale"] == "large" or policy["significant_replan"]) and not policy["plan_review"]):
            fail("large task/significant replan requires independent plan review")
        if policy["design_review"] and "design" not in request:
            fail("required design review needs design source")
        old = [e for e in self.data["events"] if e["kind"] == "configure"]
        change = request["change"]
        shape(change, ("category", "reason"), ("previous_config", "authorization"), name="change")
        text(change["reason"], "change.reason")
        if change["category"] not in ("initial", "within_grant", "organization", "material"):
            fail("unknown change category")
        if old and (change["category"] == "initial" or change.get("previous_config") != old[-1]["op"]):
            fail("reconfiguration must reference previous admission and classify its change")
        if not old and change["category"] != "initial":
            fail("first configuration must be initial")
        if old:
            previous = {a["id"]: a for a in old[-1]["payload"]["spec"]["acceptance"]}
            current = {a["id"]: a for a in payload["spec"]["acceptance"]}
            weakening = any(a["required"] and (key not in current or not current[key]["required"] or (not a.get("waivable", False) and current[key].get("waivable", False)) or (a["method"] == "command" and current[key]["method"] != "command")) for key, a in previous.items())
            if weakening and change["category"] != "material":
                fail("mechanical acceptance weakening requires material change and specific authorization")
        if change["category"] == "material":
            payload["sources"]["change_authorization"] = self.reference(change.get("authorization"), True)
        requirements = request["requirements"]
        if not isinstance(requirements, list) or not requirements:
            fail("requirements inventory required")
        seen = set()
        source_paths = {v["path"] for v in payload["sources"].values() if isinstance(v, dict) and "path" in v}
        for requirement in requirements:
            shape(requirement, ("id", "source", "tasks", "acceptance"), name="requirement")
            text(requirement["id"], "requirement.id")
            if requirement["id"] in seen:
                fail("duplicate requirement id")
            seen.add(requirement["id"])
            strings(requirement["tasks"], "requirement tasks")
            strings(requirement["acceptance"], "requirement acceptance")
            if requirement["source"].get("path") not in source_paths:
                fail("requirement must reference bound plan/design/authorization")
            reference = self.reference(requirement["source"], True)
            payload["sources"].setdefault("requirements", []).append(reference)
            for task in requirement["tasks"]:
                self.target(payload, "implementation", task)
            covered = set()
            for ac in requirement["acceptance"]:
                covered.update(self.target(payload, "verification", ac)["tasks"])
            if not set(requirement["tasks"]) <= covered:
                fail("requirement acceptance misses its task coverage")
        resources = request.get("resources", [])
        if not isinstance(resources, list):
            fail("resources must be array")
        for value in resources:
            shape(value, ("id", "mode", "tasks"), name="configured resource")
            text(value["id"], "resource id")
            if value["mode"] not in ("read", "write"):
                fail("invalid resource mode")
            strings(value["tasks"], "resource tasks")
            for target in value["tasks"]:
                self.target(payload, "implementation", target)
            if value["id"].startswith("path:"):
                safe_path(self.project, value["id"][5:], allow_missing=True)
        if "transition" in request:
            transition = request["transition"]
            shape(transition, ("from_work", "journal_hash", "reason"), name="transition")
            text(transition["reason"], "transition.reason")
            prior_work = safe_path(self.project, transition["from_work"])
            if prior_work == self.work:
                fail("transition cannot refer to its own work")
            prior_engine = Engine(prior_work)
            with prior_engine.locked():
                if prior_engine.data["events"][-1]["hash"] != transition["journal_hash"]:
                    fail("transition must bind real previous journal head")
            payload["transition"] = transition
        payload.pop("skill_revision", None)
        payload.update(contract_version=2, source_authors=merged, admission_policy=policy,
                       change=change, requirements=requirements, resources=resources)
        payload["monitor"] = self.validate_monitor(request["monitor"], payload)
        payload["skill_pins"] = self.collect_sources(request["skill_sources"])
        if old:
            accepted_pins = self.effective_pins(old[-1])
            if any(name in accepted_pins and pin["tree_hash"] != accepted_pins[name]["tree_hash"] for name, pin in payload["skill_pins"].items()):
                fail("skill source changed: explicit compatible source-update or linked new work required")
        for name in ("delivery-implement", "delivery-review", "delivery-verify", "delivery-plan"):
            if name not in payload["skill_pins"]:
                fail("missing used professional source: " + name)
        if "design" in request and "delivery-design" not in payload["skill_pins"]:
            fail("missing design source pin")
        payload["monitor_baseline"] = self.inventory(payload)
        payload["protected_index"] = old[0]["payload"].get("protected_index") if old else self.capture_index()
        return payload

    def capture_index(self):
        try:
            paths = subprocess.run(["git", "diff", "--cached", "--name-only", "-z"], cwd=self.project, capture_output=True, timeout=5)
            if paths.returncode != 0:
                return None
            names = [p.decode("utf-8", "surrogateescape") for p in paths.stdout.split(b"\0") if p]
            return {path: self.index_entry(path) for path in names}
        except (OSError, subprocess.TimeoutExpired):
            return None

    def index_entry(self, path):
        result = subprocess.run(["git", "ls-files", "--stage", "-z", "--", path], cwd=self.project, capture_output=True, timeout=5)
        if result.returncode != 0:
            fail("cannot inspect protected staged file")
        return digest(result.stdout)

    def required_gates(self, config):
        policy = config["payload"]["admission_policy"]
        required = {"mapping_review"}
        required.update(k for k in ("plan_review", "design_review") if policy[k])
        if config["payload"]["change"]["category"] != "initial":
            required.add("change_review")
        return required

    def gate_state(self, config):
        latest = {}
        for event in self.data["events"]:
            if event["kind"] == "gate" and event["payload"]["config_op"] == config["op"]:
                latest[event["payload"]["kind"]] = event
        result = {}
        for kind in self.required_gates(config) | set(latest):
            event = latest.get(kind)
            status = "pending"
            if event:
                p = event["payload"]
                names = self.gate_sources(kind)
                pins = p.get("skill_pins", {})
                current = all(pins.get(name) in self.valid_pin_hashes(config, name) for name in names)
                status = p["result"] if current and self.references_current(p["references"]) and self.references_current(config["payload"]["sources"]) else "stale"
            result[kind] = {"status": status, "operation": event["op"] if event else None}
        return result

    @staticmethod
    def gate_sources(kind):
        professional = {"plan_review": "delivery-plan", "design_review": "delivery-design"}.get(kind)
        return {"delivery-orchestrate"} | ({professional} if professional else set())

    def gate(self, request, op):
        self.validate_extra(request, ("config_operation", "kind", "report", "result", "summary", "evidence"))
        if request["kind"] not in GATES or request["result"] not in ("passed", "failed", "unknown"):
            fail("invalid admission gate kind/result")
        text(request["summary"], "summary")
        with self.locked():
            key, prior = self.duplicate(op, {"kind": "gate", "input": request})
            if prior:
                return prior
            self.active()
            config = self.match_config(request)
            if any(d["name"] in self.gate_sources(request["kind"]) for d in self.source_drift(config)):
                fail("actual gate skill source drift; accept compatible update or restore pin")
            if request["kind"] == "design_review" and "design" not in config["payload"]["sources"]:
                fail("design review requires actual configured design source")
            authors = config["payload"]["source_authors"]
            roles = {"plan_review": ["plan"], "design_review": ["design"], "mapping_review": list(authors), "change_review": ["mapping"]}[request["kind"]]
            excluded = [a for role in roles for a in authors.get(role, [])]
            if any(self.same_actor(request["actor"], a) for a in excluded):
                fail("gate actor/context is a current or historical source author")
            return self.append("gate", op, key, {**request, "config_op": config["op"],
                               "config_hash": config["hash"], "references": self.report_references(request),
                               "skill_pins": {name: pin["tree_hash"] for name, pin in self.effective_pins(config).items()}})

    def record(self, request, op):
        shape(request, ("schema_version", "contract_version") + RECORD_CORE, RECORD_OPTIONAL)
        self.v2(request)
        core = {**request, "schema_version": 1, "contract_version": 1, "skill_revision": "actual source pin captured by v2"}
        with self.adapting(request, (request["kind"], request["target"], request["actor"])):
            return super().record(core, op)

    def close(self, request, op):
        shape(request, ("schema_version", "contract_version", "actor", "mode", "summary", "report", "exceptions"))
        self.v2(request)
        with self.adapting(request, ("close", None, request["actor"])):
            return super().close({**request, "schema_version": 1, "contract_version": 1}, op)

    def target_scope(self, config, kind, target):
        scopes = super().target_scope(config, kind, target)
        # Effective impact context is applied only to matching configured events.
        current = next((e for e in reversed(self.data["events"]) if e["kind"] == "configure" and e["payload"] is config), None)
        if current:
            info = self.impact_state(current)
            scopes += list(info["extra_context"].get(kind + ":" + target, []))
        return sorted(set(scopes))

    def record_current(self, record, config, ignore_config=False):
        if not super().record_current(record, config, ignore_config):
            return False
        provenance = config
        if record.get("readmitted_from"):
            original = next((e for e in self.data["events"] if e["kind"] == "record" and e["op"] == record["readmitted_from"]), None)
            if original:
                provenance = next(e for e in self.data["events"] if e["kind"] == "configure" and e["op"] == original["payload"]["config_op"])
        if "skill_pin" in record:
            pin = record["skill_pin"]
            if pin["tree_hash"] not in self.valid_pin_hashes(provenance, pin["name"]) or record["orchestrate_pin"] not in self.valid_pin_hashes(provenance, "delivery-orchestrate"):
                return False
        info = self.impact_state(config)
        op = next((e["op"] for e in self.data["events"] if e["kind"] == "record" and e["payload"] is record), record.get("readmitted_from"))
        if op in info["invalidated"]:
            return False
        if record.get("run_operation"):
            run = next((e for e in self.data["events"] if e["kind"] == "run" and e["op"] == record["run_operation"]), None)
            if run:
                latest = next((e for e in reversed(self.data["events"]) if e["kind"] in ("run", "run-started") and e["payload"]["acceptance"] == record["target"] and e["payload"]["config_op"] == config["op"]), None)
                if latest and latest["op"] != run["op"]:
                    return False
            if run:
                binding = next(e for e in self.data["events"] if e["kind"] == "configure" and e["op"] == run["payload"]["config_op"])
                if not self.valid_run_recoveries(run, binding, live=binding["op"] == config["op"]):
                    return False
        return True

    def validate_verification(self, request, item, config, snapshot, references):
        super().validate_verification(request, item, config, snapshot, references)
        if request.get("run_operation"):
            run = next((e for e in self.data["events"] if e["kind"] == "run" and e["op"] == request["run_operation"]), None)
            if run and not self.valid_run_recoveries(run, config):
                fail("run recovery evidence is stale or belongs to another acceptance owner")
            latest = next((e for e in reversed(self.data["events"]) if e["kind"] in ("run", "run-started") and e["payload"]["acceptance"] == item["id"] and e["payload"]["config_op"] == config["op"]), None)
            if not latest or latest["kind"] != "run" or latest["op"] != request["run_operation"]:
                fail("verification must use latest actual run, not bypass a later failure")

    def state(self):
        config = self.current_config(False)
        state = super().state()
        gates = self.gate_state(config)
        impacts = self.impact_state(config)
        drift = self.source_drift(config)
        diagnoses = self.diagnosis_state(config)
        state.update(contract_version=2, admission=gates, unassessed_changes=impacts["changes"],
                     change_set_hash=impacts["change_set_hash"], unsupported_entries=impacts["inventory"]["unsupported"],
                     skill_drift=drift, resources=self.held_resources(), diagnosis_required=diagnoses,
                     unknown_runs=self.unknown_runs(config))
        diagnostics = []
        def add(code, sources, evidence, action, target=None):
            diagnostics.append({"code": code, "target": target, "sources": sources, "evidence_needed": evidence, "next_action": action})
        for name, value in gates.items():
            if value["status"] != "passed":
                add("admission_" + value["status"], [name], ["current independent report and evidence"], "gate " + name)
        if impacts["changes"]:
            add("unassessed_changes", [c["path"] for c in impacts["changes"]], ["current change-set judgement"], "impact")
        if impacts["inventory"]["unsupported"]:
            add("unsupported_entries", [e["path"] for e in impacts["inventory"]["unsupported"]], ["remove/replace unsupported entry or justified generated exclusion"], "configure")
        for item in drift:
            add("skill_drift", [item["name"]], ["restored actual source or independent compatible update"], "source / source-update")
        for item in state["unknown_runs"]:
            action = "configure with explicit recovery_transfers or renew investigation" if item.get("investigation") and not item["resolution"] else "resolve-run then new run and verdict"
            add("incomplete_run", [item["operation"]], ["side-effect and process investigation"], action, item["acceptance"])
        for item in diagnoses:
            add("diagnosis_required", [item["failure_key"]], ["new facts or substantiated strategy"], "attempt", item["id"])
        state["diagnostics"] = diagnostics
        return state

    def assert_ready(self, kind, target, who):
        actor(who)
        self.active()
        config = self.current_config()
        state = self.state()
        if any(g["status"] != "passed" for g in state["admission"].values()):
            fail("required independent admission gate is not passed")
        if state["unassessed_changes"] or state["unsupported_entries"]:
            fail("outside changes/unsupported entries require explicit assessment")
        relevant_sources = {"delivery-orchestrate"}
        if kind in KINDS:
            relevant_sources.add("delivery-" + KINDS[kind])
        if any(d["name"] in relevant_sources for d in state["skill_drift"]):
            fail("actual skill source drift; restore source or explicitly accept update")
        if any(kind == "close" or (d["kind"], d["id"]) == (kind, target) for d in state["diagnosis_required"]):
            fail("repeated failure requires new factual diagnosis/strategy")
        self.recovery_for(config, kind, target, closing=kind == "close")
        self.assert_resources(config, kind, target, who)
        protected = config["payload"].get("protected_index") or {}
        if any(self.index_entry(path) != expected for path, expected in protected.items()):
            fail("existing user staged entry changed; restore or obtain explicit project decision")

    def inspect(self, command):
        with self.locked():
            if not any(e["kind"] == "configure" for e in self.data["events"]):
                return {"contract_version": 2, "configuration": "missing", "diagnostics": [{"code": "configure_required", "target": None, "sources": [], "evidence_needed": ["plan and authorization"], "next_action": "configure"}]}
            state = self.state()
            if command == "status":
                return state
            if command == "check":
                return {"journal_integrity": "passed", "contract_version": 2, "configuration": state["configuration"], "lifecycle": state["lifecycle"], "note": "Mechanical integrity only; not semantic approval or delivery success."}
            config = self.current_config(False)
            ready, blocked = [], []
            global_block = state["configuration"] != "current" or state["lifecycle"] != "active" or any(g["status"] != "passed" for g in state["admission"].values()) or bool(state["unassessed_changes"] or state["unsupported_entries"])
            for kind, group in (("implementation", "tasks"), ("review", "reviews"), ("verification", "acceptance")):
                for item in config["payload"]["spec"][group]:
                    status = state[kind][item["id"]]["status"]
                    if status == "passed":
                        continue
                    row = {"kind": kind, "target": item["id"], "status": status, "resources": self.required_resources(config, kind, item["id"])}
                    specific = any(d["name"] in ("delivery-orchestrate", "delivery-" + KINDS[kind]) for d in state["skill_drift"]) or any((d["kind"], d["id"]) == (kind, item["id"]) for d in state["diagnosis_required"])
                    try:
                        self.recovery_for(config, kind, item["id"])
                    except DeliveryError:
                        specific = True
                    (blocked if global_block or specific or not self.dependencies_pass(item, kind, state) else ready).append(row)
            return {"contract_version": 2, "ready": ready, "blocked": blocked, "diagnostics": state["diagnostics"], "note": "Eligibility still requires explicit resource claim and reading full professional sources."}

    def run(self, acceptance, who, timeout, op):
        actor(who)
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0 or timeout > 86400:
            fail("timeout must be 0 < seconds <= 86400")
        request = {"kind": "run", "acceptance": acceptance, "actor": who, "timeout": timeout}
        with self.locked():
            key, prior = self.duplicate(op, request)
            if prior:
                return prior
            self.assert_ready("verification", acceptance, who)
            config = self.current_config()
            item = self.target(config["payload"], "verification", acceptance)
            if item["method"] != "command" or not self.dependencies_pass(item, "verification", self.state()):
                fail("run requires command method and passed prerequisites")
            scopes = self.target_scope(config["payload"], "verification", acceptance)
            before = self.snapshot(scopes)
            recovery = self.recovery_for(config, "verification", acceptance, all_operations=True)
            start = {"acceptance": acceptance, "tasks": item["tasks"], "command": item["command"], "actor": who,
                     "config_op": config["op"], "before": before, "recovery_operations": recovery, "recovery_operation": recovery[-1] if recovery else None,
                     "monitor_hash": self.inventory(config["payload"])["hash"],
                     "orchestrate_pin": self.effective_pins(config)["delivery-orchestrate"]["tree_hash"]}
            self.append("run-started", op, key, start)
        # The durable reservation precedes execution. Unlike v1, v2 releases
        # the journal lock here; another process can inspect the unknown run.
        code, timed_out, error, stdout, stderr = None, False, None, b"", b""
        try:
            process = subprocess.Popen(item["command"], cwd=self.project, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True)
            try:
                stdout, stderr = process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                timed_out = True
                os.killpg(process.pid, signal.SIGKILL)
                stdout, stderr = process.communicate()
            code = process.returncode
        except OSError as exc:
            error, stderr = str(exc), str(exc).encode()
        with self.locked():
            try:
                after = self.snapshot(scopes)
            except (DeliveryError, OSError) as exc:
                after = {"hash": None, "scopes": scopes, "error": str(exc)}
            current = self.current_config(False)
            stable = current["op"] == config["op"] and self.references_current(config["payload"]["sources"]) and self.inventory(config["payload"])["hash"] == start["monitor_hash"] and not any(d["name"] in ("delivery-orchestrate", "delivery-verify") for d in self.source_drift(config))
            try:
                self.assert_resources(config, "verification", acceptance, who)
            except DeliveryError:
                stable = False
            return self.append("run", op, key, {**start, "after": after, "sources_stable": stable,
                                "exit_code": code, "timed_out": timed_out, "error": error,
                                "stdout": self.blob(stdout), "stderr": self.blob(stderr)})
