"""Register explicit algorithm choices with their standard contracts."""

from .provider import Provider


def register_providers(registry, definitions, *, boundary, private_contracts=()):
    persistence = {
        "subsymbolic.execute_skill": "external",
        **dict.fromkeys(private_contracts, "private"),
    }
    for name, contract, output, function in definitions:
        registry.register(
            name=name,
            contracts=[contract],
            factory=lambda config, output=output, function=function, contract=contract: Provider(
                output, function, contract=contract, boundary=boundary
            ),
            metadata={
                "title": name,
                "description": f"{function.__module__}.{function.__name__}",
                "persistence": persistence.get(contract, "stateless"),
            },
        )
