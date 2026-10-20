#!/usr/bin/env python3
"""Local delivery journal and mechanical gates. No agent calls or Git mutations."""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile

# Keep one class/error identity when the CLI loads the v2 modules.
if __name__ == "__main__":
    sys.modules["delivery"] = sys.modules[__name__]


class DeliveryError(Exception):
    def __init__(self, message, code="invalid_request"):
        super().__init__(message)
        self.code = code


def fail(message, code="invalid_request"):
    raise DeliveryError(message, code)


LOADED_SOURCE_BYTES = Path(__file__).read_bytes()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def text(value, name):
    if not isinstance(value, str) or not value.strip():
        fail(f"{name}: nonempty string required")
    return value


def shape(value, required, optional=(), name="input"):
    if not isinstance(value, dict):
        fail(f"{name}: object required")
    missing = set(required) - value.keys()
    extra = value.keys() - set(required) - set(optional)
    if missing or extra:
        fail(f"{name}: missing={sorted(missing)}, unknown={sorted(extra)}")


def strings(value, name, nonempty=True, unique=True):
    if not isinstance(value, list) or (nonempty and not value):
        fail(f"{name}: {'nonempty ' if nonempty else ''}array required")
    for item in value:
        text(item, name)
    if unique and len(set(value)) != len(value):
        fail(f"{name}: duplicates")
    return value


def version(data):
    for key in ("schema_version", "contract_version"):
        if type(data.get(key)) is not int or data[key] != 1:
            fail(f"unsupported {key}; only 1 is supported")


def actor(value):
    shape(value, ("id", "context"), name="actor")
    text(value["id"], "actor.id")
    text(value["context"], "actor.context")


def validate_events(events):
    """Validate the immutable event chain without requiring a live work path."""
    previous = "0" * 64
    if not isinstance(events, list) or not events:
        fail("empty or invalid journal", "io_error")
    for number, event in enumerate(events, 1):
        shape(event, ("seq", "at", "kind", "op", "request_hash", "payload", "previous", "hash"), name="event")
        if event["seq"] != number or event["previous"] != previous:
            fail("journal chain broken", "io_error")
        body = {k: v for k, v in event.items() if k != "hash"}
        if digest(canonical(body)) != event["hash"]:
            fail("journal event hash mismatch", "io_error")
        previous = event["hash"]


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def safe_path(root, relative, allow_missing=False):
    """All stored paths are lexical project-relative, and no symlink is traversed."""
    text(relative, "path")
    p = Path(relative)
    if p.is_absolute() or ".." in p.parts or (not p.parts and relative != "."):
        fail(f"unsafe relative path: {relative}")
    current = root
    for part in p.parts:
        current = current / part
        if current.is_symlink():
            fail(f"symlink is not supported: {relative}")
    if not allow_missing and not current.exists():
        fail(f"missing path: {relative}")
    return current


