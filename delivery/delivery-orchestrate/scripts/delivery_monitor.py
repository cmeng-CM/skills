"""Project inventory, explicit impact and cooperative resources for delivery v2."""
import json
import os
from pathlib import Path
import stat

from delivery import canonical, digest, fail, safe_path, shape, strings, text


DEPENDENCY_NAMES = {"node_modules", ".venv", "venv", "vendor", "target", "Pods", ".gradle", ".m2",
                    ".pnpm-store", "__pycache__", ".tox", ".nox"}
GENERATED_NAMES = {"dist", "build", "out", ".next", ".nuxt", ".svelte-kit", ".turbo", ".parcel-cache",
                   "coverage", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache"}


def _directory_size(path):
    files = total = 0
    errors = []
    stack = [path]
    while stack:
        current = stack.pop()
        try:
            children = list(current.iterdir())
        except OSError as exc:
            errors.append({"path": current.as_posix(), "error": str(exc)})
            continue
        for child in children:
            try:
                info = child.lstat()
            except OSError as exc:
                errors.append({"path": child.as_posix(), "error": str(exc)})
                continue
            if stat.S_ISLNK(info.st_mode):
                continue
            if stat.S_ISDIR(info.st_mode):
                stack.append(child)
            elif stat.S_ISREG(info.st_mode):
                files += 1
                total += info.st_size
    return files, total, errors


def preflight(project, work, threshold=1000):
    """Suggest explicit monitor exclusions without reading file contents or state."""
    project = Path(project).absolute()
    if not project.is_dir():
        fail("project must be an existing directory")
    work_path = Path(work).absolute()
    try:
        work_relative = work_path.relative_to(project).as_posix()
    except ValueError:
        fail("work must be inside project")
    candidates, unreadable, seen = [], [], set()

    def visit(path):
        try:
            children = sorted(path.iterdir())
        except OSError as exc:
            unreadable.append({"path": path.relative_to(project).as_posix(), "error": str(exc)})
            return
        for child in children:
            relative = child.relative_to(project).as_posix()
            if relative == ".git" or relative == work_relative:
                continue
            try:
                info = child.lstat()
            except OSError as exc:
                unreadable.append({"path": relative, "error": str(exc)})
                continue
            if stat.S_ISLNK(info.st_mode):
                continue
            if not stat.S_ISDIR(info.st_mode):
                continue
            name = child.name
            kind = None
            evidence = None
            if name in DEPENDENCY_NAMES or (name == "cache" and child.parent.name == ".yarn"):
                kind, evidence = "dependency", "conventional dependency/install directory"
            elif name in GENERATED_NAMES:
                kind, evidence = "generated", "conventional generated/cache directory"
            if kind and relative not in seen:
                files, total, errors = _directory_size(child)
                seen.add(relative)
                for error in errors:
                    try:
                        error["path"] = Path(error["path"]).relative_to(project).as_posix()
                    except ValueError:
                        pass
                unreadable.extend(errors)
                candidates.append({"path": relative, "kind": kind, "files": files, "bytes": total,
                                   "high_yield": files >= threshold, "evidence": evidence,
                                   "confirmation_required": kind == "generated",
                                   "reason": ("Dependency/install output; exclude only if it contains no vendored product source."
                                              if kind == "dependency" else
                                              "Generated/cache output; confirm it is reproducible and not product source.")})
                continue
            visit(child)

    visit(project)
    candidates.sort(key=lambda item: (-item["bytes"], item["path"]))
    return {"project": str(project), "work": work_relative, "threshold": threshold,
            "candidates": candidates, "unreadable": unreadable,
            "note": "Read-only suggestion. Confirm entries and add them to monitor.exclude; nothing was changed."}


def overlaps(a, b):
    a, b = Path(a), Path(b)
    return a == b or a in b.parents or b in a.parents


LOADED_SOURCE_BYTES = Path(__file__).read_bytes()

class MonitorMixin:
    def validate_monitor(self, value, config):
        shape(value, ("roots", "exclude"), name="monitor")
        if value["roots"] != ["."] or not isinstance(value["exclude"], list):
            fail('monitor roots must be ["."] and exclude must be array')
        protected = [path for paths in config.get("inherited_context", {}).values() for path in paths]
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
        return self.impact_state_with(config, self.inventory(config["payload"]))

    def impact_state_with(self, config, current):
        """Derive impact information from a supplied inventory snapshot."""
        baseline = self.load_snapshot(config["payload"]["monitor_baseline"])
        invalid = [op for e in self.data["events"] if e["kind"] in ("impact", "source-update") and e["payload"].get("config_op") == config["op"] for op in e["payload"].get("invalidated_operations", [])]
        extra = {key: set(paths) for key, paths in config["payload"].get("inherited_context", {}).items()}
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
                judged = self.load_snapshot(p["inventory"])
                bound_baseline = p.get("baseline_hash")
                if bound_baseline is None:
                    # Read earlier v2 events conservatively: their change-set
                    # identity must prove complete coverage from this baseline.
                    bound = self.outside_changes(config, baseline, judged)
                    linked = digest(canonical(bound)) == p["change_set_hash"]
                else:
                    linked = bound_baseline == baseline["hash"]
                if not linked:
                    continue
                baseline = judged
        changes = self.outside_changes(config, baseline, current)
        return {"changes": changes, "change_set_hash": digest(canonical(changes)), "inventory": current,
                "baseline_hash": baseline["hash"], "invalidated": set(invalid), "extra_context": extra}

    def store_snapshot(self, entries, unsupported):
        data = canonical({"entries": entries, "unsupported": unsupported})
        stored = self.blob(data)
        return {"object_hash": stored["object_hash"], "entries_hash": digest(canonical(entries)),
                "entries_count": len(entries), "bytes": stored["bytes"]}

    def load_snapshot(self, value):
        if not isinstance(value, dict):
            fail("invalid snapshot reference")
        if "object_hash" in value:
            key = value["object_hash"]
            path = self.runtime / "objects" / key
            if path.is_symlink() or not path.is_file() or digest(path.read_bytes()) != key:
                fail("snapshot object is missing or corrupted; reconfigure or reimpact")
            if value.get("bytes") is not None and value["bytes"] != path.stat().st_size:
                fail("snapshot object size mismatch; reconfigure or reimpact")
            try:
                stored = json.loads(path.read_text())
            except (OSError, ValueError):
                fail("snapshot object cannot be decoded; reconfigure or reimpact")
            shape(stored, ("entries", "unsupported"), name="snapshot object")
            if not isinstance(stored["entries"], dict) or not isinstance(stored["unsupported"], list):
                fail("snapshot object has invalid shape; reconfigure or reimpact")
            entries_hash = digest(canonical(stored["entries"]))
            if entries_hash != value.get("entries_hash"):
                fail("snapshot entries hash mismatch")
            if value.get("entries_count") != len(stored["entries"]):
                fail("snapshot entry count mismatch")
            return {"entries": stored["entries"], "hash": entries_hash, "unsupported": stored["unsupported"]}
        if "entries" in value and "hash" in value:
            return {"entries": value["entries"], "hash": value["hash"], "unsupported": value.get("unsupported", [])}
        fail("invalid snapshot reference")

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
                                "references": self.report_references(request),
                                "inventory": self.store_snapshot(current["inventory"]["entries"], current["inventory"]["unsupported"]),
                                "baseline_hash": current["baseline_hash"],
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
                            fail("resource conflict; explicit owner release required", "resource_conflict")
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
                fail("close requires writer resources to be returned", "resource_conflict")
            return
        for needed in self.required_resources(config, kind, target):
            compatible = [h for h in held if h["id"] == needed["id"] and self.same_actor(h["actor"], who, exact=True) and (h["mode"] == "write" or needed["mode"] == "read")]
            if not compatible:
                fail("activity requires owned resource: " + needed["id"] + ":" + needed["mode"], "resource_conflict")
