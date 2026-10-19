"""Explicit v2 admission; reuses the unchanged v1 evidence and graph checks."""
from contextlib import contextmanager
from pathlib import Path
import json
import math
import os
import re
import signal
import subprocess
import time

from delivery import (Engine, DeliveryError, actor, canonical, digest, fail, read_rejections, safe_path,
                      shape, strings, text, validate_events)
from delivery_sources import SourcesMixin
from delivery_monitor import MonitorMixin, DEPENDENCY_NAMES, GENERATED_NAMES
from delivery_recovery import RecoveryMixin
from delivery_implementation import ImplementationMixin

KINDS = {"implementation": "implement", "review": "review", "verification": "verify"}
GATES = {"plan_review", "design_review", "mapping_review", "change_review"}
REUSABLE_GATES = {"design_review", "plan_review", "mapping_review"}
CONFIG_EXTRA = ("source_authors", "requirements", "admission_policy", "change", "monitor", "skill_sources")
CONFIG_OPTIONAL = ("resources", "transition", "recovery_transfers", "implementation_routes", "reuse_gates")
STATUS_START = "<!-- delivery:status:start -->"
STATUS_END = "<!-- delivery:status:end -->"
CONFIG_CORE = ("actor", "plan", "authorization", "mapping_reason", "tasks", "reviews", "acceptance")
RECORD_CORE = ("kind", "target", "actor", "report", "result", "summary", "evidence")
RECORD_OPTIONAL = ("issues", "resolutions", "run_operation", "confirmation", "supersedes", "reason", "implementation_skill", "implementation_authors")


LOADED_SOURCE_BYTES = Path(__file__).read_bytes()

