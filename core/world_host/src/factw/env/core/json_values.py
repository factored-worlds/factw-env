from math import isfinite


def copy_json(value):
    if type(value) is str:
        value.encode("utf-8")
        return value
    if value is None or type(value) in (bool, int):
        return value
    if type(value) is float:
        if not isfinite(value):
            raise ValueError("Values must be finite JSON")
        return value
    if type(value) is list:
        return [copy_json(item) for item in value]
    if type(value) is dict and all(type(key) is str for key in value):
        return {copy_json(key): copy_json(item) for key, item in value.items()}
    raise TypeError("Expected JSON values with string object keys")
