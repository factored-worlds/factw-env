"""Closed, in-memory linking of proposed State Language documents."""

import json
from copy import deepcopy
from dataclasses import replace
from uuid import uuid4

import smsl

from .inputs import decode_json_bytes


class LinkedDocuments:
    def __init__(self, candidate: dict):
        self._documents = {item["id"]: deepcopy(item) for item in candidate["documents"]}
        if len(self._documents) != len(candidate["documents"]):
            raise ValueError("Document IDs must be unique")
        self._bindings = {identifier: {} for identifier in self._documents}
        for item in candidate["import_bindings"]:
            origin, name, target = (
                item["from_document"],
                item["import_name"],
                item["target_document"],
            )
            if origin not in self._documents or target not in self._documents:
                raise ValueError("An import binding names an absent document")
            if name in self._bindings[origin]:
                raise ValueError("An import name must have exactly one binding")
            self._bindings[origin][name] = target
        self._reject_cycles()
        self.models = {}
        self.executions = {}
        self.systems = {}
        self.applications = {}
        self.canonical = {}
        self._sources = {}
        self._modules = {}
        for identifier, item in self._documents.items():
            if item["serialization"] == "smsl_json":
                decode_json_bytes(item["source"].encode("utf-8"))
            role = item["role"]
            if role in {"model", "abstraction"}:
                module = smsl.decode_module(item["source"], format=self._format(item))
                self._modules[identifier] = module
                self._imports(
                    identifier, {entry.source for entry in module.imports}, {"model", "abstraction"}
                )
                module = replace(
                    module,
                    imports=tuple(
                        replace(entry, source=self._bindings[identifier][entry.source])
                        for entry in module.imports
                    ),
                )
                self._sources[identifier] = smsl.Source(
                    smsl.encode_module(module, format="json"), "json"
                )
            elif role == "execution":
                self._imports(identifier, set(), set())
                execution = smsl.ExecutionDefinition.loads(
                    item["source"], format=self._format(item)
                )
                self.executions[identifier] = execution
                self.canonical[identifier] = execution.to_dict()
            elif role == "system":
                definition = smsl.SystemDefinition.loads(
                    item["source"], format=self._format(item)
                ).to_dict()
                self._imports(identifier, set(definition["imports"]), {"system"})
                definition["imports"] = [
                    self._bindings[identifier][name] for name in definition["imports"]
                ]
                self._sources[identifier] = smsl.Source(json.dumps(definition), "json")
            elif role != "application":
                raise ValueError(f"Unsupported document role: {role}")
        for identifier, item in self._documents.items():
            role = item["role"]
            if role in {"model", "abstraction"}:
                source = self._sources[identifier]
                machine = (
                    smsl.link_sources(identifier, self._source_closure(identifier))
                    if self._bindings[identifier]
                    else smsl.loads(source.text, format=source.format)
                )
                self.models[identifier] = machine
                self.canonical[identifier] = smsl.Definition.from_machine(machine).to_dict()
            elif role == "system":
                system = smsl.SystemDefinition.link(identifier, self._source_closure(identifier))
                self.systems[identifier] = system
                self.canonical[identifier] = system.to_dict()
        self.model_aliases = {
            identifier: self._model_aliases(identifier) for identifier in self.models
        }
        for identifier, item in self._documents.items():
            if item["role"] == "application":
                self._application(identifier, item)
        self.instances = {}
        for item in candidate["world_instances"]:
            instance, document = item["instance_id"], item["model_document"]
            if instance in self.instances:
                raise ValueError("World instance IDs must be unique")
            if document not in self.models:
                raise ValueError("A world instance must reference a model document")
            self.instances[instance] = document
        self.context = smsl.Context(f"refinement_{uuid4().hex}", "player_observations", "captures")
        for identifier, execution in self.executions.items():
            document = execution.to_dict()
            for block in document["blocks"].values():
                if "instance" not in block or block["instance"] not in self.instances:
                    continue
                model = self.instances[block["instance"]]
                if "branch" in block:
                    block["branch"] = self._branch(model, block["branch"])
                if "expression" in block:
                    block["expression"] = self._expression(model, block["expression"])
                if "operations" in block:
                    block["operations"] = {
                        self._branch(model, branch): operation
                        for branch, operation in block["operations"].items()
                    }
            self.executions[identifier] = smsl.ExecutionDefinition(document)
            self.canonical[identifier] = document
            smsl.ExecutionSession(self.executions[identifier], self.world())

    @staticmethod
    def _format(document):
        return {"smsl_text": "smsl", "smsl_json": "json"}[document["serialization"]]

    def _reject_cycles(self):
        visited, active = set(), set()

        def visit(identifier):
            if identifier in active:
                raise ValueError("Cyclic document imports")
            if identifier in visited:
                return
            active.add(identifier)
            for target in self._bindings[identifier].values():
                visit(target)
            active.remove(identifier)
            visited.add(identifier)

        for identifier in self._documents:
            visit(identifier)

    def _imports(self, identifier, names, roles):
        bindings = self._bindings[identifier]
        if names != set(bindings):
            raise ValueError(f"Import bindings do not exactly match document {identifier}")
        if any(self._documents[target]["role"] not in roles for target in bindings.values()):
            raise ValueError(f"Wrong document kind imported by {identifier}")

    def _source_closure(self, identifier):
        sources = {}

        def collect(current):
            if current in sources:
                return
            if current not in self._sources:
                raise ValueError("This document kind cannot be imported here")
            sources[current] = self._sources[current]
            for target in self._bindings[current].values():
                collect(target)

        collect(identifier)
        return sources

    def _model_aliases(self, identifier):
        indices, exports = {}, {}

        def visit(current):
            if current in exports:
                return exports[current], {}
            index = len(indices)
            indices[current] = index
            module = self._modules[current]
            declarations = [
                *(item.name for item in module.branches),
                *(item.branch.name for item in module.templates),
                *(item.name for item in module.instances),
                *(item.name for item in module.domains),
            ]
            symbols = {
                name: name if index == 0 else f"module{index}.{name}" for name in declarations
            }
            for entry in sorted(
                module.imports, key=lambda entry: self._bindings[current][entry.source]
            ):
                target = self._bindings[current][entry.source]
                imported, _ = visit(target)
                for name in entry.names:
                    symbols[name.alias or name.name] = imported[name.name]
            exports[current] = {name: symbols[name] for name in module.exports}
            return exports[current], symbols

        _, symbols = visit(identifier)
        names = {branch["name"] for branch in self.canonical[identifier]["branches"]}
        return {name: target for name, target in symbols.items() if target in names}

    def _branch(self, identifier, branch):
        return self.model_aliases[identifier].get(branch, branch)

    def _expression(self, identifier, value):
        if isinstance(value, list):
            return [self._expression(identifier, item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {key: self._expression(identifier, item) for key, item in value.items()}
        if result.get("kind") == "read" and result.get("source") != "self":
            result["source"] = self._branch(identifier, result["source"])
        return result

    def _application(self, identifier, item):
        bindings = self._bindings[identifier]
        sources = {}
        for name, target in bindings.items():
            if self._documents[target]["role"] not in {"model", "abstraction", "system"}:
                raise ValueError("Applications can reference only model and system documents")
            for key, source in self._source_closure(target).items():
                if key in sources and sources[key] != source:
                    raise ValueError("Ambiguous application source name")
                sources[key] = source
            source = self._sources[target]
            if name in sources and sources[name] != source:
                raise ValueError("An application import shadows another source")
            sources[name] = source
        application = smsl.ApplicationDefinition.loads(
            item["source"], format=self._format(item), sources=sources
        )
        document = application.to_dict()
        references = [*document["models"].values(), document["system"]]
        if any(set(reference) != {"ref"} for reference in references):
            raise ValueError(
                "Candidate applications require explicit in-bundle model and system references"
            )
        self._imports(
            identifier,
            {reference["ref"] for reference in references},
            {"model", "abstraction", "system"},
        )
        for reference in document["models"].values():
            if bindings[reference["ref"]] not in self.models:
                raise ValueError("An application model reference must name a model")
        if bindings[document["system"]["ref"]] not in self.systems:
            raise ValueError("An application system reference must name a system")
        self.applications[identifier] = application
        self.canonical[identifier] = document

    @property
    def unsupported_execution_documents(self):
        """These parsed compositions have no admitted provider execution path."""
        return tuple((*self.systems, *self.applications))

    def world(self):
        world = smsl.World()
        for instance, document in self.instances.items():
            context = smsl.Context(
                f"{self.context.scope}/{instance}", self.context.subject, self.context.clock
            )
            world.spawn(instance, self.models[document], context)
        return world

    def _member(self, reference, collection):
        identifier, address = reference["document_id"], reference["address"]
        if identifier not in self.models or "." not in address:
            raise ValueError("A model reference must name an existing Branch.member")
        branch, name = address.rsplit(".", 1)
        branch = self._branch(identifier, branch)
        branches = self.canonical[identifier]["branches"]
        matches = [item for item in branches if item["name"] == branch]
        if len(matches) != 1:
            raise ValueError(f"Unknown model branch: {address}")
        members = [item for item in matches[0].get(collection, ()) if item["name"] == name]
        if len(members) != 1:
            raise ValueError(f"Unknown model {collection} reference: {address}")
        return identifier, branch, name, deepcopy(members[0])

    def predicate(self, reference):
        identifier, address = reference["document_id"], reference["address"]
        if identifier not in self.models or "." not in address:
            raise ValueError("A predicate must name an existing model Branch.member")
        branch, name = address.rsplit(".", 1)
        branch = self._branch(identifier, branch)
        branches = [
            item for item in self.canonical[identifier]["branches"] if item["name"] == branch
        ]
        if len(branches) != 1:
            raise ValueError(f"Unknown predicate branch: {address}")
        for kind in ("facts", "labels", "named_states"):
            for item in branches[0].get(kind, ()):
                if item["name"] == name:
                    if kind == "facts" and (
                        not item["values"]
                        or any(type(value) is not bool for value in item["values"])
                    ):
                        raise ValueError("A predicate reference must have a Boolean domain")
                    return {
                        "document_id": identifier,
                        "branch": branch,
                        "field": name,
                        "kind": kind,
                        "definition": deepcopy(item),
                    }
        raise ValueError(f"Unknown predicate: {address}")

    def action(self, reference):
        identifier, branch, name, definition = self._member(reference, "actions")
        return {
            "document_id": identifier,
            "branch": branch,
            "action": name,
            "definition": definition,
        }

    def abstraction(self, reference):
        identifier, branch, name, definition = self._member(reference, "abstractions")
        return {"document_id": identifier, "branch": branch, "name": name, "definition": definition}

    def execution_block(self, reference):
        identifier, address = reference["document_id"], reference["address"]
        if identifier not in self.executions or address.count("/") != 1:
            raise ValueError("An execution reference must name an existing ExecutionId/block_id")
        execution_id, block_id = address.split("/")
        document = self.executions[identifier].to_dict()
        if execution_id != document["id"] or block_id not in document["blocks"]:
            raise ValueError(f"Unknown execution block: {address}")
        return {
            "document_id": identifier,
            "execution_id": execution_id,
            "block_id": block_id,
            "definition": deepcopy(document["blocks"][block_id]),
        }

    def condition(self, record):
        identifier, branch = record["document_id"], record["branch"]
        if identifier not in self.models:
            raise ValueError("A condition must name a model document")
        source = (
            'smsl "0.2"; execution Check { initial check; '
            'block check: control.condition { input instance = "case"; '
            f"input branch = {json.dumps(branch)}; when {record['expression']}; "
            "} }"
        )
        execution = smsl.ExecutionDefinition.loads(source)
        document = execution.to_dict()
        expected = {
            "id": "Check",
            "root": "check",
            "version": 1,
            "blocks": {
                "check": {
                    "mechanism": "control.condition",
                    "instance": "case",
                    "branch": branch,
                    "expression": document["blocks"]["check"]["expression"],
                }
            },
        }
        if document != expected:
            raise ValueError("A condition record must contain only one expression")
        branch = self._branch(identifier, branch)
        expression = self._expression(identifier, expected["blocks"]["check"]["expression"])
        document["blocks"]["check"]["branch"] = branch
        document["blocks"]["check"]["expression"] = expression
        execution = smsl.ExecutionDefinition(document)
        world = smsl.World()
        world.spawn("case", self.models[identifier], self.context)
        smsl.ExecutionSession(execution, world)
        return {"document_id": identifier, "branch": branch, "expression": deepcopy(expression)}