class EngineV2(ImplementationMixin, SourcesMixin, MonitorMixin, RecoveryMixin, Engine):
    def __init__(self, work):
        super().__init__(work)
        self._original = None
        self._activity = None
        self._computed = None
        self._snapshot = None
        self._inventory_scans = 0
        self._inventory_seconds = 0.0
        self.last_warnings = []

    def load(self):
        super().load()
        self._snapshot = None
        if self.data["events"][0]["payload"].get("contract_version") != 2:
            fail("v2 engine cannot operate a v1 work")
        allowed = {"init", "configure", "record", "run-started", "run", "close", "reopen", "gate", "impact", "source-update", "resource", "attempt", "run-resolution", "run-investigation", "implementation-protocol"}
        if any(e["kind"] not in allowed for e in self.data["events"]):
            fail("unknown v2 journal event kind")
        self.validate_implementation_protocol()

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

    def scan_inventory(self, payload):
        started = time.monotonic()
        current = self.inventory(payload)
        self._inventory_scans += 1
        self._inventory_seconds += time.monotonic() - started
        return current

    def inventory_snapshot(self, config):
        """Single inventory scan per config per command, shared by all readers."""
        key = (config["op"], len(self.data["events"]), self.data["schema_version"])
        if self._snapshot is not None and self._snapshot["key"] == key:
            return self._snapshot["value"]
        current = self.scan_inventory(config["payload"])
        info = self.impact_state_with(config, current)
        value = {"inventory": current, "info": info, "key": key}
        self._snapshot = {"key": key, "value": value}
        return value

    def impact_state(self, config):
        return self.inventory_snapshot(config)["info"]

    def duplicate(self, op, request):
        # The idempotency identity binds the complete v2 request, including all
        # extension fields, rather than only its v1-compatible projection.
        if self._original is not None:
            request = {"kind": request["kind"], "input": self._original}
        key, prior = super().duplicate(op, request)
        if not prior and self._activity:
            kind, target, who = self._activity
            self.assert_ready(kind, target, who)
            if kind in KINDS:
                self.validate_implementation_record(self._original, self.current_config())
        return key, prior

    def init(self, project, title, op):
        with self.adapting({"schema_version": 2, "contract_version": 2, "project": str(Path(project).absolute()), "title": title}):
            return super().init(project, title, op)

    @staticmethod
    def is_snapshot_ref(value):
        return isinstance(value, dict) and "object_hash" in value and "entries_hash" in value

    def upgrade_schema(self):
        """Create the schema 1 rollback point, then switch the container in the
        same atomic write that appends the first snapshot reference."""
        if self.data["schema_version"] == 2:
            return
        backup = self.runtime / "journal.schema1.bak"
        if backup.is_symlink() or (backup.exists() and not backup.is_file()):
            fail("journal schema backup is not a regular file")
        if not backup.exists():
            self.atomic(backup, self.journal_path.read_bytes())
        self.data["schema_version"] = 2

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
            name = self.activity_skill(config, payload["kind"], payload["target"])
            payload.update(self.implementation_record_fields(self._original, config))
            payload["skill_pin"] = self.effective_pins(config)[name]
            payload["orchestrate_pin"] = self.effective_pins(config)["delivery-orchestrate"]["tree_hash"]
        if kind in ("configure", "impact") and (self.is_snapshot_ref(payload.get("monitor_baseline"))
                                                or self.is_snapshot_ref(payload.get("inventory"))):
            self.upgrade_schema()
        event = super().append(kind, op, request_hash, payload)
        self._snapshot = None
        return event

    def append_many(self, items):
        if self.data["schema_version"] != 2:
            fail("verify-batch requires journal schema 2; configure first or use single verify")
        events = super().append_many(items)
        self._snapshot = None
        return events

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
        self.validate_implementation_routes(payload, request)
        payload["monitor"] = self.validate_monitor(request["monitor"], payload)
        payload["skill_pins"] = self.collect_sources(request["skill_sources"])
        if "delivery-fix" in payload["skill_pins"] and not self.fix_enabled():
            fail("delivery-fix source requires explicit enable-fix")
        if old:
            accepted_pins = self.effective_pins(old[-1])
            if any(name in accepted_pins and pin["tree_hash"] != accepted_pins[name]["tree_hash"] for name, pin in payload["skill_pins"].items()):
                fail("skill source changed: explicit compatible source-update or linked new work required")
        used = {"delivery-review", "delivery-verify", "delivery-plan"}
        used.update(self.implementation_route(payload, task["id"])["skill"] for task in payload["spec"]["tasks"])
        for name in sorted(used):
            if name not in payload["skill_pins"]:
                fail("missing used professional source: " + name)
        if "design" in request and "delivery-design" not in payload["skill_pins"]:
            fail("missing design source pin")
        if "reuse_gates" in request:
            if not old:
                fail("gate reuse requires a previous configuration")
            payload["reused_gates"] = self.validate_reuse_gates(payload, request, old[-1])
        inventory = self.scan_inventory(payload)
        payload["monitor_baseline"] = self.store_snapshot(inventory["entries"], inventory["unsupported"])
        payload["protected_index"] = old[0]["payload"].get("protected_index") if old else self.capture_index()
        self.last_warnings = self.unexcluded_warnings(payload, inventory["entries"])
        return payload

    def monitor_only_input_view(self, payload):
        """Admission inputs whose change invalidates gate reuse.

        Derived/mechanism fields (baseline, protected index, exclude, actor,
        change reason, paths/quotes, reused record bodies, mapping author) are
        deliberately absent so that the organization-only configure can differ
        in those fields without pretending the admitted work changed. The one
        reused-related comparison is the sorted set of readmitted operation
        identities: adding or removing a record readmission changes what the
        admission accepts even when the plan/spec is unchanged. Reuse reasons
        and record bodies remain derived and are not compared.
        """
        def authors(values):
            return sorted(({"id": v["id"], "context": v["context"]} for v in values or []),
                          key=lambda v: (v["id"], v["context"]))
        sources = payload.get("sources", {})
        stored = payload.get("skill_pins", {})
        return {
            "tasks": payload["spec"]["tasks"],
            "reviews": payload["spec"]["reviews"],
            "acceptance": payload["spec"]["acceptance"],
            "requirements": payload.get("requirements"),
            "resources": payload.get("resources", []),
            "implementation_routes": payload.get("implementation_routes", {}),
            "transition": payload.get("transition"),
            "recovery_transfers": payload.get("recovery_transfers", []),
            "admission_policy": payload.get("admission_policy"),
            "sources": {name: sources[name].get("object_hash") if isinstance(sources.get(name), dict) else None
                        for name in ("plan", "design")},
            "monitor_roots": payload.get("monitor", {}).get("roots"),
            "skill_sources": {name: {"source_root": pin.get("source_root"),
                                     "contract_version": pin.get("contract_version")}
                              for name, pin in stored.items()},
            "authorization_scope": sources.get("authorization", {}).get("scope"),
            "source_authors": {"design": authors(payload.get("source_authors", {}).get("design")),
                               "plan": authors(payload.get("source_authors", {}).get("plan"))},
            "reuse_operations": sorted(item.get("op") for item in payload.get("reused", [])),
        }

    def validate_reuse_gates(self, payload, request, old_config):
        values = request.get("reuse_gates")
        if not isinstance(values, list) or not values:
            fail("reuse_gates must be a nonempty array")
        change = request["change"]
        if change["category"] != "organization":
            fail("gate reuse requires change.category organization")
        if change.get("previous_config") != old_config["op"]:
            fail("gate reuse requires the immediately previous configuration")
        if self.monitor_only_input_view(old_config["payload"]) != self.monitor_only_input_view(payload):
            fail("gate reuse requires unchanged admission inputs; only monitor.exclude may change")
        seen, result = set(), []
        for value in values:
            shape(value, ("kind", "operation_id", "reason"), name="reuse gate")
            text(value["reason"], "reuse_gate.reason")
            kind = value["kind"]
            if kind not in REUSABLE_GATES:
                fail("only design/plan/mapping gates can be reused; change_review must be new")
            if kind in seen:
                fail("duplicate reused gate kind")
            seen.add(kind)
            gate = next((e for e in self.data["events"] if e["kind"] == "gate" and e["op"] == value["operation_id"]), None)
            if not gate or gate["payload"]["kind"] != kind:
                fail("reused gate operation not found or kind mismatch")
            if gate["payload"]["config_op"] != old_config["op"]:
                fail("reused gate must belong to the immediately previous configuration")
            if gate["payload"]["result"] != "passed":
                fail("only passed gates can be reused")
            if not self.references_current(gate["payload"]["references"]):
                fail("reused gate references changed")
            pins = gate["payload"].get("skill_pins", {})
            if not all(pins.get(name) in self.valid_pin_hashes(old_config, name) for name in self.gate_sources(kind)):
                fail("reused gate skill pins are stale")
            roles = {"plan_review": ["plan"], "design_review": ["design"],
                     "mapping_review": list(payload["source_authors"])}[kind]
            excluded = [a for role in roles for a in payload["source_authors"].get(role, [])]
            if any(self.same_actor(gate["payload"]["actor"], a) for a in excluded):
                fail("reused gate actor is a current or historical source author")
            legacy, source = False, "gate"
            expected = {name: payload["sources"][name]["object_hash"]
                        for name in ("plan", "design") if name in payload["sources"]}
            if "source_hashes" in gate["payload"]:
                if gate["payload"]["source_hashes"] != expected:
                    fail("reused gate source hashes disagree with current sources")
            else:
                cutoff = self.legacy_cutoff()
                if "gate_protocol" in gate["payload"] or (cutoff is not None and gate["seq"] >= cutoff):
                    fail("new or post-cutoff gate lacks source_hashes; fail closed")
                previous = {name: old_config["payload"]["sources"][name]["object_hash"]
                            for name in ("plan", "design")
                            if name in old_config["payload"]["sources"]}
                if previous != expected:
                    fail("legacy gate anchor disagrees with current sources")
                if not self.references_current(old_config["payload"]["sources"]):
                    fail("legacy gate requires current previous sources")
                legacy, source = True, "legacy"
            result.append({"kind": kind, "operation_id": gate["op"], "reason": value["reason"],
                           "legacy": legacy, "source": source})
        return result

    def unexcluded_warnings(self, payload, entries):
        excluded = [e["path"] for e in payload["monitor"]["exclude"]]
        found = {}
        for path in entries:
            parts = Path(path).parts
            for index, part in enumerate(parts[:-1]):
                conventional = part in DEPENDENCY_NAMES or part in GENERATED_NAMES or (
                    part == "cache" and index > 0 and parts[index - 1] == ".yarn")
                if not conventional:
                    continue
                candidate = "/".join(parts[:index + 1])
                if not any(candidate == e or candidate.startswith(e + "/") for e in excluded):
                    found[candidate] = found.get(candidate, 0) + 1
                break
        return [{"code": "unexcluded_generated_directory", "path": path, "entries": count,
                 "advice": "run preflight and confirm explicit monitor.exclude"}
                for path, count in sorted(found.items()) if count]

    def legacy_cutoff(self):
        for event in self.data["events"]:
            if event["kind"] == "configure" and self.is_snapshot_ref(event["payload"].get("monitor_baseline")):
                return event["seq"]
            if event["kind"] == "impact" and self.is_snapshot_ref(event["payload"].get("inventory")):
                return event["seq"]
        return None

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
        reused = {value["kind"]: value for value in config["payload"].get("reused_gates", [])}
        result = {}
        for kind in self.required_gates(config) | set(latest) | set(reused):
            event = latest.get(kind)
            if event:
                result[kind] = self.gate_event_state(config, event)
            elif kind in reused:
                result[kind] = self.reused_gate_state(config, reused[kind])
            else:
                result[kind] = {"status": "pending", "operation": None}
        return result

    def gate_source_state(self, config, event):
        """Return (matches, legacy, issue) for a gate's source anchor."""
        p = event["payload"]
        expected = {name: config["payload"]["sources"][name]["object_hash"]
                    for name in ("plan", "design") if name in config["payload"]["sources"]}
        if "source_hashes" in p:
            return p["source_hashes"] == expected, False, None
        cutoff = self.legacy_cutoff()
        if "gate_protocol" in p:
            return False, False, "gate_protocol_without_source_hashes"
        if cutoff is not None and event["seq"] >= cutoff:
            return False, False, "post_cutoff_gate_without_source_hashes"
        return True, True, None

    def gate_event_state(self, config, event):
        p = event["payload"]
        pins = p.get("skill_pins", {})
        current = all(pins.get(name) in self.valid_pin_hashes(config, name)
                      for name in self.gate_sources(p["kind"]))
        matches, legacy, issue = self.gate_source_state(config, event)
        valid = (current and self.references_current(p["references"])
                 and self.references_current(config["payload"]["sources"]) and matches)
        row = {"status": p["result"] if valid else "stale", "operation": event["op"],
               "source": "legacy" if legacy else "gate", "legacy": legacy}
        if issue:
            row["issue"] = issue
        return row

    def reused_gate_state(self, config, value):
        event = next((e for e in self.data["events"] if e["kind"] == "gate" and e["op"] == value["operation_id"]), None)
        if not event:
            return {"status": "stale", "operation": None, "issue": "missing_reused_gate"}
        p = event["payload"]
        pins = p.get("skill_pins", {})
        pins_current = all(pins.get(name) in self.valid_pin_hashes(config, name)
                           for name in self.gate_sources(p["kind"]))
        matches, legacy, issue = self.gate_source_state(config, event)
        old = next((e for e in self.data["events"] if e["kind"] == "configure"
                    and e["op"] == p["config_op"]), None)
        provenance = bool(old and self.references_current(old["payload"]["sources"]))
        valid = (pins_current and provenance and self.references_current(p["references"])
                 and matches and p["result"] == "passed" and p["kind"] == value["kind"])
        row = {"status": "passed" if valid else "stale", "operation": event["op"],
               "reused_from": p["config_op"], "source": "legacy" if legacy else "gate", "legacy": legacy}
        if issue:
            row["issue"] = issue
        return row

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
            sources = config["payload"]["sources"]
            return self.append("gate", op, key, {**request, "config_op": config["op"],
                               "config_hash": config["hash"], "references": self.report_references(request),
                               "source_hashes": {name: sources[name]["object_hash"]
                                                 for name in ("plan", "design") if name in sources},
                               "gate_protocol": 2,
                               "skill_pins": {name: pin["tree_hash"] for name, pin in self.effective_pins(config).items()}})

    def record(self, request, op):
        shape(request, ("schema_version", "contract_version") + RECORD_CORE, RECORD_OPTIONAL)
        self.v2(request)
        core = {k: v for k, v in request.items() if k not in ("implementation_skill", "implementation_authors")}
        core.update(schema_version=1, contract_version=1, skill_revision="actual source pin captured by v2")
        with self.adapting(request, (request["kind"], request["target"], request["actor"])):
            return super().record(core, op)

    def batch_record_payload(self, item, config):
        shape(item, ("op", "config_operation") + RECORD_CORE,
              ("schema_version", "contract_version") + RECORD_OPTIONAL, name="batch item")
        if "schema_version" in item or "contract_version" in item:
            self.v2(item)
        if item["config_operation"] != config["op"]:
            fail("batch item belongs to another configuration")
        core = {k: v for k, v in item.items() if k in RECORD_CORE + RECORD_OPTIONAL}
        core.update(schema_version=1, contract_version=1, skill_revision="actual source pin captured by v2")
        with self.adapting(item, (item["kind"], item["target"], item["actor"])):
            self.assert_ready(item["kind"], item["target"], item["actor"])
            if item["kind"] in KINDS:
                self.validate_implementation_record(item, config)
            payload = super().prepare_record(core, config)
        payload = dict(payload)
        payload.pop("skill_revision", None)
        payload["schema_version"] = payload["contract_version"] = 2
        name = self.activity_skill(config, payload["kind"], payload["target"])
        payload.update(self.implementation_record_fields(item, config))
        payload["skill_pin"] = self.effective_pins(config)[name]
        payload["orchestrate_pin"] = self.effective_pins(config)["delivery-orchestrate"]["tree_hash"]
        return payload

    def verify_batch(self, request, op):
        shape(request, ("schema_version", "contract_version", "batch_id", "items"))
        self.v2(request)
        text(request["batch_id"], "batch_id")
        text(op, "batch operation id")
        items = request["items"]
        if not isinstance(items, list) or not items:
            fail("batch items must be a nonempty array")
        ops, targets = set(), set()
        for item in items:
            if not isinstance(item, dict):
                fail("batch item must be an object")
            text(item.get("op"), "batch item.op")
            if item["op"] in ops:
                fail("duplicate batch item operation id")
            ops.add(item["op"])
            identity = (item.get("kind"), item.get("target"))
            if identity in targets:
                fail("duplicate batch item target")
            targets.add(identity)

        def key_for(item):
            normalized = {k: v for k, v in item.items() if k not in ("op", "config_operation")}
            normalized.setdefault("schema_version", 2)
            normalized.setdefault("contract_version", 2)
            return digest(canonical({"kind": "record", "input": normalized}))

        with self.locked():
            if self.data["schema_version"] != 2:
                fail("verify-batch requires journal schema 2; configure first or use single verify")
            config = self.current_config(False)
            for item in items:
                if item.get("config_operation") != config["op"]:
                    fail("batch item belongs to another configuration")
            existing = []
            for item in items:
                matches = [e for e in self.data["events"] if e["op"] == item["op"]]
                if matches:
                    if any(e["request_hash"] != key_for(item) for e in matches):
                        fail("operation id reused with different request")
                    event = matches[-1]
                    if event["payload"].get("config_op") != config["op"]:
                        fail("batch belongs to another configuration")
                    existing.append(event)
            if existing:
                if len(existing) != len(items):
                    fail("verify-batch partially exists; journal changed during the batch")
                return {"kind": "verify-batch", "batch_id": request["batch_id"],
                        "items": existing, "note": "Idempotent replay; no new events written."}
            self.active()
            prepared = []
            for item in items:
                prepared.append(("record", item["op"], key_for(item), self.batch_record_payload(item, config)))
            events = self.append_many(prepared)
            return {"kind": "verify-batch", "batch_id": request["batch_id"], "items": events}

    def prepare_close(self, request):
        payload = super().prepare_close(request)
        expected = (Path(self.data["work"]) / "closeout.md").as_posix()
        if not isinstance(request["report"], dict) or request["report"].get("path") != expected:
            fail("close report must point to the fixed work path " + expected)
        return payload

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
            info = self.inventory_snapshot(current)["info"]
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
        info = self.inventory_snapshot(config)["info"]
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
        snapshot = self.inventory_snapshot(config)
        impacts = snapshot["info"]
        drift = self.source_drift(config)
        diagnoses = self.diagnosis_state(config)
        config_payload = config["payload"]
        state.update(contract_version=2, admission=gates, unassessed_changes=impacts["changes"],
                     change_set_hash=impacts["change_set_hash"], unsupported_entries=impacts["inventory"]["unsupported"],
                     skill_drift=drift, resources=self.held_resources(), diagnosis_required=diagnoses,
                     unknown_runs=self.unknown_runs(config),
                     inventory={"entries": len(impacts["inventory"]["entries"]),
                                "unsupported": len(impacts["inventory"]["unsupported"]),
                                "hash": impacts["inventory"]["hash"],
                                "duration_ms": round(self._inventory_seconds * 1000, 1),
                                "excluded_paths": [e["path"] for e in config_payload["monitor"]["exclude"]],
                                "inventory_calls": self._inventory_scans})
        blockers = self.base_blockers(config, state)
        state["ready_to_implement"] = not blockers
        state["blocked_reason"] = blockers
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

    def base_blockers(self, config, state):
        reasons = []
        if state["configuration"] != "current":
            reasons.append("configuration sources changed; explicit configure required")
        if state["lifecycle"] != "active":
            reasons.append("work lifecycle is " + state["lifecycle"])
        for kind, row in sorted(state["admission"].items()):
            if row["status"] != "passed":
                reasons.append("gate " + kind + ": " + row["status"])
        if state["unassessed_changes"]:
            reasons.append(str(len(state["unassessed_changes"])) + " unassessed outside changes")
        if state["unsupported_entries"]:
            reasons.append(str(len(state["unsupported_entries"])) + " unsupported entries")
        if any(d["name"] == "delivery-orchestrate" for d in state["skill_drift"]):
            reasons.append("orchestrate skill source drift")
        for item in state["unknown_runs"]:
            if item["config_op"] == config["op"] and not item["settled"]:
                reasons.append("incomplete run " + item["operation"] + " requires evidenced resolution")
        for item in state["diagnosis_required"]:
            reasons.append("repeated failure requires diagnosis: " + item["failure_key"])
        return reasons

    def _guard_info(self, config, state, kind, target, who=None):
        item = self.target(config["payload"], kind, target)
        reasons = list(self.base_blockers(config, state))
        deps = list(item.get("depends", []))
        if kind != "implementation":
            deps += [{"kind": "implementation", "id": task} for task in item["tasks"]]
        blocked_deps = []
        for dep in deps:
            group = "verification" if dep["kind"] == "acceptance" else dep["kind"]
            if state[group][dep["id"]]["status"] != "passed":
                blocked_deps.append({"kind": dep["kind"], "id": dep["id"],
                                     "status": state[group][dep["id"]]["status"]})
        if blocked_deps:
            reasons.append("dependencies not passed: " + ", ".join(d["kind"] + ":" + d["id"] for d in blocked_deps))
        selected = self.activity_skill(config, kind, target)
        if any(d["name"] == selected for d in state["skill_drift"]):
            reasons.append("professional skill source drift: " + selected)
        held = self.held_resources()
        resources = []
        for needed in self.required_resources(config, kind, target):
            holders = [h for h in held if h["id"] == needed["id"]]
            conflicts = [h for h in held if self.resource_overlap(h["id"], needed["id"])
                         and "write" in (h["mode"], needed["mode"])]
            compatible = bool(who) and any(
                h["id"] == needed["id"] and self.same_actor(h["actor"], who, exact=True)
                and (h["mode"] == "write" or needed["mode"] == "read") for h in held)
            claimable = not conflicts or compatible
            resources.append({**needed, "held_by": holders, "claimable": claimable})
            if conflicts and not compatible:
                holders_text = ", ".join(sorted(h["actor"]["id"] for h in conflicts))
                if who is None:
                    reasons.append("resource conflict; rerun guard with --actor/--context to confirm ownership: "
                                   + needed["id"] + ":" + needed["mode"] + " held by " + holders_text)
                else:
                    reasons.append("resource conflict: " + needed["id"] + ":" + needed["mode"]
                                   + " held by " + holders_text)
        try:
            self.recovery_for(config, kind, target, closing=kind == "close")
        except DeliveryError as exc:
            reasons.append(str(exc))
        return {"kind": kind, "target": target, "ready": not reasons, "blocked_reasons": reasons,
                "gates": state["admission"], "dependencies": {"passed": not blocked_deps, "blocked": blocked_deps},
                "resources": resources,
                "note": "Read-only advisory check. It does not reserve resources or approve gates; record/run/close still enforce them."}

    def guard(self, kind, target, who=None):
        kind = {"task": "implementation", "review": "review", "verification": "verification"}.get(kind)
        if kind is None:
            fail("guard kind must be task, review or verification")
        if who is not None:
            actor(who)
        with self.locked():
            if not any(e["kind"] == "configure" for e in self.data["events"]):
                return {"kind": kind, "target": target, "ready": False,
                        "blocked_reasons": ["configure required"], "gates": {},
                        "dependencies": {"passed": False, "blocked": []}, "resources": [],
                        "note": "Read-only advisory check; configuration is missing."}
            config = self.current_config(False)
            return self._guard_info(config, self.state(), kind, target, who)

    def approval_anchor(self, config):
        """Resolve the approved plan/design content anchor for preclose checks."""
        result = {}
        reused = {value["kind"]: value for value in config["payload"].get("reused_gates", [])}
        for kind, name in (("plan_review", "plan"), ("design_review", "design")):
            if name not in config["payload"]["sources"]:
                continue
            gate = next((e for e in reversed(self.data["events"]) if e["kind"] == "gate"
                         and e["payload"].get("config_op") == config["op"]
                         and e["payload"]["kind"] == kind and e["payload"]["result"] == "passed"), None)
            if not gate and kind in reused:
                gate = next((e for e in self.data["events"] if e["kind"] == "gate"
                             and e["op"] == reused[kind]["operation_id"]), None)
            if gate:
                matches, legacy, issue = self.gate_source_state(config, gate)
                if issue:
                    result[name] = {"anchor": None, "source": "error", "issue": issue,
                                    "operation": gate["op"]}
                elif "source_hashes" in gate["payload"]:
                    result[name] = {"anchor": gate["payload"]["source_hashes"].get(name),
                                    "source": "gate", "operation": gate["op"]}
                else:
                    result[name] = {"anchor": config["payload"]["sources"][name]["object_hash"],
                                    "source": "legacy" if legacy else "gate", "operation": gate["op"],
                                    "legacy": True}
            else:
                result[name] = {"anchor": config["payload"]["sources"][name]["object_hash"],
                                "source": "fallback", "operation": None}
        return result

    def status_body(self, config, state):
        payload = config["payload"]
        lines = ["", "## Delivery status", "",
                 f"- lifecycle: {state['lifecycle']}",
                 f"- configuration: {config['op']} ({state['configuration']})",
                 f"- inventory: {state['inventory']['entries']} entries, "
                 f"{state['inventory']['unsupported']} unsupported",
                 f"- excluded: {', '.join(state['inventory']['excluded_paths']) or '(none)'}",
                 f"- ready_to_implement: {str(state['ready_to_implement']).lower()}",
                 "- gates: " + ", ".join(f"{k}={v['status']}" for k, v in sorted(state["admission"].items())),
                 f"- unassessed_changes: {len(state['unassessed_changes'])}",
                 f"- unsupported_entries: {len(state['unsupported_entries'])}",
                 f"- unknown_runs: {sum(1 for item in state['unknown_runs'] if not item['settled'])} unsettled",
                 f"- held_resources: {len(state['resources'])}",
                 ""]
        for title, group in (("Tasks", "implementation"), ("Reviews", "review"), ("Verification", "verification")):
            lines.append("### " + title)
            lines.append("")
            for item in payload["spec"][{"implementation": "tasks", "review": "reviews", "verification": "acceptance"}[group]]:
                row = state[group][item["id"]]
                manual = (" manual-pending" if group == "verification" and item["method"] == "manual"
                          and row["status"] in ("pending", "unknown", "stale") else "")
                lines.append(f"- {item['id']}: {row['status']}{manual} ({row['operation_id'] or 'no operation'})")
            lines.append("")
        if state["blocked_reason"]:
            lines.append("### Blocking")
            lines.append("")
            lines.extend("- " + reason for reason in state["blocked_reason"])
            lines.append("")
        return "\n".join(lines).strip("\n")

    def status_view_consistency(self, config, state):
        path = self.work / "status.md"
        if path.is_symlink() or not path.is_file():
            return {"status": "missing"}
        text_value = path.read_text()
        if STATUS_START not in text_value or STATUS_END not in text_value:
            return {"status": "missing markers"}
        body = text_value.split(STATUS_START, 1)[1].split(STATUS_END, 1)[0].strip("\n")
        expected = self.status_body(config, state)
        return {"status": "current" if body == expected else "stale"}

    def write_status(self):
        with self.locked():
            path = self.work / "status.md"
            if path.is_symlink():
                fail("status.md must not be a symlink")
            if not any(e["kind"] == "configure" for e in self.data["events"]):
                body = "## Delivery status\n\n- configure_required: true"
                old = path.read_text() if path.is_file() else ""
                new = self.replace_status_region(old, body)
            else:
                config = self.current_config(False)
                state = self.state()
                old = path.read_text() if path.is_file() else ""
                new = self.replace_status_region(old, self.status_body(config, state))
            self.atomic(path, new.encode())
            return {"kind": "status", "path": "status.md", "written": True,
                    "note": "Generated region derives from the journal; manual notes never prove acceptance."}

    @staticmethod
    def replace_status_region(old, body):
        if STATUS_START in old and STATUS_END in old:
            before, rest = old.split(STATUS_START, 1)
            _, after = rest.split(STATUS_END, 1)
            return before + STATUS_START + "\n" + body + "\n" + STATUS_END + after
        if old.strip():
            return "# Delivery status\n\n" + STATUS_START + "\n" + body + "\n" + STATUS_END + "\n\n" + old
        return ("# Delivery status\n\n" + STATUS_START + "\n" + body + "\n" + STATUS_END
                + "\n\n## 人工补充（不参与门禁判定）\n")

    def orphan_admissions(self):
        directory = self.work / "admission"
        if directory.is_symlink() or not directory.is_dir():
            return [], 0
        hashes = {e["request_hash"] for e in self.data["events"]}
        kinds = {e["kind"] for e in self.data["events"]}
        orphans, matched = [], 0
        for path in sorted(directory.iterdir()):
            if path.is_symlink() or not path.is_file() or path.suffix != ".json":
                continue
            try:
                value = json.loads(path.read_text())
            except (OSError, ValueError) as exc:
                orphans.append({"path": path.name, "error": str(exc)})
                continue
            candidates = [value]
            if isinstance(value, dict) and "request" in value:
                candidates.append(value["request"])
            # Admission files hold the raw request. The journal hash binds the
            # request together with its command kind, so match both projections.
            projections = []
            for candidate in candidates:
                if isinstance(candidate, (dict, list)):
                    projections.append(canonical(candidate))
                    projections.extend(canonical({"kind": kind, "input": candidate}) for kind in kinds)
            if any(digest(projection) in hashes for projection in projections):
                matched += 1
            else:
                orphans.append({"path": path.name})
        return orphans, matched

    def rejection_report(self):
        try:
            records, bad = read_rejections(self.runtime / "rejected.jsonl")
        except OSError as exc:
            return {"records": 0, "roots": 0, "bad_lines": [], "root_details": [],
                    "unresolved": [], "unresolved_count": 0, "batch_unresolved_count": 0,
                    "error": str(exc)}
        ops = {e["op"] for e in self.data["events"]}
        roots = {}
        for value in records:
            root = value.get("retry_of") or value.get("id")
            entry = roots.setdefault(root, {"id": root, "op": value.get("op"),
                                            "error_code": value.get("error_code"),
                                            "attempts": 0, "first_at": value.get("at"),
                                            "last_at": value.get("at"),
                                            "last_message": value.get("error_message")})
            entry["attempts"] += 1
            entry["last_at"] = value.get("at")
            entry["last_message"] = value.get("error_message")
        # A verify-batch call op is intentionally not a journal op; its items
        # are the durable keys, so the batch call itself cannot be looked up
        # here. Report it separately instead of leaving permanent noise.
        unresolved = [value for value in records
                      if value.get("op") not in ops and value.get("command") != "verify-batch"]
        batch_unresolved = [value for value in records
                            if value.get("op") not in ops and value.get("command") == "verify-batch"]
        details = sorted(roots.values(), key=lambda item: item["last_at"] or "", reverse=True)[:10]
        return {"records": len(records), "roots": len(roots), "bad_lines": bad,
                "root_details": details,
                "unresolved": unresolved[-10:], "unresolved_count": len(unresolved),
                "batch_unresolved_count": len(batch_unresolved)}

    def preclose(self, request=None):
        if request is not None and not isinstance(request, dict):
            fail("preclose input must be an object")
        with self.locked():
            if not any(e["kind"] == "configure" for e in self.data["events"]):
                return {"ready": False, "blocking": ["configure required"], "warnings": []}
            config = self.current_config(False)
            state = self.state()
            blocking = list(self.base_blockers(config, state))
            warnings = []
            if request is not None:
                expected = (Path(self.data["work"]) / "closeout.md").as_posix()
                if not isinstance(request.get("report"), dict) or request["report"].get("path") != expected:
                    blocking.append("close report must point to " + expected)
                try:
                    self.assert_ready("close", None, request.get("actor"))
                except DeliveryError as exc:
                    blocking.append("close readiness: " + str(exc))
                try:
                    with self.adapting(request, ("close", None, request.get("actor"))):
                        super().prepare_close({**request, "schema_version": 1, "contract_version": 1})
                except DeliveryError as exc:
                    blocking.append("close judgement: " + str(exc))
            else:
                for group in ("implementation", "review"):
                    for target, row in state[group].items():
                        if row["status"] != "passed":
                            blocking.append(f"{group} {target}: {row['status']}")
                for item in config["payload"]["spec"]["acceptance"]:
                    if item["required"] and state["verification"][item["id"]]["status"] != "passed":
                        blocking.append(f"required acceptance {item['id']}: {state['verification'][item['id']]['status']}")
            if any(h["mode"] == "write" for h in state["resources"]):
                blocking.append("write resources are still held")
            protected = config["payload"].get("protected_index") or {}
            try:
                changed = [path for path, expected in protected.items() if self.index_entry(path) != expected]
            except DeliveryError as exc:
                blocking.append("protected staged entries cannot be checked: " + str(exc))
            else:
                if changed:
                    blocking.append("existing user staged entries changed: " + ", ".join(changed))
            try:
                self.recovery_for(config, "close", None, closing=True)
            except DeliveryError as exc:
                blocking.append("close recovery: " + str(exc))
            closing = self.closing_sources(config)
            drifted = sorted(d["name"] for d in state["skill_drift"] if d["name"] in closing)
            if drifted:
                blocking.append("source drift: " + ", ".join(drifted))
            for (kind, target), (op, record) in sorted(self.records(config).items()):
                if not self.references_current(record["references"]):
                    blocking.append(f"record evidence is missing or changed: {kind}:{target}")
            for name, anchor in self.approval_anchor(config).items():
                if anchor["source"] == "error":
                    blocking.append(f"{name} approval anchor invalid: {anchor.get('issue')}")
                    continue
                source = config["payload"]["sources"][name]
                try:
                    actual = digest(safe_path(self.project, source["path"]).read_bytes())
                except (DeliveryError, OSError):
                    actual = None
                if actual != anchor["anchor"]:
                    blocking.append(f"{name} was edited after approval")
                if anchor["source"] == "legacy":
                    warnings.append(f"{name} approval uses legacy gate anchor")
                elif anchor["source"] == "fallback":
                    warnings.append(f"{name} approval uses configure fallback anchor")
            view = self.status_view_consistency(config, state)
            if view["status"] == "missing":
                warnings.append("status.md is missing; run status --write-status")
            elif view["status"] != "current":
                warnings.append("status.md is stale; journal remains authoritative")
            index_path = self.work / "index.md"
            if not index_path.exists():
                warnings.append("index.md is missing (warning for older work)")
            else:
                index_text = index_path.read_text(errors="replace")
                if STATUS_START in index_text or re.search(r"(?m)^\|\s*(状态|status)\s*\|", index_text):
                    warnings.append("index.md appears to carry status; keep it pure navigation")
            for name in ("plan", "design"):
                source = config["payload"]["sources"].get(name)
                if not isinstance(source, dict) or not source.get("path"):
                    continue
                try:
                    source_text = safe_path(self.project, source["path"]).read_text(errors="replace")
                except (DeliveryError, OSError):
                    continue
                if "实施状态" in source_text or "更新时间与状态" in source_text:
                    warnings.append(f"{name} still carries mutable execution status; converge on next version")
            orphans, matched = self.orphan_admissions()
            if orphans:
                warnings.append(f"{len(orphans)} admission file(s) do not match any journal request hash")
            rejected = self.rejection_report()
            if rejected["unresolved_count"]:
                warnings.append(f"{rejected['unresolved_count']} rejected write command(s) have no successful operation")
            if rejected.get("batch_unresolved_count"):
                warnings.append(f"{rejected['batch_unresolved_count']} rejected verify-batch call(s); inspect their item operations")
            if rejected["bad_lines"]:
                warnings.append(f"{len(rejected['bad_lines'])} rejected log line(s) are malformed")
            return {"ready": not blocking, "blocking": blocking, "warnings": warnings,
                    "admission": {"matched": matched, "orphans": orphans},
                    "rejected": {"records": rejected["records"], "unresolved": rejected["unresolved_count"],
                                 "batch_unresolved": rejected.get("batch_unresolved_count", 0)},
                    "approval_anchor": self.approval_anchor(config)}

    def doctor(self):
        with self.locked():
            report = {"work": self.data["work"], "journal": {
                "schema_version": self.data["schema_version"], "events": len(self.data["events"])},
                "warnings": [], "admission": {}, "rejected": {}, "evidence": [],
                "status_view": None, "rollback_backup": None, "approval_anchor": {}}
            if not any(e["kind"] == "configure" for e in self.data["events"]):
                report["configuration"] = "missing"
                report["warnings"].append("configure required")
                return report
            config = self.current_config(False)
            state = self.state()
            unsettled = [item for item in state["unknown_runs"] if not item["settled"]]
            report["configuration"] = config["op"]
            report["lifecycle"] = state["lifecycle"]
            report["state"] = {
                "configuration": state["configuration"],
                "admission": state["admission"],
                "unassessed_changes": len(state["unassessed_changes"]),
                "unsupported_entries": len(state["unsupported_entries"]),
                "unknown_runs": unsettled,
                "held_resources": state["resources"],
                "diagnostics": state["diagnostics"],
            }
            if state["configuration"] != "current":
                report["warnings"].append("configuration sources changed")
            for kind, row in sorted(state["admission"].items()):
                if row["status"] != "passed":
                    report["warnings"].append(f"gate {kind}: {row['status']}")
            if state["unassessed_changes"]:
                report["warnings"].append(f"{len(state['unassessed_changes'])} unassessed outside changes")
            if state["unsupported_entries"]:
                report["warnings"].append(f"{len(state['unsupported_entries'])} unsupported entries")
            if unsettled:
                report["warnings"].append(f"{len(unsettled)} unsettled run(s)")
            if any(item["mode"] == "write" for item in state["resources"]):
                report["warnings"].append("write resources are still held")
            if state["diagnosis_required"]:
                report["warnings"].append("repeated failure requires new diagnosis")
            report["status_view"] = self.status_view_consistency(config, state)
            if report["status_view"]["status"] != "current":
                report["warnings"].append("status view: " + report["status_view"]["status"])
            orphans, matched = self.orphan_admissions()
            report["admission"] = {"matched": matched, "orphans": orphans}
            if orphans:
                report["warnings"].append(f"{len(orphans)} unmatched admission file(s)")
            report["rejected"] = self.rejection_report()
            if report["rejected"]["bad_lines"]:
                report["warnings"].append("rejected log has malformed lines")
            if report["rejected"]["unresolved_count"]:
                report["warnings"].append("rejected write commands without a successful operation")
            if report["rejected"].get("batch_unresolved_count"):
                report["warnings"].append("rejected verify-batch calls; inspect their item operations")
            if report["rejected"]["root_details"]:
                report["rejected"]["summary"] = [
                    {"op": item["op"], "error_code": item["error_code"],
                     "attempts": item["attempts"], "first_id": item["id"]}
                    for item in report["rejected"]["root_details"]]
            missing = []
            for (kind, target), (op, record) in sorted(self.records(config).items()):
                if not self.references_current(record["references"]):
                    missing.append(kind + ":" + target)
            report["evidence"] = missing
            if missing:
                report["warnings"].append("records with missing/changed evidence: " + ", ".join(missing))
            if self.data["schema_version"] == 2:
                backup = self.runtime / "journal.schema1.bak"
                if not backup.is_file() or backup.is_symlink():
                    report["rollback_backup"] = {"status": "missing"}
                    report["warnings"].append("schema 1 rollback backup is missing")
                else:
                    try:
                        data = json.loads(backup.read_text())
                        if not isinstance(data, dict):
                            fail("rollback backup is not an object")
                        if data.get("schema_version") != 1:
                            fail("rollback backup is not schema 1")
                        if data.get("project") != self.data["project"] or data.get("work") != self.data["work"]:
                            fail("rollback backup belongs to another work")
                        validate_events(data["events"])
                        for event in data["events"]:
                            self.check_objects(event["payload"])
                        report["rollback_backup"] = {"status": "readable", "bytes": backup.stat().st_size,
                                                     "events": len(data["events"])}
                    except (OSError, ValueError, DeliveryError) as exc:
                        report["rollback_backup"] = {"status": "invalid", "error": str(exc)}
                        report["warnings"].append("schema 1 rollback backup is unreadable")
            report["approval_anchor"] = self.approval_anchor(config)
            for name, anchor in report["approval_anchor"].items():
                if anchor["source"] in ("legacy", "fallback", "error"):
                    report["warnings"].append(name + " approval anchor: " + anchor["source"])
            return report

    def closing_sources(self, config):
        """Current delivery inputs and admitted producers, not every installed package."""
        names = {"delivery-orchestrate", "delivery-plan", "delivery-review", "delivery-verify"}
        if "design" in config["payload"]["sources"]:
            names.add("delivery-design")
        names.update(self.activity_skill(config, "implementation", task["id"])
                     for task in config["payload"]["spec"]["tasks"])
        names.update(record["skill_pin"]["name"] for _, record in self.records(config).values()
                     if "skill_pin" in record)
        return names

    def assert_ready(self, kind, target, who):
        actor(who)
        self.active()
        config = self.current_config()
        state = self.state()
        if any(g["status"] != "passed" for g in state["admission"].values()):
            fail("required independent admission gate is not passed", "gate_not_passed")
        if state["unassessed_changes"] or state["unsupported_entries"]:
            fail("outside changes/unsupported entries require explicit assessment")
        relevant_sources = {"delivery-orchestrate"}
        if kind == "close":
            relevant_sources = self.closing_sources(config)
        elif kind in KINDS:
            relevant_sources.add(self.activity_skill(config, kind, target))
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
            global_reasons = self.base_blockers(config, state)
            for kind, group in (("implementation", "tasks"), ("review", "reviews"), ("verification", "acceptance")):
                for item in config["payload"]["spec"][group]:
                    status = state[kind][item["id"]]["status"]
                    if status == "passed":
                        continue
                    selected = self.activity_skill(config, kind, item["id"])
                    row = {"kind": kind, "target": item["id"], "status": status,
                           "resources": self.required_resources(config, kind, item["id"])}
                    if self.fix_enabled():
                        row["skill"] = selected
                        if kind == "implementation":
                            row["implementation_route"] = self.implementation_route(config, item["id"])
                            if selected == "delivery-fix":
                                row["report_location"] = row["implementation_route"]["bug_path"] + "/NNN/fix.md"
                    reasons = list(global_reasons)
                    if any(d["name"] in ("delivery-orchestrate", selected) for d in state["skill_drift"]):
                        reasons.append("relevant skill source drift")
                    if any((d["kind"], d["id"]) == (kind, item["id"]) for d in state["diagnosis_required"]):
                        reasons.append("repeated failure requires new diagnosis")
                    try:
                        self.recovery_for(config, kind, item["id"])
                    except DeliveryError as exc:
                        reasons.append(str(exc))
                    if not self.dependencies_pass(item, kind, state):
                        reasons.append("dependencies are not passed")
                    row["blocked_reason"] = reasons
                    (blocked if reasons else ready).append(row)
            return {"contract_version": 2, "ready": ready, "blocked": blocked,
                    "ready_to_implement": not global_reasons, "blocked_reason": global_reasons,
                    "diagnostics": state["diagnostics"],
                    "note": "Eligibility still requires explicit resource claim and reading full professional sources."}

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
            monitor = self.inventory_snapshot(config)
            start = {"acceptance": acceptance, "tasks": item["tasks"], "command": item["command"], "actor": who,
                     "config_op": config["op"], "before": before, "recovery_operations": recovery, "recovery_operation": recovery[-1] if recovery else None,
                     "monitor_hash": monitor["inventory"]["hash"],
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
            stable = (current["op"] == config["op"]
                      and self.references_current(config["payload"]["sources"])
                      and self.inventory_snapshot(current)["inventory"]["hash"] == start["monitor_hash"]
                      and not any(d["name"] in ("delivery-orchestrate", "delivery-verify") for d in self.source_drift(config)))
            try:
                self.assert_resources(config, "verification", acceptance, who)
            except DeliveryError:
                stable = False
            return self.append("run", op, key, {**start, "after": after, "sources_stable": stable,
                                "exit_code": code, "timed_out": timed_out, "error": error,
                                "stdout": self.blob(stdout), "stderr": self.blob(stderr)})
