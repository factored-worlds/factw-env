"""Conservative Boolean correspondence checks over actual linked definitions."""

from ..bindings.button_primitives import ButtonBindings, ButtonCommand, validate_button_composition
from .boolean_proof import BooleanClosure


def _same(left, right, label):
    if left != right:
        raise ValueError(f"Inconsistent {label} correspondence")


def _reference(document, address):
    return {"document_id": document, "address": address}


def _members(definition, root):
    block = definition["blocks"][root]
    children = block.get("members", [block["member"]] if "member" in block else [])
    return {root}.union(*(_members(definition, child) for child in children))


def check_correspondence(candidate, documents, request, registry):
    closure, issues, required = BooleanClosure(documents), [], set()
    if len(set(documents.instances.values())) != len(documents.instances):
        raise ValueError("Correspondence requires an unambiguous world instance per model")
    clauses = request.request["original_goal"]["document"]["clauses"]
    correspondences = {item["goal_clause_id"]: item for item in candidate["goal_correspondence"]}
    if set(correspondences) != {item["id"] for item in clauses}:
        raise ValueError("Goal correspondence must cover every fixed clause exactly once")
    grounding = {item["id"]: item for item in candidate["grounding"]}
    expanded_clauses = []
    for clause in clauses:
        item = correspondences[clause["id"]]
        if item["meaning"] != clause["meaning"]:
            raise ValueError("The original goal clause meaning is fixed")
        if item["grounding_id"] is not None and item["grounding_id"] not in grounding:
            raise ValueError("A declared goal grounding must exist")
        if item["predicate"] is None:
            issues.append(f"missing_goal_predicate:{clause['id']}")
            continue
        facts = closure.predicate(item["predicate"])
        if not facts:
            raise ValueError("A goal clause cannot be a constant assertion")
        expanded_clauses.append(facts)
        required.update(facts)
        if item["grounding_id"] is None:
            issues.append(f"missing_goal_grounding:{clause['id']}")
        else:
            source = grounding.get(item["grounding_id"])
            if source is None or source["predicate"] != item["predicate"]:
                raise ValueError("Goal grounding must target its exact declared predicate")
            if source["binding_id"] is not None:
                binding = registry.grounding(source["binding_id"])
                if binding.goal_clause_id != clause["id"] or binding.meaning != clause["meaning"]:
                    raise ValueError(
                        "Goal correspondence lacks the matching trusted clause binding"
                    )
        if clause["id"] not in registry.observable_goal_clauses:
            issues.append(f"unavailable_goal_observation:{clause['id']}")
    if len(set(expanded_clauses)) != len(expanded_clauses):
        raise ValueError("Distinct goal clauses cannot collapse to the same fact closure")
    goal = candidate["entrypoints"]["goal"]
    if goal is None:
        issues.append("missing_goal_entrypoint")
    else:
        goal_facts = closure.predicate(goal)
        if len(expanded_clauses) == len(clauses):
            _same(goal_facts, frozenset().union(*expanded_clauses), "fixed goal dependency")
    for item in candidate["state_correspondence"]:
        parent, refined = closure.predicate(item["parent"]), closure.predicate(item["refined"])
        _same(parent, refined, "parent/refined state")
        abstract = documents.abstraction(item["abstraction"])
        reference = documents.predicate(item["refined"])
        if (
            abstract["document_id"] != reference["document_id"]
            or abstract["branch"] != reference["branch"]
            or reference["field"] not in abstract["definition"]["facts"]
        ):
            raise ValueError("The named abstraction must actually include the refined predicate")
        required.update(parent)
    refined_leaves = set()
    for item in candidate["action_refinements"]:
        parent = documents.action(item["parent_action"])
        pre = closure.condition(item["parent_precondition"])
        lower_pre = closure.condition(item["lower_precondition"])
        post = closure.condition(item["parent_postcondition"])
        lower_post = closure.condition(item["lower_postcondition"])
        _same(pre, lower_pre, "parent/lower precondition")
        _same(post, lower_post, "parent/lower postcondition")
        if not post:
            raise ValueError("A parent postcondition needs independently observed facts")
        _same(
            pre,
            closure.expression(
                parent["document_id"], parent["branch"], parent["definition"]["precondition"]
            ),
            "parent action guard",
        )
        root = documents.execution_block(item["refined_execution"])
        definition = documents.executions[root["document_id"]].to_dict()
        block = root["definition"]
        if (
            block["mechanism"] != "control.sequence"
            or block["mode"] != "memory"
            or len(block["members"]) < 3
        ):
            raise ValueError(
                "Refinement needs a memory sequence with entry and postcondition monitors"
            )
        for name, expected in ((block["members"][0], pre), (block["members"][-1], post)):
            monitor = definition["blocks"][name]
            if monitor["mechanism"] != "control.condition":
                raise ValueError(
                    "Refinement entry and observed postcondition must be condition monitors"
                )
            document = documents.instances[monitor["instance"]]
            _same(
                closure.expression(document, monitor["branch"], monitor["expression"]),
                expected,
                "execution monitor",
            )
        members = _members(definition, root["block_id"])
        leaves = [
            definition["blocks"][name]
            for name in members
            if definition["blocks"][name]["mechanism"] == "control.action"
        ]
        refined_leaves.update(
            (root["document_id"], name)
            for name in members
            if definition["blocks"][name]["mechanism"] == "control.action"
        )
        if not leaves:
            raise ValueError("An action refinement must reach actual action leaves")
        for leaf in leaves:
            document = documents.instances[leaf["instance"]]
            action = documents.action(_reference(document, f"{leaf['branch']}.{leaf['action']}"))
            guard = closure.expression(
                document, action["branch"], action["definition"]["precondition"]
            )
            if not pre <= guard:
                raise ValueError("Primitive guards cannot weaken the declared refinement entry")
            required.update(guard)
        required.update(pre | post)
    if not candidate["action_refinements"] or not candidate["state_correspondence"]:
        issues.append("missing_nontrivial_refinement")
    covered = set()
    for item in candidate["grounding"]:
        facts = closure.predicate(item["predicate"])
        if (
            len(item["input_stream_ids"]) != len(set(item["input_stream_ids"]))
            or not set(item["input_stream_ids"]) <= request.streams.keys()
        ):
            raise ValueError("Grounding requests unavailable or private input streams")
        if item["binding_id"] is None:
            issues.append(f"unbound_grounding:{item['id']}")
            continue
        binding = registry.grounding(item["binding_id"])
        if binding.meaning != item["meaning"] or set(binding.input_stream_ids) != set(
            item["input_stream_ids"]
        ):
            raise ValueError("Grounding meaning or granted inputs differ from the trusted binding")
        covered.update(facts)
    if required - covered:
        issues.append("unbound_observation_dependencies")
    if documents.systems or documents.applications:
        issues.append("unsupported_system_application_activation")
    bindings = _button_bindings(candidate, documents, registry, issues)
    for identifier, execution in documents.executions.items():
        definition = execution.to_dict()
        validate_button_composition(definition, documents.world(), bindings[identifier])
        for block in definition["blocks"].values():
            if block["mechanism"] == "control.condition":
                required.update(
                    closure.expression(
                        documents.instances[block["instance"]], block["branch"], block["expression"]
                    )
                )
    if required - covered and "unbound_observation_dependencies" not in issues:
        issues.append("unbound_observation_dependencies")
    _observation_writers(documents, required)
    execution = candidate["entrypoints"]["execution"]
    if execution is None:
        issues.append("missing_execution_entrypoint")
    else:
        root = documents.execution_block(execution)
        definition = documents.executions[root["document_id"]].to_dict()
        if root["block_id"] != definition["root"]:
            raise ValueError("The execution entrypoint must name its actual native root")
        descendants = _members(definition, definition["root"])
        selected_leaves = {
            (root["document_id"], name)
            for name in descendants
            if definition["blocks"][name]["mechanism"] == "control.action"
        }
        if not selected_leaves <= refined_leaves:
            raise ValueError("Every selected action leaf must belong to a validated refinement")
        for item in candidate["action_refinements"]:
            child = documents.execution_block(item["refined_execution"])
            if child["document_id"] != root["document_id"] or child["block_id"] not in descendants:
                raise ValueError("A declared action refinement must govern the selected execution")
    issues.extend(f"declared_unresolved:{item['id']}" for item in candidate["unresolved"])
    issues.extend(
        f"contradicted_evidence:{item['id']}"
        for item in candidate["evidence"]
        if item["assessment"] == "contradicted"
    )
    return tuple(sorted(set(issues))), bindings


