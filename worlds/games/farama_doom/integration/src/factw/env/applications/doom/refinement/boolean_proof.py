"""Expand the bounded Boolean conjunction proof profile over linked facts."""


class BooleanClosure:
    """Compare expanded conjunctions; unsupported proofs fail explicitly."""

    def __init__(self, documents):
        self.documents = documents

    def branch(self, document, branch):
        if document not in self.documents.instances.values():
            raise ValueError("A referenced model needs an unambiguous world instance")
        aliases = getattr(self.documents, "model_aliases", {}).get(document, {})
        branch = aliases.get(branch, branch)
        result = next(
            (
                item
                for item in self.documents.canonical[document]["branches"]
                if item["name"] == branch
            ),
            None,
        )
        if result is None:
            raise ValueError(f"Absent linked branch: {branch}")
        return result

    def predicate(self, reference, active=frozenset()):
        location = self.documents.predicate(reference)
        return self.fact(location["document_id"], location["branch"], location["field"], active)

    def fact(self, document, branch, field, active):
        definition = self.branch(document, branch)
        key = (document, definition["name"], field)
        if key in active:
            raise ValueError("Cyclic goal or correspondence dependency")
        fact = next((item for item in definition["facts"] if item["name"] == field), None)
        if (
            fact is None
            or fact["values"] != [False, True]
            or any(type(value) is not bool for value in fact["values"])
        ):
            raise ValueError("The refinement proof profile requires Boolean facts")
        if fact["derived"] is not None:
            return self.expression(document, definition["name"], fact["derived"], active | {key})
        if fact["initial"] != {"kind": "unknown"}:
            raise ValueError("Observation-grounded facts must initialize unknown")
        return frozenset({key})

    def expression(self, document, branch, expression, active=frozenset()):
        kind = expression["kind"]
        if kind == "and":
            return self.expression(document, branch, expression["left"], active) | self.expression(
                document, branch, expression["right"], active
            )
        if kind == "literal" and expression.get("value") is True:
            return frozenset()
        if kind != "read":
            raise ValueError("Correspondence proof supports Boolean conjunctions and reads only")
        source = expression["source"]
        definition = self.branch(document, branch)
        if source == "self":
            target = definition["name"]
        else:
            reads = {item["alias"]: item["branch"] for item in definition["reads"]}
            target = reads.get(source, source)
        return self.fact(document, target, expression["field"], active)

    def condition(self, record):
        condition = self.documents.condition(record)
        return self.expression(
            condition["document_id"], condition["branch"], condition["expression"]
        )