class Engine:
    def __init__(self, work):
        raw = Path(work).absolute()
        for part in [raw, *raw.parents]:
            if part.is_symlink():
                fail("work path must not traverse symlinks")
        self.work = raw.resolve()
        self.runtime = self.work / "runtime"
        self.journal_path = self.runtime / "journal.json"
        self.data = None
        self.project = None

    @contextlib.contextmanager
    def locked(self, initializing=False):
        if self.runtime.is_symlink():
            fail("runtime symlink rejected")
        if initializing:
            self.runtime.mkdir(parents=True, exist_ok=True)
        if not self.runtime.is_dir():
            fail("not initialized")
        for name in ("journal.json", "lock", "objects"):
            if (self.runtime / name).is_symlink():
                fail(f"runtime/{name} symlink rejected")
        with (self.runtime / "lock").open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                if self.journal_path.exists():
                    self.load()
                yield
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)

    def load(self):
        try:
            self.data = json.loads(self.journal_path.read_text())
        except (OSError, ValueError) as exc:
            fail(f"journal cannot be read: {exc}")
        shape(self.data, ("schema_version", "project", "work", "events"), name="journal")
        if type(self.data["schema_version"]) is not int or self.data["schema_version"] not in (1, 2):
            fail("unsupported journal schema")
        self.project = Path(self.data["project"])
        if not self.project.is_absolute() or self.project.resolve() != self.project:
            fail("invalid journal project")
        if safe_path(self.project, self.data["work"]) != self.work:
            fail("journal work identity mismatch")
        validate_events(self.data["events"])
        for event in self.data["events"]:
            self.check_objects(event["payload"])

    def check_objects(self, value):
        if isinstance(value, dict):
            if "object_hash" in value:
                key = value["object_hash"]
                if not isinstance(key, str) or len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
                    fail("invalid object identity")
                p = self.runtime / "objects" / key
                if p.is_symlink() or not p.is_file() or digest(p.read_bytes()) != key:
                    fail(f"missing or corrupted immutable object: {key}")
            for child in value.values():
                self.check_objects(child)
        elif isinstance(value, list):
            for child in value:
                self.check_objects(child)

    def blob(self, data):
        objects = self.runtime / "objects"
        if objects.is_symlink():
            fail("objects symlink rejected")
        objects.mkdir(exist_ok=True)
        key = digest(data)
        dest = objects / key
        if dest.is_symlink():
            fail("object symlink rejected")
        if dest.exists():
            if dest.read_bytes() != data:
                fail("object corruption")
        else:
            self.atomic(dest, data)
        return {"object_hash": key, "bytes": len(data)}

    @staticmethod
    def atomic(path, data):
        fd, temporary = tempfile.mkstemp(prefix=".write-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as out:
                out.write(data)
                out.flush()
                os.fsync(out.fileno())
            os.replace(temporary, path)
            dfd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def new_event(self, kind, op, request_hash, payload, previous, seq=None):
        event = {"seq": len(self.data["events"]) + 1 if seq is None else seq,
                 "at": now(), "kind": kind, "op": op,
                 "request_hash": request_hash, "payload": payload, "previous": previous}
        event["hash"] = digest(canonical(event))
        return event

    def append(self, kind, op, request_hash, payload):
        events = self.data["events"]
        event = self.new_event(kind, op, request_hash, payload, events[-1]["hash"] if events else "0" * 64)
        events.append(event)
        self.atomic(self.journal_path, canonical(self.data) + b"\n")
        return event

    def append_many(self, items):
        """Construct consecutive events from the current head and write once.

        Each item is (kind, op, request_hash, payload). A crash leaves either
        the previous journal or the complete batch, never a partial batch.
        """
        events = self.data["events"]
        previous = events[-1]["hash"] if events else "0" * 64
        appended = []
        for kind, op, request_hash, payload in items:
            event = self.new_event(kind, op, request_hash, payload, previous,
                                   seq=len(events) + len(appended) + 1)
            appended.append(event)
            previous = event["hash"]
        if not appended:
            fail("empty batch")
        events.extend(appended)
        self.atomic(self.journal_path, canonical(self.data) + b"\n")
        return appended

    def duplicate(self, op, request):
        text(op, "operation id")
        key = digest(canonical(request))
        matches = [e for e in self.data["events"] if e["op"] == op] if self.data else []
        if matches:
            if any(e["request_hash"] != key for e in matches):
                fail("operation id reused with different request")
            return key, matches[-1]
        return key, None

    def init(self, project, title, op):
        project = Path(project).absolute()
        if project.resolve() != project or not project.is_dir():
            fail("project must be an existing canonical directory without symlinks")
        try:
            relative = self.work.relative_to(project).as_posix()
        except ValueError:
            fail("work must be inside project")
        if relative == "." or ".git" in Path(relative).parts:
            fail("work cannot be project root or inside .git")
        safe_path(project, relative, allow_missing=True)
        text(title, "title")
        request = {"kind": "init", "project": str(project), "work": relative, "title": title}
        with self.locked(initializing=True):
            key, existing = self.duplicate(op, request)
            if existing:
                return existing
            if self.data:
                fail("already initialized")
            self.project = project
            self.data = {"schema_version": 1, "project": str(project), "work": relative, "events": []}
            return self.append("init", op, key, {"title": title})

    def active(self):
        if not self.data:
            fail("not initialized")
        for event in reversed(self.data["events"]):
            if event["kind"] == "reopen":
                return
            if event["kind"] == "close":
                fail("closed journal is immutable; explicitly reopen first")

    def reference(self, value, quote=False):
        shape(value, ("path", "quote") if quote else ("path",), name="reference")
        p = safe_path(self.project, value["path"])
        if not p.is_file() or self.runtime == p or self.runtime in p.parents or ".git" in p.relative_to(self.project).parts:
            fail("reference must be a regular project file outside runtime/.git")
        data = p.read_bytes()
        if quote:
            text(value["quote"], "quote")
            if value["quote"] not in data.decode("utf-8", errors="replace"):
                fail("quoted source text not found")
        return {**value, **self.blob(data)}

    def references_current(self, value):
        if isinstance(value, dict):
            if "object_hash" in value and "path" in value:
                try:
                    p = safe_path(self.project, value["path"])
                    if not p.is_file() or digest(p.read_bytes()) != value["object_hash"]:
                        return False
                except (DeliveryError, OSError):
                    return False
            return all(self.references_current(v) for v in value.values())
        if isinstance(value, list):
            return all(self.references_current(v) for v in value)
        return True

    def scopes(self, values):
        strings(values, "scope")
        for relative in values:
            p = safe_path(self.project, relative, allow_missing=True)
            if ".git" in Path(relative).parts or p == self.work or self.work in p.parents:
                fail("product scope must not include work directory or .git explicitly")
        return sorted(set(values))

    def snapshot(self, scopes):
        entries = {}
        for relative in self.scopes(scopes):
            path = safe_path(self.project, relative, allow_missing=True)
            if not path.exists():
                entries[relative] = {"missing": True}
                continue
            candidates = [path]
            if path.is_dir():
                candidates = []
                for base, dirs, files in os.walk(path, followlinks=False):
                    base = Path(base)
                    for name in list(dirs):
                        d = base / name
                        if name == ".git" or d == self.work:
                            dirs.remove(name)
                        elif d.is_symlink():
                            fail(f"symlink in product scope: {d.relative_to(self.project)}")
                    entries[base.relative_to(self.project).as_posix()] = {"directory": True}
                    candidates.extend(base / f for f in files if f != ".git")
            for candidate in candidates:
                key = candidate.relative_to(self.project).as_posix()
                if candidate.is_symlink():
                    fail(f"symlink in product scope: {key}")
                if not candidate.is_file():
                    fail(f"unsupported product entry: {key}")
                entries[key] = {**self.blob(candidate.read_bytes()), "executable": bool(candidate.stat().st_mode & 0o111)}
        return {"scopes": sorted(scopes), "entries": entries, "hash": digest(canonical(entries))}

    def current_config(self, fresh=True):
        configs = [e for e in self.data["events"] if e["kind"] == "configure"]
        if not configs:
            fail("configure required")
        event = configs[-1]
        if fresh and not self.references_current(event["payload"]["sources"]):
            fail("configuration sources changed; explicit configure/readmission required")
        return event

    @staticmethod
    def target(config, kind, target):
        group = {"implementation": "tasks", "review": "reviews", "verification": "acceptance"}[kind]
        for item in config["spec"][group]:
            if item["id"] == target:
                return item
        fail(f"unknown {kind} target: {target}", "unknown_target")

    def target_scope(self, config, kind, target):
        item = self.target(config, kind, target)
        tasks = [target] if kind == "implementation" else item["tasks"]
        values = []
        for task in config["spec"]["tasks"]:
            if task["id"] in tasks:
                values += task["scope"]
        values += item.get("context_scope", [])
        return sorted(set(values))

    @staticmethod
    def descriptor(config, kind, target):
        item = Engine.target(config, kind, target)
        task_ids = [target] if kind == "implementation" else item["tasks"]
        return {"item": item, "tasks": [t for t in config["spec"]["tasks"] if t["id"] in task_ids]}

    def configure(self, request, op):
        shape(request, ("schema_version", "contract_version", "actor", "skill_revision", "plan", "authorization",
                        "mapping_reason", "tasks", "reviews", "acceptance"), ("design", "reuse"))
        version(request)
        actor(request["actor"])
        text(request["skill_revision"], "skill_revision")
        text(request["mapping_reason"], "mapping_reason")
        with self.locked():
            key, existing = self.duplicate(op, {"kind": "configure", "input": request})
            if existing:
                return existing
            self.active()
            shape(request["authorization"], ("path", "quote", "scope"), name="authorization")
            text(request["authorization"]["scope"], "authorization.scope")
            sources = {"plan": self.reference(request["plan"], True),
                       "authorization": {**self.reference({k: request["authorization"][k] for k in ("path", "quote")}, True),
                                         "scope": request["authorization"]["scope"]}}
            if "design" in request:
                sources["design"] = self.reference(request["design"], True)
            spec = {k: request[k] for k in ("tasks", "reviews", "acceptance")}
            self.validate_spec(spec)
            payload = {"sources": sources, "spec": spec, "actor": request["actor"],
                       "skill_revision": request["skill_revision"], "contract_version": 1,
                       "mapping_reason": request["mapping_reason"], "reused": [], "resolution_history": []}
            reuse = request.get("reuse", [])
            if not isinstance(reuse, list):
                fail("reuse must be array")
            old_config = self.current_config(False) if any(e["kind"] == "configure" for e in self.data["events"]) else None
            if old_config:
                # Finding identities outlive individual admissions. Removing an
                # owner would make its findings impossible to resolve safely.
                for finding in self.issues(old_config).values():
                    try:
                        owner = self.target(payload, finding["owner_kind"], finding["owner_target"])
                    except DeliveryError:
                        fail(f"cannot remove finding owner {finding['owner_kind']}:{finding['owner_target']}; preserve stable IDs and resolve findings there, or start a linked new work item")
                    covered = {owner["id"]} if finding["owner_kind"] == "implementation" else set(owner["tasks"])
                    if not set(finding["tasks"]) <= covered:
                        fail("cannot remove finding task coverage from its stable owner; preserve IDs for re-review")
            seen = set()
            for mapping in reuse:
                shape(mapping, ("operation_id", "reason"), name="reuse")
                text(mapping["reason"], "reuse.reason")
                source = next((e for e in reversed(self.data["events"]) if e["op"] == mapping["operation_id"] and e["kind"] == "record"), None)
                if not source or not old_config:
                    fail("reuse requires an existing record")
                record = source["payload"]
                identity = (record["kind"], record["target"])
                latest = self.records(old_config).get(identity)
                if not latest or latest[0] != source["op"]:
                    fail("reuse must select the latest admitted result for its target; do not bypass later findings or failures")
                if identity in seen:
                    fail("duplicate reused target")
                seen.add(identity)
                prior_config = next(e for e in self.data["events"] if e["op"] == record["config_op"] and e["kind"] == "configure")
                if self.descriptor(prior_config["payload"], *identity) != self.descriptor(payload, *identity):
                    fail("changed task/target contract cannot reuse a result")
                if not self.record_current(record, prior_config, ignore_config=True):
                    fail("stale product/report/evidence cannot be readmitted")
                # Explicit rebinding only; originals remain untouched and inspectable.
                copy = dict(record)
                copy["config_op"] = op
                copy["readmitted_from"] = source["op"]
                copy["readmission_reason"] = mapping["reason"]
                payload["reused"].append({"op": source["op"], "record": copy})
                candidates = [(e["op"], e["payload"]) for e in self.data["events"] if e["kind"] == "record"]
                candidates += [(e["op"], e["record"]) for e in prior_config["payload"].get("resolution_history", [])]
                for history_op, history in candidates:
                    if history["kind"] == identity[0] and history["target"] == identity[1] and history.get("resolutions") and self.record_current(history, prior_config, ignore_config=True):
                        # Carry only the resolved-finding evidence of explicitly
                        # readmitted unchanged targets, not unrelated old reports.
                        history_config = next(e for e in self.data["events"] if e["op"] == history["config_op"] and e["kind"] == "configure")
                        if self.descriptor(history_config["payload"], *identity) == self.descriptor(payload, *identity):
                            rebound = {**history, "config_op": op, "readmission_reason": mapping["reason"]}
                            payload["resolution_history"].append({"op": history_op, "record": rebound})
            return self.append("configure", op, key, payload)

    def validate_spec(self, spec):
        for group in ("tasks", "reviews", "acceptance"):
            if not isinstance(spec[group], list) or not spec[group]:
                fail(f"{group}: nonempty array required")
        ids = {}
        for group in spec:
            ids[group] = []
            for item in spec[group]:
                if not isinstance(item, dict):
                    fail("spec item must be object")
                ident = text(item.get("id"), "id")
                if ident in ids[group]:
                    fail(f"duplicate {group} id")
                ids[group].append(ident)
        for task in spec["tasks"]:
            shape(task, ("id", "scope", "depends"), name="task")
            self.scopes(task["scope"])
        for review in spec["reviews"]:
            shape(review, ("id", "tasks", "whole"), ("context_scope", "depends"), name="review")
            if type(review["whole"]) is not bool:
                fail("whole must be bool")
        for ac in spec["acceptance"]:
            shape(ac, ("id", "tasks", "required", "method", "criteria", "environment"),
                  ("command", "waivable", "context_scope", "depends"), name="acceptance")
            if type(ac["required"]) is not bool or type(ac.get("waivable", False)) is not bool:
                fail("required and waivable must be bool")
            text(ac["criteria"], "criteria")
            text(ac["environment"], "environment")
            if ac["method"] not in ("command", "manual", "inspection"):
                fail("unknown verification method")
            if ac["method"] == "command":
                strings(ac.get("command"), "command", unique=False)
            elif "command" in ac:
                fail("command allowed only for command method")
        for group in ("reviews", "acceptance"):
            for item in spec[group]:
                strings(item["tasks"], "tasks")
                if not set(item["tasks"]) <= set(ids["tasks"]):
                    fail("unknown task in coverage")
                if "context_scope" in item:
                    strings(item["context_scope"], "context_scope", nonempty=False)
                    if item["context_scope"]:
                        self.scopes(item["context_scope"])
        all_tasks = set(ids["tasks"])
        if not any(r["whole"] and set(r["tasks"]) == all_tasks for r in spec["reviews"]):
            fail("whole review must cover every task")
        for task in all_tasks:
            if not any(task in r["tasks"] for r in spec["reviews"]):
                fail("task missing review coverage")
            if not any(task in a["tasks"] and a["required"] for a in spec["acceptance"]):
                fail("task missing required acceptance coverage")
        names = {"implementation": "tasks", "review": "reviews", "acceptance": "acceptance"}
        graph = {}
        for kind, group in names.items():
            for item in spec[group]:
                dependencies = item.get("depends", [])
                if not isinstance(dependencies, list):
                    fail("depends must be array")
                node = (kind, item["id"])
                graph[node] = []
                if kind != "implementation":
                    graph[node] += [("implementation", t) for t in item["tasks"]]
                for dep in dependencies:
                    shape(dep, ("kind", "id"), name="dependency")
                    if dep["kind"] not in names or dep["id"] not in ids[names[dep["kind"]]]:
                        fail("unknown dependency")
                    graph[node].append((dep["kind"], dep["id"]))
        visiting, visited = set(), set()

        def visit(node):
            if node in visiting:
                fail("joint implementation/review/acceptance dependency cycle")
            if node in visited:
                return
            visiting.add(node)
            for child in graph[node]:
                visit(child)
            visiting.remove(node)
            visited.add(node)

        for node in graph:
            visit(node)

    def records(self, config):
        result = {}
        for item in config["payload"].get("reused", []):
            result[(item["record"]["kind"], item["record"]["target"])] = (item["op"], item["record"])
        for event in self.data["events"]:
            if event["kind"] == "record" and event["payload"]["config_op"] == config["op"]:
                record = event["payload"]
                result[(record["kind"], record["target"])] = (event["op"], record)
        return result

    def record_current(self, record, config, ignore_config=False):
        if not ignore_config and (record["config_op"] != config["op"] or not self.references_current(config["payload"]["sources"])):
            return False
        if not self.references_current(record["references"]):
            return False
        try:
            current = self.snapshot(record["snapshot"]["scopes"])
        except (DeliveryError, OSError):
            return False
        return current["hash"] == record["snapshot"]["hash"]

    def issues(self, config):
        issues = {}
        candidates = [(e["op"], e["payload"]) for e in self.data["events"] if e["kind"] == "record"]
        candidates += [(e["op"], e["record"]) for e in config["payload"].get("reused", [])]
        candidates += [(e["op"], e["record"]) for e in config["payload"].get("resolution_history", [])]
        valid_ops = {op for op, record in candidates if self.record_current(record, config)}
        for event in self.data["events"]:
            if event["kind"] != "record":
                continue
            record = event["payload"]
            for item in record.get("issues", []):
                if item["id"] not in issues:
                    issues[item["id"]] = {**item, "owner_kind": record["kind"], "owner_target": record["target"],
                                           "origin_op": event["op"], "status": "open"}
            for resolution in record.get("resolutions", []):
                if event["op"] in valid_ops and resolution["id"] in issues:
                    issues[resolution["id"]]["status"] = "resolved"
                    issues[resolution["id"]]["resolution_op"] = event["op"]
        return issues

    def state(self):
        config = self.current_config(False)
        fresh = self.references_current(config["payload"]["sources"])
        records = self.records(config)
        issues = self.issues(config)
        result = {"configuration": "current" if fresh else "stale", "config_operation": config["op"],
                  "implementation": {}, "review": {}, "verification": {}, "issues": issues}
        for kind, group in (("implementation", "tasks"), ("review", "reviews"), ("verification", "acceptance")):
            for item in config["payload"]["spec"][group]:
                pair = records.get((kind, item["id"]))
                status = "pending"
                if pair:
                    record = pair[1]
                    if not self.record_current(record, config):
                        status = "stale"
                    elif kind == "review":
                        verdicts = record["result"]
                        status = "passed" if all(v == "passed" for v in verdicts.values()) else ("failed" if "failed" in verdicts.values() else "unknown")
                    else:
                        status = record["result"]
                    if status == "passed" and any(i["blocking"] and i["status"] == "open" and i["owner_kind"] == kind and i["owner_target"] == item["id"] for i in issues.values()):
                        status = "blocked"
                result[kind][item["id"]] = {"status": status, "operation_id": pair[0] if pair else None}
        # A current review is not independent if any current implementation was
        # authored by its reviewer, even when implementation was recorded later.
        for item in config["payload"]["spec"]["reviews"]:
            pair = records.get(("review", item["id"]))
            if pair and result["review"][item["id"]]["status"] == "passed":
                if not self.independent(pair[1]["actor"], item["tasks"]):
                    result["review"][item["id"]]["status"] = "blocked"
        # Propagate stale/pending prerequisite gates, not just content fingerprints.
        changed = True
        while changed:
            changed = False
            for kind, group in (("implementation", "tasks"), ("review", "reviews"), ("verification", "acceptance")):
                for item in config["payload"]["spec"][group]:
                    current = result[kind][item["id"]]
                    if current["status"] == "passed" and not self.dependencies_pass(item, kind, result):
                        current["status"] = "blocked"
                        changed = True
        lifecycle = "active"
        closure = None
        for event in self.data["events"]:
            if event["kind"] == "close":
                lifecycle, closure = "closed", event["payload"]
            elif event["kind"] == "reopen":
                lifecycle, closure = "active", None
        result["lifecycle"] = lifecycle
        result["closure"] = closure
        runs = {}
        for event in self.data["events"]:
            if event["kind"] in ("run-started", "run"):
                runs[event["op"]] = {"status": "incomplete" if event["kind"] == "run-started" else "finished",
                                     "acceptance": event["payload"]["acceptance"],
                                     "exit_code": event["payload"].get("exit_code"),
                                     "timed_out": event["payload"].get("timed_out", False)}
        result["runs"] = runs
        return result

    @staticmethod
    def dependencies_pass(item, kind, state):
        deps = list(item.get("depends", []))
        if kind != "implementation":
            deps += [{"kind": "implementation", "id": t} for t in item["tasks"]]
        for dep in deps:
            group = "verification" if dep["kind"] == "acceptance" else dep["kind"]
            if state[group][dep["id"]]["status"] != "passed":
                return False
        return True

    def independent(self, reviewer, tasks):
        for event in self.data["events"]:
            if event["kind"] == "record":
                record = event["payload"]
                if record["kind"] == "implementation" and record["target"] in tasks:
                    if reviewer["id"] == record["actor"]["id"] or reviewer["context"] == record["actor"]["context"]:
                        return False
        return True

    def prepare_record(self, request, config=None):
        shape(request, ("schema_version", "contract_version", "skill_revision", "kind", "target", "actor", "report", "result", "summary", "evidence"),
              ("issues", "resolutions", "run_operation", "confirmation", "supersedes", "reason",
               "review_commit", "base_commit"))
        version(request)
        actor(request["actor"])
        text(request["skill_revision"], "skill_revision")
        text(request["summary"], "summary")
        if request["kind"] not in ("implementation", "review", "verification"):
            fail("unknown record kind")
        if not isinstance(request["evidence"], list) or not request["evidence"]:
            fail("nonempty evidence array required")
        self.active()
        config = config or self.current_config()
        kind, target = request["kind"], request["target"]
        item = self.target(config["payload"], kind, target)
        state = self.state()
        if not self.dependencies_pass(item, kind, state):
            fail("prerequisite gate is not passed", "dependency_not_ready")
        references = {"report": self.reference(request["report"]), "evidence": [self.reference(e) for e in request["evidence"]]}
        snapshot = self.snapshot(self.target_scope(config["payload"], kind, target))
        result = request["result"]
        if kind == "review":
            shape(result, ("spec", "quality"), name="review result")
            if any(v not in ("passed", "failed", "unknown") for v in result.values()):
                fail("invalid review result")
            if not self.independent(request["actor"], item["tasks"]):
                fail("reviewer id/context participated in implementation")
        elif result not in ("passed", "failed", "unknown"):
            fail("invalid result")
        pair = self.records(config).get((kind, target))
        if pair and pair[1]["result"] != result:
            if request.get("supersedes") != pair[0] or not request.get("reason", "").strip():
                fail("changed conclusion requires supersedes and reason")
        if kind == "verification":
            self.validate_verification(request, item, config, snapshot, references)
        elif "run_operation" in request or "confirmation" in request:
            fail("run_operation/confirmation are verification-only")
        issues = request.get("issues", [])
        resolutions = request.get("resolutions", [])
        if not isinstance(issues, list) or not isinstance(resolutions, list):
            fail("issues and resolutions must be arrays")
        existing_issues = self.issues(config)
        known_ids = set(existing_issues)
        for issue in issues:
            shape(issue, ("id", "summary", "severity", "blocking", "tasks"), name="issue")
            for field in ("id", "summary", "severity"):
                text(issue[field], f"issue.{field}")
            if type(issue["blocking"]) is not bool:
                fail("issue.blocking must be bool")
            strings(issue["tasks"], "issue.tasks")
            covered = {target} if kind == "implementation" else set(item["tasks"])
            if not set(issue["tasks"]) <= covered:
                fail("issue tasks outside record scope")
            if issue["id"] in known_ids:
                fail("issue id already exists; reference original and add explicit resolution")
            known_ids.add(issue["id"])
        resolution_ids = set()
        for resolution in resolutions:
            shape(resolution, ("id", "reason", "evidence"), name="resolution")
            text(resolution["reason"], "resolution.reason")
            original = existing_issues.get(resolution["id"])
            if not original or original["owner_kind"] != kind or original["owner_target"] != target:
                fail("resolution must be by original finding capability and target")
            if resolution["id"] in resolution_ids:
                fail("duplicate resolution")
            resolution_ids.add(resolution["id"])
            if not isinstance(resolution["evidence"], list) or not resolution["evidence"]:
                fail("resolution requires evidence")
            references.setdefault("resolutions", []).append({"id": resolution["id"], "evidence": [self.reference(e) for e in resolution["evidence"]]})
        passed = all(v == "passed" for v in result.values()) if isinstance(result, dict) else result == "passed"
        blockers = [i for i in existing_issues.values() if i["blocking"] and i["status"] == "open" and i["owner_kind"] == kind and i["owner_target"] == target and i["id"] not in resolution_ids]
        if passed and (blockers or any(i["blocking"] for i in issues)):
            fail("passed result cannot hide unresolved blocking issues")
        payload = {k: v for k, v in request.items() if k not in ("report", "evidence", "confirmation")}
        payload.update({"config_op": config["op"], "snapshot": snapshot, "references": references})
        return payload

    def record(self, request, op):
        with self.locked():
            key, existing = self.duplicate(op, {"kind": "record", "input": request})
            if existing:
                return existing
            payload = self.prepare_record(request)
            return self.append("record", op, key, payload)

    def validate_verification(self, request, item, config, snapshot, references):
        result = request["result"]
        if item["method"] == "command":
            if "confirmation" in request:
                fail("confirmation only for manual verification")
            run = next((e for e in reversed(self.data["events"]) if e["op"] == request.get("run_operation") and e["kind"] == "run"), None)
            if not run:
                if result == "unknown" and "run_operation" not in request:
                    return
                fail("command verification needs an actual completed run")
            payload = run["payload"]
            if payload["acceptance"] != item["id"] or payload["command"] != item["command"] or payload["config_op"] != config["op"]:
                fail("run belongs to another command, acceptance, or configuration")
            if payload["before"]["hash"] != payload["after"]["hash"] or payload["after"]["hash"] != snapshot["hash"] or not payload["sources_stable"]:
                fail("run changed product/sources or belongs to stale product")
            if result == "passed" and (payload["exit_code"] != 0 or payload["timed_out"]):
                fail("nonzero/timed-out run cannot support passed verification")
        elif item["method"] == "manual":
            if "run_operation" in request:
                fail("run_operation only for command verification")
            if result == "passed":
                confirmation = request.get("confirmation")
                shape(confirmation, ("path", "quote", "acceptance", "by", "role"), name="manual confirmation")
                if confirmation["role"] != "human" or confirmation["acceptance"] != item["id"]:
                    fail("item-specific human confirmation required")
                text(confirmation["by"], "confirmation.by")
                references["confirmation"] = {**self.reference({k: confirmation[k] for k in ("path", "quote")}, True),
                                              "acceptance": confirmation["acceptance"], "by": confirmation["by"], "role": "human"}
            elif "confirmation" in request:
                fail("confirmation is used only for manual passed result")
        elif "run_operation" in request or "confirmation" in request:
            fail("inspection does not accept run_operation or confirmation")

    def run(self, acceptance, who, timeout, op):
        actor(who)
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0 or timeout > 86400:
            fail("timeout must be 0 < seconds <= 86400")
        request = {"kind": "run", "acceptance": acceptance, "actor": who, "timeout": timeout}
        with self.locked():
            key, existing = self.duplicate(op, request)
            if existing:
                return existing
            self.active()
            config = self.current_config()
            item = self.target(config["payload"], "verification", acceptance)
            if item["method"] != "command":
                fail("run requires command method")
            if not self.dependencies_pass(item, "verification", self.state()):
                fail("run prerequisites are not passed")
            scopes = self.target_scope(config["payload"], "verification", acceptance)
            before = self.snapshot(scopes)
            self.append("run-started", op, key, {"acceptance": acceptance, "command": item["command"],
                                               "actor": who, "config_op": config["op"], "before": before})
            timed_out, error, code = False, None, None
            stdout, stderr = b"", b""
            try:
                process = subprocess.Popen(item["command"], cwd=self.project, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE, start_new_session=True)
                try:
                    stdout, stderr = process.communicate(timeout=timeout)
                except subprocess.TimeoutExpired:
                    timed_out = True
                    os.killpg(process.pid, signal.SIGKILL)
                    stdout, stderr = process.communicate()
                code = process.returncode
            except OSError as exc:
                error = str(exc)
                stderr = error.encode()
            try:
                after = self.snapshot(scopes)
            except (DeliveryError, OSError) as exc:
                after = {"hash": None, "scopes": scopes, "error": str(exc)}
            return self.append("run", op, key, {"acceptance": acceptance, "command": item["command"],
                                               "actor": who, "config_op": config["op"], "before": before, "after": after,
                                               "sources_stable": self.references_current(config["payload"]["sources"]),
                                               "exit_code": code, "timed_out": timed_out, "error": error,
                                               "stdout": self.blob(stdout), "stderr": self.blob(stderr)})

    def prepare_close(self, request):
        """Validate and materialize a close without appending it.

        `check --preclose` reuses this exact judgement so the precheck and the
        actual close cannot disagree about exceptions or required evidence.
        """
        shape(request, ("schema_version", "contract_version", "actor", "mode", "summary", "report", "exceptions"))
        version(request)
        actor(request["actor"])
        text(request["summary"], "summary")
        if request["mode"] not in ("complete", "limited"):
            fail("close mode must be complete or limited")
        if not isinstance(request["exceptions"], list):
            fail("exceptions must be array")
        self.active()
        config = self.current_config()
        state = self.state()
        if any(v["status"] != "passed" for group in ("implementation", "review") for v in state[group].values()):
            fail("all implementations and independent reviews must pass")
        exceptions = {}
        for exception in request["exceptions"]:
            shape(exception, ("acceptance", "scope", "risk", "authorization", "issues"), name="exception")
            target = exception["acceptance"]
            if target in exceptions:
                fail("duplicate acceptance exception")
            item = self.target(config["payload"], "verification", target)
            if not item.get("waivable", False):
                fail("non-waivable criterion")
            if state["verification"][target]["status"] != "failed":
                fail("only currently evidenced failed criteria can be excepted; not unknown/stale/pending")
            text(exception["scope"], "exception.scope")
            text(exception["risk"], "exception.risk")
            strings(exception["issues"], "exception.issues", nonempty=False)
            auth = exception["authorization"]
            shape(auth, ("path", "quote", "by", "role"), name="exception authorization")
            if auth["role"] != "human":
                fail("exception requires actual human authorization")
            text(auth["by"], "authorization.by")
            reference = {**self.reference({k: auth[k] for k in ("path", "quote")}, True), "by": auth["by"], "role": "human"}
            for issue_id in exception["issues"]:
                issue = state["issues"].get(issue_id)
                if not issue or issue["owner_kind"] != "verification" or issue["owner_target"] != target:
                    fail("exception issue must belong to the excepted verification")
            exceptions[target] = {**exception, "authorization": reference,
                                  "verification_operation": state["verification"][target]["operation_id"]}
        if request["mode"] == "complete" and exceptions:
            fail("complete cannot have exceptions")
        if request["mode"] == "limited" and not exceptions:
            fail("limited requires explicit exceptions")
        for item in config["payload"]["spec"]["acceptance"]:
            if item["required"] and state["verification"][item["id"]]["status"] != "passed" and item["id"] not in exceptions:
                fail(f"required acceptance is not passed: {item['id']}")
        allowed_issues = {issue for exception in exceptions.values() for issue in exception["issues"]}
        if any(i["blocking"] and i["status"] == "open" and i["id"] not in allowed_issues for i in state["issues"].values()):
            fail("unresolved blocking issue")
        report = self.reference(request["report"])
        return {"mode": request["mode"], "actor": request["actor"], "summary": request["summary"],
                "report": report, "config_op": config["op"], "exceptions": list(exceptions.values()), "state": state}

    def close(self, request, op):
        with self.locked():
            key, existing = self.duplicate(op, {"kind": "close", "input": request})
            if existing:
                return existing
            payload = self.prepare_close(request)
            return self.append("close", op, key, payload)

    def reopen(self, reason, op):
        text(reason, "reason")
        with self.locked():
            key, existing = self.duplicate(op, {"kind": "reopen", "reason": reason})
            if existing:
                return existing
            if self.state()["lifecycle"] != "closed":
                fail("only closed work can be reopened")
            return self.append("reopen", op, key, {"reason": reason})

    def inspect(self, command):
        with self.locked():
            state = self.state()
            if command == "status":
                return state
            if command == "check":
                return {"journal_integrity": "passed", "configuration": state["configuration"],
                        "lifecycle": state["lifecycle"],
                        "note": "Mechanical integrity only; does not establish semantic truth or readiness."}
            config = self.current_config(False)
            ready, blocked = [], []
            for kind, group in (("implementation", "tasks"), ("review", "reviews"), ("verification", "acceptance")):
                for item in config["payload"]["spec"][group]:
                    status = state[kind][item["id"]]["status"]
                    if status == "passed":
                        continue
                    candidate = {"kind": kind, "target": item["id"], "status": status}
                    if state["configuration"] == "current" and state["lifecycle"] == "active" and self.dependencies_pass(item, kind, state):
                        ready.append(candidate)
                    else:
                        blocked.append(candidate)
            return {"ready": ready, "blocked": blocked, "note": "Ready means mechanically eligible; inspect human-readable requirements before acting."}


def read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        fail(f"cannot read input JSON: {exc}")


WRITE_COMMANDS = {"init", "configure", "record", "run", "close", "reopen", "gate", "impact",
                  "source-update", "resource", "attempt", "resolve-run", "enable-fix", "verify", "verify-batch"}
REJECTED_LIMIT = 10 * 1024 * 1024


def read_rejections(path):
    records, bad = [], []
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        return records, bad
    for number, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except ValueError:
            bad.append(number)
            continue
        if not isinstance(value, dict) or "id" not in value or "op" not in value:
            bad.append(number)
            continue
        records.append(value)
    return records, bad


def redact_rejection(message, project=None):
    message = str(message)
    if project:
        root = str(project).rstrip("/")
        message = message.replace(root + "/", "").replace(root, ".")
    message = re.sub(
        r"(?i)([\"']?(?:token|password|passwd|secret|api[_-]?key)[\"']?\s*[:=]\s*)"
        r"(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)",
        r"\1<redacted>", message)
    return message[:500]


def record_rejection(work, command, op, actor_value, request, exc):
    """Append one rejection line without changing the command outcome."""
    runtime = Path(work) / "runtime"
    if runtime.is_symlink() or not runtime.is_dir():
        return None
    path = runtime / "rejected.jsonl"
    if path.is_symlink():
        print("rejected log is a symlink; refusal not recorded", file=sys.stderr)
        return None
    project = None
    try:
        project = json.loads((runtime / "journal.json").read_text()).get("project")
    except (OSError, ValueError):
        pass
    request_hash = digest(canonical(request)) if request is not None else digest(b"")
    code = "io_error" if isinstance(exc, OSError) else getattr(exc, "code", "invalid_request")
    seed = {"command": command, "op": op, "request_hash": request_hash, "error_code": code}
    identity = digest(canonical(seed))
    lock_path = runtime / "lock"
    if lock_path.is_symlink():
        print("rejected log lock is a symlink; refusal not recorded", file=sys.stderr)
        return None
    try:
        with lock_path.open("a+b") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                try:
                    records, bad = read_rejections(path)
                except OSError as exc:
                    print(f"rejected log read failed: {exc}", file=sys.stderr)
                    return None
                root, attempt = identity, 1
                for value in records:
                    if value.get("op") == op and value.get("request_hash") == request_hash and value.get("error_code") == code:
                        root = value.get("retry_of") or value.get("id") or identity
                        attempts = [v.get("attempt", 0) for v in records if (v.get("id") == root or v.get("retry_of") == root)]
                        attempt = max(attempts or [0]) + 1
                        break
                record = {"id": identity, "at": now(), "command": command, "op": op,
                          "actor": actor_value if isinstance(actor_value, dict) else None,
                          "request_hash": request_hash, "error_code": code,
                          "error_message": redact_rejection(exc, project), "work": str(work),
                          "attempt": attempt, "retry_of": None if attempt == 1 else root}
                line = (json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n").encode()
                if path.exists() and path.stat().st_size >= REJECTED_LIMIT:
                    os.replace(path, path.with_name("rejected.jsonl.1"))
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
                try:
                    os.write(fd, line)
                    os.fsync(fd)
                finally:
                    os.close(fd)
                dfd = os.open(runtime, os.O_RDONLY)
                try:
                    os.fsync(dfd)
                finally:
                    os.close(dfd)
                return record
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
    except OSError as log_error:
        print(f"rejected log write failed: {log_error}", file=sys.stderr)
        return None


def render_markdown(value):
    """Render the same result object; no second readiness calculation."""
    lines = ["# Delivery 状态视图", ""]
    def render(item, depth=0):
        prefix = "  " * depth
        if isinstance(item, dict):
            for key, child in item.items():
                if isinstance(child, (dict, list)) and child:
                    lines.append(prefix + "- **" + str(key) + "**:")
                    render(child, depth + 1)
                else:
                    lines.append(prefix + "- **" + str(key) + "**: " + json.dumps(child, ensure_ascii=False))
        elif isinstance(item, list):
            for child in item:
                if isinstance(child, (dict, list)):
                    lines.append(prefix + "- 条目:")
                    render(child, depth + 1)
                else:
                    lines.append(prefix + "- " + str(child))
        else:
            lines.append(prefix + str(item))
    render(value)
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    read_only = {"status", "check", "next", "source", "brief", "preflight", "guard", "doctor"}
    with_input = {"configure", "record", "close", "gate", "impact", "source-update", "resource",
                  "attempt", "resolve-run", "enable-fix", "verify-batch"}
    for name in ("init", "configure", "record", "run", "status", "check", "next", "close", "reopen",
                 "gate", "impact", "source-update", "resource", "attempt", "resolve-run", "source",
                 "brief", "enable-fix", "preflight", "guard", "verify-batch", "doctor"):
        p = sub.add_parser(name)
        p.add_argument("--work", required=True)
        if name not in read_only:
            p.add_argument("--op", required=True)
        if name in with_input:
            p.add_argument("--input", required=True)
        if name == "init":
            p.add_argument("--project", required=True)
            p.add_argument("--title", required=True)
            p.add_argument("--contract-version", type=int, choices=(1, 2), default=1)
        if name in ("status", "check", "next", "source", "brief", "preflight", "guard", "doctor"):
            p.add_argument("--format", choices=("json", "markdown"), default="json")
        if name == "status":
            p.add_argument("--write-status", action="store_true")
        if name == "check":
            p.add_argument("--preclose", action="store_true")
            p.add_argument("--input")
        if name == "source":
            p.add_argument("--restore")
            p.add_argument("--destination")
        if name == "brief":
            p.add_argument("--kind", choices=("implementation", "review", "verification"), required=True)
            p.add_argument("--target", required=True)
        if name == "guard":
            p.add_argument("--kind", choices=("task", "review", "verification"), required=True)
            p.add_argument("--target", required=True)
            p.add_argument("--actor")
            p.add_argument("--context")
        if name == "preflight":
            p.add_argument("--project", required=True)
            p.add_argument("--high-yield-threshold", type=int, default=1000)
        if name == "run":
            p.add_argument("--acceptance", required=True)
            p.add_argument("--actor", required=True)
            p.add_argument("--context", required=True)
            p.add_argument("--timeout", type=float, default=60)
        if name == "reopen":
            p.add_argument("--reason", required=True)
    args = parser.parse_args(argv)
    request = None
    actor_value = None
    if args.command == "preflight":
        try:
            from delivery_monitor import preflight
            result = preflight(args.project, args.work, args.high_yield_threshold)
        except (DeliveryError, OSError, ValueError) as exc:
            print(json.dumps({"error": str(exc), "code": getattr(exc, "code", "invalid_request")},
                             ensure_ascii=False), file=sys.stderr)
            return 2
        if args.format == "markdown":
            print(render_markdown(result))
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    try:
        contract = args.contract_version if args.command == "init" else None
        journal = Path(args.work) / "runtime" / "journal.json"
        if journal.exists():
            stored = read_json(journal)
            existing_contract = stored["events"][0]["payload"].get("contract_version", 1)
            if contract is not None and contract != existing_contract:
                fail("init contract does not match existing work")
            contract = existing_contract
        if contract not in (1, 2):
            fail("unsupported work contract or work not initialized")
        if args.command == "init":
            request = {"kind": "init", "project": args.project, "title": args.title}
        elif args.command in with_input:
            request = read_json(args.input)
        elif args.command == "run":
            request = {"kind": "run", "acceptance": args.acceptance, "timeout": args.timeout,
                       "actor": {"id": args.actor, "context": args.context}}
        elif args.command == "reopen":
            request = {"kind": "reopen", "reason": args.reason}
        elif args.command == "check" and args.input:
            request = read_json(args.input)
        if isinstance(request, dict):
            actor_value = request.get("actor")
        if contract == 2:
            # Adding scripts locally is sufficient for the standalone CLI; tests
            # importing this file by spec retain the original v1 class identity.
            scripts = str(Path(__file__).resolve().parent)
            if scripts not in sys.path:
                sys.path.insert(0, scripts)
            from delivery_v2 import EngineV2
            engine = EngineV2(args.work)
        else:
            engine = Engine(args.work)
        extras = {"gate", "impact", "source-update", "resource", "attempt", "resolve-run", "source",
                  "brief", "enable-fix", "guard", "verify-batch", "doctor"}
        if args.command in extras and contract != 2:
            fail("command requires explicit v2 work; v1 is not silently upgraded")
        if args.command == "check" and args.preclose and contract != 2:
            fail("command requires explicit v2 work; v1 is not silently upgraded")
        if args.command == "status" and args.write_status and contract != 2:
            fail("command requires explicit v2 work; v1 is not silently upgraded")
        status_code = 0
        if args.command == "init":
            result = engine.init(args.project, args.title, args.op)
        elif args.command == "verify-batch":
            result = engine.verify_batch(request, args.op)
        elif args.command in ("configure", "record", "close", "gate", "impact", "source-update", "resource", "attempt", "resolve-run", "enable-fix"):
            result = getattr(engine, args.command.replace("-", "_"))(request, args.op)
        elif args.command == "run":
            result = engine.run(args.acceptance, {"id": args.actor, "context": args.context}, args.timeout, args.op)
        elif args.command == "reopen":
            result = engine.reopen(args.reason, args.op)
        elif args.command == "source":
            result = engine.source(args.restore, args.destination)
        elif args.command == "brief":
            result = engine.brief(args.kind, args.target)
        elif args.command == "guard":
            who = {"id": args.actor, "context": args.context} if args.actor and args.context else None
            result = engine.guard(args.kind, args.target, who)
            status_code = 0 if result["ready"] else 1
        elif args.command == "doctor":
            result = engine.doctor()
        elif args.command == "status" and args.write_status:
            result = engine.write_status()
        elif args.command == "check" and args.preclose:
            result = engine.preclose(request)
            status_code = 0 if result["ready"] else 1
        else:
            result = engine.inspect(args.command)
            if contract == 1:
                result["contract_version"] = 1
        warnings = getattr(engine, "last_warnings", None)
        if warnings:
            print(json.dumps({"warnings": warnings}, ensure_ascii=False), file=sys.stderr)
        if getattr(args, "format", "json") == "markdown":
            print(render_markdown(result))
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return status_code
    except (DeliveryError, OSError, ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
        if args.command in WRITE_COMMANDS:
            logged = exc if isinstance(exc, (DeliveryError, OSError)) else DeliveryError(str(exc), "internal_error")
            record_rejection(args.work, args.command, getattr(args, "op", None) or "", actor_value, request, logged)
        print(json.dumps({"error": str(exc), "code": getattr(exc, "code", "invalid_request")}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
