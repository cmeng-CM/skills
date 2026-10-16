"""Project inventory, explicit impact and cooperative resources for delivery v2."""
import os
from pathlib import Path
import stat

from delivery import canonical, digest, fail, safe_path, shape, strings, text


def overlaps(a, b):
    a, b = Path(a), Path(b)
    return a == b or a in b.parents or b in a.parents


LOADED_SOURCE_BYTES = Path(__file__).read_bytes()

class MonitorMixin:
    def validate_monitor(self, value, config):
        shape(value, ("roots", "exclude"), name="monitor")
        if value["roots"] != ["."] or not isinstance(value["exclude"], list):
            fail('monitor roots must be ["."] and exclude must be array')
        protected = []
        for group in ("tasks", "reviews", "acceptance"):
            for item in config["spec"][group]:
                protected += item.get("scope", []) + item.get("context_scope", [])
        def refs(v):
            if isinstance(v, dict):
                if "path" in v:
                    protected.append(v["path"])
                for child in v.values():
                    refs(child)
            elif isinstance(v, list):
                for child in v:
                    refs(child)
        refs(config["sources"])
        result = []
        for item in value["exclude"]:
            shape(item, ("path", "reason"), name="exclude")
            text(item["reason"], "exclude.reason")
            path = safe_path(self.project, item["path"], allow_missing=True)
            if path == self.project or path in self.work.parents or any(overlaps(item["path"], p) for p in protected):
                fail("monitor exclusion overlaps product/context/real source or contains current work")
            result.append(item)
        return {"roots": ["."], "exclude": result}

    def inventory(self, config):
        excludes = [".git", self.work.relative_to(self.project).as_posix()]
        excludes += [e["path"] for e in config["monitor"]["exclude"]]
        entries, unsupported = {}, []
        def skipped(relative):
            return any(relative == p or Path(p) in Path(relative).parents for p in excludes)
        def visit(path):
            relative = path.relative_to(self.project).as_posix()
            if skipped(relative):
                return
            try:
                info = path.lstat()
                if stat.S_ISLNK(info.st_mode):
                    entries[relative] = {"type": "symlink", "target": os.readlink(path)}
                elif stat.S_ISDIR(info.st_mode):
                    # Empty directory existence is relevant, but descendant edits
                    # do not change the parent's identity or trigger noise.
                    entries[relative] = {"type": "directory"}
                    for child in sorted(path.iterdir()):
                        visit(child)
                elif stat.S_ISREG(info.st_mode):
                    entries[relative] = {"type": "file", "hash": digest(path.read_bytes()), "executable": bool(info.st_mode & 0o111)}
                else:
                    entries[relative] = {"type": "unsupported", "mode": info.st_mode}
                    unsupported.append({"path": relative, "type": "unsupported"})
            except OSError as exc:
                entries[relative] = {"type": "unreadable", "error": str(exc)}
                unsupported.append({"path": relative, "type": "unreadable", "error": str(exc)})
        for child in sorted(self.project.iterdir()):
            visit(child)
        return {"entries": entries, "hash": digest(canonical(entries)), "unsupported": unsupported}

    def impact_state(self, config):
        baseline = config["payload"]["monitor_baseline"]
        invalid = [op for e in self.data["events"] if e["kind"] in ("impact", "source-update") and e["payload"].get("config_op") == config["op"] for op in e["payload"].get("invalidated_operations", [])]
        extra = {}
        for event in self.data["events"]:
            p = event["payload"]
            if p.get("config_op") != config["op"]:
                continue
            if event["kind"] == "impact":
                # Once admitted as relevant, keep context conservatively for
                # this admission, even while its judgement requires renewal.
                for target, paths in p.get("extra_context", {}).items():
                    extra.setdefault(target, set()).update(paths)
                # An invalid judgement cannot hide an earlier unassessed change.
                if not self.references_current(p["references"]):
                    continue
                bound_baseline = p.get("baseline_hash")
                if bound_baseline is None:
                    # Read earlier v2 events conservatively: their change-set
                    # identity must prove complete coverage from this baseline.
                    bound = self.outside_changes(config, baseline, p["inventory"])
                    linked = digest(canonical(bound)) == p["change_set_hash"]
                else:
                    linked = bound_baseline == baseline["hash"]
                if not linked:
                    continue
                baseline = p["inventory"]
        current = self.inventory(config["payload"])
        changes = self.outside_changes(config, baseline, current)
        return {"changes": changes, "change_set_hash": digest(canonical(changes)), "inventory": current,
                "baseline_hash": baseline["hash"], "invalidated": set(invalid), "extra_context": extra}

    def outside_changes(self, config, baseline, current):
        declared = []
        for group in ("tasks", "reviews", "acceptance"):
            for item in config["payload"]["spec"][group]:
                declared += item.get("scope", []) + item.get("context_scope", [])
        changes = []
        for path in sorted(set(baseline["entries"]) | set(current["entries"])):
            before, after = baseline["entries"].get(path), current["entries"].get(path)
            if before != after and not any(path == scope or Path(scope) in Path(path).parents or ((after or before).get("type") == "directory" and Path(path) in Path(scope).parents) for scope in declared):
                changes.append({"path": path, "before": before, "after": after})
        return changes

    def validate_targets(self, values, config):
        if not isinstance(values, list):
            fail("targets must be array")
        seen = set()
        result = []
        for value in values:
            shape(value, ("kind", "id"), name="impact target")
            if value["kind"] not in ("implementation", "review", "verification"):
                fail("invalid impact kind")
            self.target(config["payload"], value["kind"], value["id"])
            key = (value["kind"], value["id"])
            if key in seen:
                fail("duplicate impact target")
            seen.add(key)
            result.append(value)
        return result

    def invalidations(self, config, targets):
        affected = {(t["kind"], t["id"]) for t in targets}
        changed = True
        while changed:
            changed = False
            for kind, group in (("implementation", "tasks"), ("review", "reviews"), ("verification", "acceptance")):
                for item in config["payload"]["spec"][group]:
                    deps = {(d["kind"] if d["kind"] != "acceptance" else "verification", d["id"]) for d in item.get("depends", [])}
                    if kind != "implementation":
                        deps |= {("implementation", task) for task in item["tasks"]}
                    key = (kind, item["id"])
                    if key not in affected and affected & deps:
                        affected.add(key)
                        changed = True
        return [op for key, (op, _) in self.records(config).items() if key in affected]

    def impact(self, request, op):
        self.validate_extra(request, ("config_operation", "change_set_hash", "report", "evidence", "decisions"))
        with self.locked():
            key, prior = self.duplicate(op, {"kind": "impact", "input": request})
            if prior:
                return prior
            self.active()
            config = self.match_config(request)
            current = self.impact_state(config)
            if not current["changes"] or request["change_set_hash"] != current["change_set_hash"]:
                fail("impact judgement is empty or stale; inspect current changes")
            if not isinstance(request["decisions"], list):
                fail("decisions must be array")
            covered, targets, extra = [], [], {}
            for decision in request["decisions"]:
                shape(decision, ("paths", "effect", "targets", "reason"), name="impact decision")
                strings(decision["paths"], "impact paths")
                text(decision["reason"], "impact reason")
                ts = self.validate_targets(decision["targets"], config)
                if decision["effect"] not in ("related", "unrelated") or (decision["effect"] == "related") != bool(ts):
                    fail("related requires targets; unrelated forbids targets")
                covered += decision["paths"]
                targets += ts
                for t in ts:
                    extra.setdefault(t["kind"] + ":" + t["id"], []).extend(decision["paths"])
            if sorted(covered) != sorted(c["path"] for c in current["changes"]):
                fail("decisions must cover every current external change exactly once")
            return self.append("impact", op, key, {**request, "config_op": config["op"],
                                "references": self.report_references(request), "inventory": current["inventory"], "baseline_hash": current["baseline_hash"],
                                "extra_context": extra, "invalidated_operations": self.invalidations(config, targets)})

    def held_resources(self):
        held = []
        for event in self.data["events"]:
            if event["kind"] != "resource":
                continue
            p = event["payload"]
            for resource in p["resources"]:
                key = (resource["id"], p["actor"]["id"], p["actor"]["context"])
                if p["action"] == "release":
                    held = [h for h in held if not (h["id"] == resource["id"] and h["actor"]["id"] == p["actor"]["id"])]
                else:
                    held = [h for h in held if (h["id"], h["actor"]["id"], h["actor"]["context"]) != key]
                if p["action"] == "claim":
                    held.append({**resource, "actor": p["actor"], "operation": event["op"]})
        return held

    @staticmethod
    def resource_overlap(a, b):
        return overlaps(a[5:], b[5:]) if a.startswith("path:") and b.startswith("path:") else a == b

    def resource(self, request, op):
        self.validate_extra(request, ("action", "resources", "reason"))
        if request["action"] not in ("claim", "release") or not isinstance(request["resources"], list) or not request["resources"]:
            fail("resource action/array required")
        text(request["reason"], "reason")
        with self.locked():
            key, prior = self.duplicate(op, {"kind": "resource", "input": request})
            if prior:
                return prior
            self.active()
            held = self.held_resources()
            seen = set()
            for resource in request["resources"]:
                shape(resource, ("id", "mode"), name="resource")
                text(resource["id"], "resource.id")
                if resource["mode"] not in ("read", "write") or resource["id"] in seen:
                    fail("resource mode or duplicate invalid")
                seen.add(resource["id"])
                if resource["id"].startswith("path:"):
                    safe_path(self.project, resource["id"][5:], allow_missing=True)
                own = [h for h in held if h["id"] == resource["id"] and h["actor"]["id"] == request["actor"]["id"]]
                if request["action"] == "release" and not own:
                    fail("cannot release another actor's resource")
                if request["action"] == "claim":
                    for h in held:
                        if self.resource_overlap(h["id"], resource["id"]) and not self.same_actor(h["actor"], request["actor"], exact=True) and "write" in (h["mode"], resource["mode"]):
                            fail("resource conflict; explicit owner release required")
            return self.append("resource", op, key, request)

    def required_resources(self, config, kind, target):
        item = self.target(config["payload"], kind, target)
        tasks = [target] if kind == "implementation" else item["tasks"]
        result = {"path:" + s: "write" if kind == "implementation" else "read" for s in self.target_scope(config["payload"], kind, target)}
        for resource in config["payload"]["resources"]:
            if set(resource["tasks"]) & set(tasks):
                mode = resource["mode"] if kind == "implementation" or (kind == "verification" and item["method"] == "command") else "read"
                result[resource["id"]] = mode
        return [{"id": key, "mode": mode} for key, mode in sorted(result.items())]

    def assert_resources(self, config, kind, target, who):
        held = self.held_resources()
        if kind == "close":
            if any(h["mode"] == "write" for h in held):
                fail("close requires writer resources to be returned")
            return
        for needed in self.required_resources(config, kind, target):
            compatible = [h for h in held if h["id"] == needed["id"] and self.same_actor(h["actor"], who, exact=True) and (h["mode"] == "write" or needed["mode"] == "read")]
            if not compatible:
                fail("activity requires owned resource: " + needed["id"] + ":" + needed["mode"])
