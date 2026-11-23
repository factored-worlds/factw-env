from dataclasses import fields


def members(value: object, names: set[str]) -> dict:
    if type(value) is not dict or set(value) != names:
        raise ValueError(f"Expected object fields: {', '.join(sorted(names))}")
    return value


def record(value: object, cls: type) -> dict:
    return members(value, {field.name for field in fields(cls)})


def array(value: object) -> tuple:
    if type(value) is not list:
        raise ValueError("Expected a JSON array")
    return tuple(value)


def memory(value: object, cls: type):
    if value is None:
        return None
    values = record(value, cls)
    if any(type(item) is not int for item in values.values()):
        raise ValueError("Memory fields must be integers")
    return cls(**values)
