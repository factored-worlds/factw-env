DEPTH_BUFFER_ENCODING = "vizdoom-depth-u8-v1"
SCHEMAS = ("1.0", "2.0")


def schema_version(value):
    if value not in SCHEMAS:
        raise ValueError("Unsupported trajectory schema")
    return value


def sensor_encodings(version, value):
    schema_version(version)
    if version == "1.0":
        return {}
    if type(value) is not dict or set(value) - {"depth_buffer"}:
        raise ValueError("Trajectory 2.0 requires a sensor_encodings object")
    if "depth_buffer" in value and value["depth_buffer"] != DEPTH_BUFFER_ENCODING:
        raise ValueError("Unsupported depth buffer encoding")
    return dict(value)


def boundary_status(terminated, truncated):
    if terminated and truncated:
        return "terminated_and_truncated"
    return "terminated" if terminated else "truncated" if truncated else "partial"


def reject_legacy_depth(metadata, paths):
    benchmark = metadata.get("benchmark")
    vizdoom = metadata["engine"] == "benchmark-vizdoom-v1" or (
        type(benchmark) is dict and benchmark.get("backend") == "vizdoom"
    )
    if metadata["schema_version"] == "1.0" and vizdoom and "depth" in paths:
        raise ValueError(
            "Legacy ViZDoom depth is mislabeled nonmetric data; metric decoding is unsafe"
        )
