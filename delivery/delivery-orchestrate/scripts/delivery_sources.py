"""Recoverable package sources and execution-package binding for delivery v2."""
from pathlib import Path
import os
import re
import sys

from delivery import actor, canonical, digest, fail, safe_path, shape, strings, text

NAMES = {"delivery-" + name for name in ("design", "plan", "implement", "review", "verify", "orchestrate")}
MODULES = ("delivery", "delivery_v2", "delivery_sources", "delivery_monitor", "delivery_recovery")


LOADED_SOURCE_BYTES = Path(__file__).read_bytes()

class SourcesMixin:
    def executing_root(self):
        import delivery
        root = Path(delivery.__file__).resolve().parents[1]
        for name in MODULES:
            module = sys.modules.get(name)
            if module is not None:
                if Path(module.__file__).resolve().parent != root / "scripts":
                    fail("mixed execution modules: all runtime modules must belong to the actual package")
                if Path(module.__file__).read_bytes() != getattr(module, "LOADED_SOURCE_BYTES", None):
                    fail("executing module source changed after load; restart from an actual pinned package")
        return root

    def collect_pin(self, value):
        shape(value, ("name", "root", "contract_version"), name="skill source")
        if value["name"] not in NAMES:
            fail("unknown skill name")
        expected = 2 if value["name"] == "delivery-orchestrate" else 1
        if type(value["contract_version"]) is not int or value["contract_version"] != expected:
            fail("unsupported professional/orchestration contract")
        root = Path(value["root"])
        if not root.is_absolute() or root.resolve() != root or not root.is_dir():
            fail("skill root must be a canonical actual directory")
        skill = root / "SKILL.md"
        if not skill.is_file() or f"name: {value['name']}" not in skill.read_text():
            fail("skill frontmatter name must match source")
        contract_path = root / "references" / ("contracts.md" if value["name"] == "delivery-orchestrate" else "delivery-contract.md")
        if not contract_path.is_file():
            fail("skill source contract document missing")
        declaration = re.search(r"当前版本为\s*\*\*(\d+)\*\*", contract_path.read_text())
        if declaration is None or int(declaration.group(1)) != expected:
            fail("actual skill contract declaration disagrees with requested supported version")
        entries = []
        for base, dirs, files in os.walk(root, followlinks=False):
            base = Path(base)
            dirs[:] = sorted(d for d in dirs if d not in (".git", "__pycache__"))
            for name in dirs + sorted(files):
                path = base / name
                if path.is_symlink():
                    fail("symlink inside skill source")
            for name in sorted(files):
                if name == ".DS_Store" or name.endswith((".pyc", ".pyo")):
                    continue
                path = base / name
                if not path.is_file():
                    fail("unsupported skill source entry")
                entries.append({"relative_path": path.relative_to(root).as_posix(),
                                **self.blob(path.read_bytes()),
                                "executable": bool(path.stat().st_mode & 0o111)})
        entries.sort(key=lambda e: e["relative_path"])
        return {"name": value["name"], "contract_version": expected, "source_root": str(root),
                "tree_hash": digest(canonical(entries)), "files": entries}

    def collect_sources(self, values):
        if not isinstance(values, list) or not values:
            fail("nonempty skill_sources required")
        result = {}
        for value in values:
            pin = self.collect_pin(value)
            if pin["name"] in result:
                fail("duplicate skill source")
            result[pin["name"]] = pin
        actual = self.executing_root()
        if "delivery-orchestrate" not in result or Path(result["delivery-orchestrate"]["source_root"]) != actual:
            fail("orchestrate source must be the actually executing package; cannot execute B and declare A")
        return result

    def pin_lineage(self, config, name):
        initial = config["payload"]["skill_pins"][name]
        lineage, reachable = [initial], {initial["tree_hash"]}
        for event in self.data["events"]:
            p = event["payload"]
            if event["kind"] != "source-update" or p["config_op"] != config["op"] or p["name"] != name or p["decision"] == "incompatible":
                continue
            # Each review is an explicit edge. A renewed full review from an
            # effective old pin can recover after stale evidence; descendants
            # depending solely on the stale edge cannot bridge its gap.
            if self.references_current(p["references"]) and p["old_tree_hash"] in reachable:
                lineage.append(p["pin"])
                reachable.add(p["pin"]["tree_hash"])
        return lineage

    def effective_pins(self, config):
        return {name: self.pin_lineage(config, name)[-1] for name in config["payload"]["skill_pins"]}

    def valid_pin_hashes(self, config, name):
        return {pin["tree_hash"] for pin in self.pin_lineage(config, name)}

    def source_drift(self, config):
        drift = []
        for name, pin in self.effective_pins(config).items():
            root = self.executing_root() if name == "delivery-orchestrate" else Path(pin["source_root"])
            try:
                current = self.collect_pin({"name": name, "root": str(root), "contract_version": pin["contract_version"]})
                if current["tree_hash"] != pin["tree_hash"]:
                    drift.append({"name": name, "expected": pin["tree_hash"], "actual": current["tree_hash"], "root": str(root)})
            except (OSError, ValueError) as exc:
                drift.append({"name": name, "error": str(exc)})
            except Exception as exc:
                # A missing/corrupt source is a resumable diagnostic, not a pass.
                from delivery import DeliveryError
                if not isinstance(exc, DeliveryError):
                    raise
                drift.append({"name": name, "error": str(exc)})
        return drift

    def source(self, restore=None, destination=None):
        with self.locked():
            config = self.current_config(False)
            pins = self.effective_pins(config)
            if not restore:
                return {"pins": pins, "drift": self.source_drift(config)}
            if restore not in pins or destination is None:
                fail("known source and destination required")
            dest = safe_path(self.project, destination, allow_missing=True)
            if self.work not in dest.parents or dest == self.runtime or self.runtime in dest.parents or dest.exists():
                fail("restore destination must be a new directory inside work, outside runtime")
            dest.mkdir(parents=True)
            for entry in pins[restore]["files"]:
                path = dest / entry["relative_path"]
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes((self.runtime / "objects" / entry["object_hash"]).read_bytes())
                path.chmod(0o755 if entry["executable"] else 0o644)
            return {"name": restore, "destination": destination, "tree_hash": pins[restore]["tree_hash"]}

    def source_update(self, request, op):
        self.validate_extra(request, ("config_operation", "name", "old_tree_hash", "new_root", "decision", "report", "evidence", "reason", "affected_targets"))
        with self.locked():
            key, previous = self.duplicate(op, {"kind": "source-update", "input": request})
            if previous:
                return previous
            self.active()
            # Source assessment changes no business execution or authorization.
            # Bind the immutable admission even when its plan has since changed,
            # so a pinned recovery fix can be admitted before investigating it.
            config = self.current_config(False)
            if request["config_operation"] != config["op"]:
                fail("request belongs to another configuration")
            pins = self.effective_pins(config)
            if request["name"] != "delivery-orchestrate" and any(d["name"] == "delivery-orchestrate" for d in self.source_drift(config)):
                fail("first accept actual orchestrate source before professional update")
            old = pins.get(request["name"])
            if not old or old["tree_hash"] != request["old_tree_hash"]:
                fail("source update must bind the effective old pin")
            new = self.collect_pin({"name": request["name"], "root": request["new_root"], "contract_version": old["contract_version"]})
            if new["name"] == "delivery-orchestrate" and Path(new["source_root"]) != self.executing_root():
                fail("new orchestrate source must be actual executing package")
            decision = request["decision"]
            if decision not in ("path_only", "compatible", "incompatible"):
                fail("invalid source update decision")
            if decision == "path_only" and (new["tree_hash"] != old["tree_hash"] or request["affected_targets"]):
                fail("path_only requires identical content and no invalidation")
            if decision == "compatible":
                excluded = list(config["payload"]["source_authors"]["mapping"])
                if new["name"] == "delivery-orchestrate":
                    excluded += [e["payload"]["actor"] for e in self.data["events"] if e["kind"] == "record" and e["payload"]["kind"] == "implementation"]
                if any(self.same_actor(request["actor"], a) for a in excluded):
                    fail("compatible source update needs independent review")
            references = self.report_references(request)
            targets = self.validate_targets(request["affected_targets"], config)
            invalidated = self.invalidations(config, targets) if decision == "compatible" else []
            return self.append("source-update", op, key, {**request, "config_op": config["op"], "references": references,
                                                        "pin": new, "invalidated_operations": invalidated})
