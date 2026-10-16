"""Opt-in implementation providers; ordinary v2 work retains its original protocol."""
from pathlib import Path
import re

from delivery import actor, fail, safe_path, shape, text


LOADED_SOURCE_BYTES = Path(__file__).read_bytes()


class ImplementationMixin:
    def fix_enabled(self):
        return any(e["kind"] == "implementation-protocol" for e in self.data["events"])

    def validate_implementation_protocol(self):
        enabled = False
        for event in self.data["events"]:
            payload = event["payload"]
            if event["kind"] == "implementation-protocol":
                version = payload.get("implementation_contract_version")
                if type(version) is not int or version != 1:
                    fail("unsupported implementation contract")
                enabled = True
            elif (event["kind"] == "configure" and "implementation_routes" in payload
                  or event["kind"] == "record" and ({"implementation_skill", "implementation_authors"} & payload.keys())):
                if not enabled:
                    fail("implementation extension requires prior explicit enable-fix")

    def enable_fix(self, request, op):
        self.validate_extra(request, ("implementation_contract_version", "reason"))
        if type(request["implementation_contract_version"]) is not int or request["implementation_contract_version"] != 1:
            fail("unsupported implementation contract")
        text(request["reason"], "reason")
        with self.locked():
            key, previous = self.duplicate(op, {"kind": "implementation-protocol", "input": request})
            if previous:
                return previous
            self.active()
            if self.fix_enabled():
                fail("implementation protocol already enabled; use original operation for retry")
            configs = [e for e in self.data["events"] if e["kind"] == "configure"]
            if configs:
                config = configs[-1]
                if any(d["name"] == "delivery-orchestrate" for d in self.source_drift(config)):
                    fail("first explicitly accept actual orchestrate source before enable-fix")
                pin = self.effective_pins(config)["delivery-orchestrate"]
            else:
                pin = self.collect_pin({"name": "delivery-orchestrate", "root": str(self.executing_root()), "contract_version": 2})
            return self.append("implementation-protocol", op, key,
                               {**request, "orchestrate_pin": pin["tree_hash"]})

    @staticmethod
    def implementation_route(config, target):
        payload = config.get("payload", config)
        return payload.get("implementation_routes", {}).get(target, {"skill": "delivery-implement"})

    def activity_skill(self, config, kind, target):
        if kind == "implementation":
            return self.implementation_route(config, target)["skill"]
        return {"review": "delivery-review", "verification": "delivery-verify"}.get(kind, "delivery-orchestrate")

    def validate_implementation_routes(self, payload, request):
        if "implementation_routes" not in request:
            prior = [e for e in self.data["events"] if e["kind"] == "configure"]
            if prior and prior[-1]["payload"].get("implementation_routes"):
                fail("explicitly preserve or replace implementation_routes on reconfiguration")
            return
        if not self.fix_enabled():
            fail("implementation_routes requires explicit enable-fix")
        routes = request["implementation_routes"]
        if not isinstance(routes, dict):
            fail("implementation_routes must be an object")
        identities = {}
        paths = {}
        for event in self.data["events"]:
            if event["kind"] == "configure":
                for route in event["payload"].get("implementation_routes", {}).values():
                    if route["skill"] == "delivery-fix":
                        identities[route["bug_id"]] = route["bug_path"]
                        paths[route["bug_path"]] = route["bug_id"]
        for target, route in routes.items():
            self.target(payload, "implementation", target)
            shape(route, ("skill",), ("bug_id", "bug_path"), name="implementation route")
            if route["skill"] == "delivery-implement":
                shape(route, ("skill",), name="implement route")
            elif route["skill"] == "delivery-fix":
                shape(route, ("skill", "bug_id", "bug_path"), name="fix route")
                text(route["bug_id"], "bug_id")
                root = safe_path(self.project, route["bug_path"], allow_missing=True)
                if root == self.project or root == self.runtime or self.runtime in root.parents or Path(route["bug_path"]).as_posix() != route["bug_path"]:
                    fail("bug_path must be a canonical project-relative record directory outside runtime")
                if route["bug_id"] in identities and identities[route["bug_id"]] != route["bug_path"]:
                    fail("same bug must retain its record directory")
                if route["bug_path"] in paths and paths[route["bug_path"]] != route["bug_id"]:
                    fail("different bug identities cannot share a record directory")
                identities[route["bug_id"]], paths[route["bug_path"]] = route["bug_path"], route["bug_id"]
            else:
                fail("unknown implementation skill")
        payload["implementation_routes"] = routes
        # Changing a provider or bug binding is a new implementation activity,
        # not a readmission of an older pass for the same target.
        for reuse in payload.get("reused", []):
            record = reuse["record"]
            original = next(e for e in self.data["events"] if e["op"] == reuse["op"])
            old = next(e for e in self.data["events"] if e["op"] == original["payload"]["config_op"])
            tasks = [record["target"]] if record["kind"] == "implementation" else self.target(payload, record["kind"], record["target"])["tasks"]
            if any(self.implementation_route(old, task) != self.implementation_route(payload, task) for task in tasks):
                fail("changed implementation route cannot reuse affected results")

    def implementation_authors(self, tasks=None):
        if tasks is not None:
            tasks = set(tasks)
            routes = [route for event in self.data["events"] if event["kind"] == "configure"
                      for route in event["payload"].get("implementation_routes", {}).items()]
            changed = True
            while changed:
                bugs = {route["bug_id"] for target, route in routes if target in tasks and route["skill"] == "delivery-fix"}
                linked = {target for target, route in routes if route["skill"] == "delivery-fix" and route["bug_id"] in bugs}
                changed = not linked <= tasks
                tasks.update(linked)
        values = []
        for event in self.data["events"]:
            record = event["payload"]
            if event["kind"] == "record" and record["kind"] == "implementation" and (tasks is None or record["target"] in tasks):
                values.extend([record["actor"], *record.get("implementation_authors", [])])
        return list({(v["id"], v["context"]): v for v in values}.values())

    def independent(self, reviewer, tasks):
        return not any(self.same_actor(reviewer, author) for author in self.implementation_authors(tasks))

    def validate_implementation_record(self, request, config):
        fields = {"implementation_skill", "implementation_authors"}
        extension = fields & request.keys()
        if request["kind"] != "implementation":
            if extension:
                fail("implementation provider fields are implementation-only")
            return
        route = self.implementation_route(config, request["target"])
        if extension and not self.fix_enabled():
            fail("implementation author/provider fields require explicit enable-fix")
        if route["skill"] == "delivery-fix" and not fields <= request.keys():
            fail("fix requires explicit implementation_skill and implementation_authors")
        if request.get("implementation_skill", "delivery-implement") != route["skill"]:
            fail("record implementation skill does not match admitted task route")
        if "implementation_authors" in request:
            authors = request["implementation_authors"]
            if not isinstance(authors, list) or not authors:
                fail("nonempty implementation_authors required")
            for author in authors:
                actor(author)
            if request["actor"] not in authors:
                fail("implementation_authors must include the actual record actor")
        if route["skill"] == "delivery-fix":
            path = safe_path(self.project, request["report"]["path"])
            root = safe_path(self.project, route["bug_path"])
            relative = path.relative_to(root) if path.is_relative_to(root) else None
            if relative is None or len(relative.parts) != 2 or relative.name != "fix.md" or not re.fullmatch(r"[0-9]{3,}", relative.parts[0]) or int(relative.parts[0]) < 1:
                fail("fix report must be bug_path/NNN/fix.md with a positive round")

    def implementation_record_fields(self, request, config):
        if request["kind"] != "implementation" or not ({"implementation_skill", "implementation_authors"} & request.keys()):
            return {}
        authors = self.implementation_authors([request["target"]]) + request.get("implementation_authors", [request["actor"]])
        return {"implementation_skill": self.implementation_route(config, request["target"])["skill"],
                "implementation_authors": list({(v["id"], v["context"]): v for v in authors}.values())}
