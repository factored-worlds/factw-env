"""Check retained sample coverage and opaque RGB asset bytes."""

import math

from ..recording.demonstrations.validation import (
    GAP_REASONS,
    digest,
    fields,
    integer,
    nonempty,
    relative_time,
    sha256,
)


def _coverage_stream(record, stream, maximum):
    fields(
        record,
        "stream_id available_count selected_sample_ids omitted_intervals "
        "original_gaps sample_provenance",
        "coverage stream",
    )
    integer(record["available_count"], "Available sample count")
    provenance = record["sample_provenance"]
    gaps = record["original_gaps"]
    if not isinstance(provenance, list) or not isinstance(gaps, list):
        raise ValueError("Invalid sample provenance or original gaps")
    for item in provenance:
        fields(item, "sample_id provenance", "sample provenance")
        nonempty(item["sample_id"], "Sample identity")
        if item["provenance"] not in ("player_observation", "authored_demonstration"):
            raise ValueError("Unsupported observation provenance")
    sample_ids = [item["sample_id"] for item in provenance]
    if len(sample_ids) != len(set(sample_ids)):
        raise ValueError("Duplicate sample provenance identity")
    if len(provenance) != record["available_count"]:
        raise ValueError("Coverage sample count differs from provenance")
    gap_ordinals, captures = set(), {item["sample_id"] for item in provenance}
    for gap in gaps:
        fields(
            gap,
            "ordinal relative_time after_sample before_sample reason capture_id",
            "original gap",
        )
        integer(gap["ordinal"], "Gap ordinal")
        if gap["ordinal"] in gap_ordinals:
            raise ValueError("Duplicate gap ordinal")
        gap_ordinals.add(gap["ordinal"])
        if gap["relative_time"] is not None:
            relative_time(gap["relative_time"])
        elif stream is not None and stream["modality"] == "rgb":
            raise ValueError("RGB gaps require actual transport timestamps")
        if not isinstance(gap["reason"], str) or gap["reason"] not in GAP_REASONS:
            raise ValueError("Unsupported original gap reason")
        if gap["capture_id"] is not None:
            nonempty(gap["capture_id"], "Unavailable capture identity")
            if gap["capture_id"] in captures:
                raise ValueError("Duplicate available or unavailable capture identity")
            captures.add(gap["capture_id"])
    count = len(provenance) + len(gaps)
    if any(ordinal >= count for ordinal in gap_ordinals):
        raise ValueError("Gap ordinal falls outside coverage")
    available_ordinals = [ordinal for ordinal in range(count) if ordinal not in gap_ordinals]
    positions = dict(
        zip((item["sample_id"] for item in provenance), available_ordinals, strict=True)
    )
    for gap in gaps:
        for name, before in (("after_sample", True), ("before_sample", False)):
            ref = gap[name]
            if ref is not None:
                nonempty(ref, "Gap sample reference")
                if ref not in positions or (positions[ref] < gap["ordinal"]) != before:
                    raise ValueError("Original gap reference is unavailable or out of order")
    if stream is None:
        if (
            provenance
            or not gaps
            or record["selected_sample_ids"] != []
            or record["omitted_intervals"] != []
        ):
            raise ValueError("Only an entirely unavailable stream may be omitted from the request")
        return
    samples = stream["samples"]
    if stream["modality"] == "rgb" and len(provenance) > maximum:
        indices = sorted({i * (len(provenance) - 1) // (maximum - 1) for i in range(maximum)})
    else:
        indices = list(range(len(provenance)))
    selected = [provenance[index]["sample_id"] for index in indices]
    if (
        record["selected_sample_ids"] != selected
        or [sample["id"] for sample in samples] != selected
    ):
        raise ValueError("Selected observations differ from declared uniform coverage")
    for sample in samples:
        if sample["ordinal"] != positions[sample["id"]]:
            raise ValueError("Selected sample ordinal differs from coverage")
    known_times = sorted(
        (item["ordinal"], item["relative_time"])
        for item in [*samples, *gaps]
        if item["relative_time"] is not None
    )
    if any(right[1] < left[1] for left, right in zip(known_times, known_times[1:], strict=False)):
        raise ValueError("Observation and gap timestamps must be monotonic")
    if stream["modality"] == "rgb" and any(
        item["provenance"] != "player_observation" for item in provenance
    ):
        raise ValueError("RGB requires player-observation provenance")
    intervals = []
    for left, right in zip(indices, indices[1:], strict=False):
        if right - left > 1:
            intervals.append(
                {
                    "after_sample": provenance[left]["sample_id"],
                    "before_sample": provenance[right]["sample_id"],
                    "first_omitted_ordinal": available_ordinals[left + 1],
                    "last_omitted_ordinal": available_ordinals[right - 1],
                    "omitted_count": right - left - 1,
                }
            )
    if not isinstance(record["omitted_intervals"], list):
        raise ValueError("Invalid omitted intervals")
    for interval in record["omitted_intervals"]:
        fields(
            interval,
            "after_sample before_sample first_omitted_ordinal last_omitted_ordinal omitted_count",
            "omitted interval",
        )
        for name in ("first_omitted_ordinal", "last_omitted_ordinal", "omitted_count"):
            integer(interval[name], name)
    if record["omitted_intervals"] != intervals:
        raise ValueError("Omitted intervals differ from declared uniform coverage")
    expected_gaps = []
    for gap in gaps:
        expected_gaps.append(
            {
                "after_sample": next(
                    (
                        sample["id"]
                        for sample in reversed(samples)
                        if sample["ordinal"] < gap["ordinal"]
                    ),
                    None,
                ),
                "before_sample": next(
                    (sample["id"] for sample in samples if sample["ordinal"] > gap["ordinal"]), None
                ),
                "reason": gap["reason"],
            }
        )
    expected_gaps.extend(
        {
            "after_sample": interval["after_sample"],
            "before_sample": interval["before_sample"],
            "reason": "uniform_sampling_omission",
        }
        for interval in intervals
    )
    if stream["gaps"] != expected_gaps:
        raise ValueError("Request gaps differ from retained coverage")


def validate_coverage(request, coverage, assets):
    fields(
        coverage,
        "schema manifest_sha256 source_id source_assistance selection max_rgb_frames "
        "streams assets unexported_command_alignment",
        "coverage",
    )
    if coverage["schema"] != "doom.demonstration-coverage/1":
        raise ValueError("Unsupported coverage schema")
    digest(coverage["manifest_sha256"])
    nonempty(coverage["source_id"], "Coverage source")
    if coverage["source_assistance"] not in ("reference_assisted", "unassisted", "authored"):
        raise ValueError("Unsupported source assistance")
    if coverage["selection"] != "uniform_available_frame_ordinals_including_first_and_last":
        raise ValueError("Unsupported observation selection")
    maximum = coverage["max_rgb_frames"]
    if type(maximum) is not int or not 2 <= maximum <= 128:
        raise ValueError("RGB frame cap must be between 2 and 128")
    if not isinstance(coverage["streams"], list) or not coverage["streams"]:
        raise ValueError("Coverage requires declared streams")
    for record in coverage["streams"]:
        if not isinstance(record, dict) or not isinstance(record.get("stream_id"), str):
            raise ValueError("Invalid coverage stream")
        nonempty(record["stream_id"], "Coverage stream identity")
    identities = [record["stream_id"] for record in coverage["streams"]]
    if len(identities) != len(set(identities)):
        raise ValueError("Duplicate coverage stream identity")
    streams = {stream["id"]: stream for stream in request["observation_streams"]}
    coverage_ids = {record["stream_id"] for record in coverage["streams"]}
    if not set(streams) <= coverage_ids:
        raise ValueError("Observation stream lacks retained coverage")
    for record in coverage["streams"]:
        _coverage_stream(record, streams.get(record["stream_id"]), maximum)
    descriptors = coverage["assets"]
    if not isinstance(descriptors, dict) or set(descriptors) != set(assets):
        raise ValueError("Asset descriptors must exactly cover supplied payloads")
    used_assets = set()
    for stream in streams.values():
        if stream["source_id"] != coverage["source_id"]:
            raise ValueError("Observation source differs from its granted export")
        modality = (stream["modality"], stream["encoding"])
        if modality not in {("text", "utf_8"), ("rgb", "rgb_uint8_hwc")}:
            raise ValueError("Unsupported observation modality or encoding")
        times = []
        for sample in stream["samples"]:
            if sample["relative_time"] is not None:
                times.append(relative_time(sample["relative_time"]))
            elif stream["modality"] == "rgb":
                raise ValueError("RGB requires actual transport timestamps")
            if modality[0] == "text":
                fields(sample["content"], "text", "inline text")
                nonempty(sample["content"]["text"], "Text observation")
                payload = sample["content"]["text"].encode("utf-8")
            else:
                fields(sample["content"], "asset_id", "RGB content")
                asset_id = sample["content"]["asset_id"]
                if asset_id in used_assets or asset_id not in descriptors:
                    raise ValueError("RGB asset is duplicate or absent")
                used_assets.add(asset_id)
                descriptor = descriptors[asset_id]
                fields(
                    descriptor,
                    "encoding shape height width channels payload_sha256 stream_id sample_id",
                    "RGB asset descriptor",
                )
                shape = descriptor["shape"]
                if (
                    not isinstance(shape, list)
                    or len(shape) != 3
                    or any(type(n) is not int or n < 1 for n in shape)
                    or shape[2] != 3
                ):
                    raise ValueError("RGB shape must be HxWx3")
                if (descriptor["height"], descriptor["width"], descriptor["channels"]) != tuple(
                    shape
                ) or any(
                    type(descriptor[name]) is not int for name in ("height", "width", "channels")
                ):
                    raise ValueError("RGB dimensions disagree with shape")
                if (
                    descriptor["encoding"] != stream["encoding"]
                    or descriptor["payload_sha256"] != sample["payload_sha256"]
                    or (descriptor["stream_id"], descriptor["sample_id"])
                    != (stream["id"], sample["id"])
                ):
                    raise ValueError("RGB descriptor differs from granted sample")
                payload = assets[asset_id]
                if type(payload) is not bytes or len(payload) != math.prod(shape):
                    raise ValueError("RGB payload length differs from shape")
            if sha256(payload) != sample["payload_sha256"]:
                raise ValueError("Observation payload hash mismatch")
        if any(right < left for left, right in zip(times, times[1:], strict=False)):
            raise ValueError("Observation timestamps must be monotonic")
        expected_time = {"kind": "relative_time", "unit": "transport_seconds"}
        record = next(item for item in coverage["streams"] if item["stream_id"] == stream["id"])
        if (
            modality[0] == "text"
            and not times
            and all(gap["relative_time"] is None for gap in record["original_gaps"])
        ):
            expected_time = {"kind": "ordinal", "unit": "sample"}
        if stream["time_basis"] != expected_time:
            raise ValueError("Observation time basis differs from available timing")
    if used_assets != set(assets):
        raise ValueError("Supplied assets include ungranted payloads")