def _observation_writers(documents, dependencies):
    events = set()
    for document, branch, field in dependencies:
        definition = next(
            item for item in documents.canonical[document]["branches"] if item["name"] == branch
        )
        if definition["states"] or definition.get("operations"):
            raise ValueError("Observed facts cannot be written by state lifecycle or operations")
        for reaction in definition["reactions"]:
            for update in reaction["updates"]:
                if update["field"] != field:
                    continue
                value = update["value"]
                unknown = value == {"kind": "literal", "value": {"kind": "unknown"}}
                if not unknown and (
                    value.get("kind") != "read" or value.get("source") != "payload"
                ):
                    raise ValueError(
                        "Observed fact updates require external observation payloads "
                        "or unknown resets"
                    )
                events.add((document, reaction["event"]))

    def check(value, document):
        if isinstance(value, dict):
            for key, item in value.items():
                if key == "emit":
                    if any((document, event) in events for event in item):
                        raise ValueError(
                            "Observation events cannot be synthesized by the candidate"
                        )
                else:
                    check(item, document)
        elif isinstance(value, list):
            for item in value:
                check(item, document)

    for document in documents.models:
        check(documents.canonical[document], document)


def _button_bindings(candidate, documents, registry, issues):
    result = {identifier: {} for identifier in documents.executions}
    seen = set()
    for item in candidate["primitive_bindings"]:
        location = documents.execution_block(item["leaf"])
        key = location["document_id"], location["block_id"]
        if key in seen or location["definition"]["mechanism"] != "control.action":
            raise ValueError("Primitive bindings must target distinct actual action leaves")
        seen.add(key)
        command = ButtonCommand.from_dict(item["arguments"])
        if item["binding_id"] is None:
            issues.append(f"unbound_primitive:{location['block_id']}")
            continue
        binding = registry.primitive(item["binding_id"])
        if (
            binding.contract_id != item["contract_id"]
            or binding.command.as_dict() != command.as_dict()
        ):
            raise ValueError("Primitive contract or arguments differ from the registered effect")
        result[key[0]][key[1]] = binding.command
    for identifier, execution in documents.executions.items():
        for name, block in execution.to_dict()["blocks"].items():
            if block["mechanism"] == "control.action" and (identifier, name) not in seen:
                issues.append(f"missing_primitive_binding:{identifier}/{name}")
    return {identifier: ButtonBindings(bindings) for identifier, bindings in result.items()}
