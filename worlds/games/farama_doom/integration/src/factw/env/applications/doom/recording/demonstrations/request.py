"""Export detached request inputs, never paths into a raw episode."""

import json
from dataclasses import asdict
from pathlib import Path

from .types import Demonstration, RequestExport
from .validation import (
    decode_json,
    detached,
    digest,
    fields,
    identifier,
    nonempty,
    sha256,
    validate_demonstration,
)


def _goal(payload):
    if not isinstance(payload, bytes):
        raise ValueError("Original goal must be retained exact UTF-8 bytes")
    goal = decode_json(payload)
    fields(
        goal,
        "schema id scenario_id scenario_behavior_revision text clauses "
        "agent_completion temporal_scope revision_rule",
        "original goal",
    )
    if goal["schema"] != "doom.refinement-original-goal/1":
        raise ValueError("Unsupported original-goal schema")
    identifier(goal["id"])
    for name in ("scenario_id", "text", "agent_completion", "temporal_scope", "revision_rule"):
        nonempty(goal[name], name)
    if (
        type(goal["scenario_behavior_revision"]) is not int
        or goal["scenario_behavior_revision"] < 1
    ):
        raise ValueError("Invalid scenario behavior revision")
    if not isinstance(goal["clauses"], list) or not goal["clauses"]:
        raise ValueError("Original goal requires clauses")
    clause_ids = set()
    for clause in goal["clauses"]:
        fields(clause, "id meaning", "goal clause")
        identifier(clause["id"])
        nonempty(clause["meaning"], "Clause meaning")
        if clause["id"] in clause_ids:
            raise ValueError("Duplicate original-goal clause")
        clause_ids.add(clause["id"])
    return {"sha256": sha256(payload), "document": goal}


def _priors(documents):
    result, document_ids = [], set()
    for document in documents:
        fields(document, "id role serialization source sha256", "prior SMSL document")
        identifier(document["id"])
        if document["id"] in document_ids:
            raise ValueError("Duplicate prior SMSL document")
        document_ids.add(document["id"])
        if document["role"] not in {
            "model",
            "abstraction",
            "execution",
            "system",
            "application",
        } or document["serialization"] not in {"smsl_text", "smsl_json"}:
            raise ValueError("Unsupported prior SMSL document declaration")
        nonempty(document["source"], "Prior SMSL source")
        digest(document["sha256"])
        if sha256(document["source"].encode("utf-8")) != document["sha256"]:
            raise ValueError("Prior SMSL source hash mismatch")
        result.append(detached(document))
    return result


def export_request(
    demonstration, *, request_id, original_goal, prior_smsl_documents=(), max_rgb_frames=128
):
    if not isinstance(demonstration, Demonstration) or "discovery" not in demonstration.consumers:
        raise ValueError("A discovery-granted detached demonstration is required")
    validate_demonstration(demonstration)
    identifier(request_id)
    if type(max_rgb_frames) is not int or not 2 <= max_rgb_frames <= 128:
        raise ValueError("RGB frame cap must be between 2 and 128")
    request = {
        "schema": "doom.refinement-request/1",
        "id": request_id,
        "original_goal": _goal(original_goal),
        "observation_streams": [],
    }
    assets, coverage_streams, asset_descriptors = {}, [], {}
    retained_references = set()
    for stream in demonstration.streams:
        available = stream.samples
        if stream.modality == "rgb" and len(available) > max_rgb_frames:
            indices = sorted(
                {i * (len(available) - 1) // (max_rgb_frames - 1) for i in range(max_rgb_frames)}
            )
        else:
            indices = list(range(len(available)))
        retained = set(indices)
        samples = []
        for index, sample in enumerate(available):
            if index not in retained:
                continue
            if sample.shape is None:
                content = {"text": sample.text}
            else:
                asset_id = f"rgb_{len(assets):06d}"
                assets[asset_id] = sample.payload
                asset_descriptors[asset_id] = {
                    "encoding": stream.encoding,
                    "shape": list(sample.shape),
                    "height": sample.shape[0],
                    "width": sample.shape[1],
                    "channels": 3,
                    "payload_sha256": sample.payload_sha256,
                    "stream_id": stream.id,
                    "sample_id": sample.id,
                }
                content = {"asset_id": asset_id}
            samples.append(
                {
                    "id": sample.id,
                    "ordinal": sample.ordinal,
                    "relative_time": sample.relative_time,
                    "payload_sha256": sample.payload_sha256,
                    "content": content,
                }
            )
            retained_references.add((stream.id, sample.id))
        gaps = []
        for gap in stream.gaps:
            previous = next(
                (
                    sample.id
                    for sample in reversed(available)
                    if sample.ordinal < gap.ordinal
                    and (stream.id, sample.id) in retained_references
                ),
                None,
            )
            following = next(
                (
                    sample.id
                    for sample in available
                    if sample.ordinal > gap.ordinal
                    and (stream.id, sample.id) in retained_references
                ),
                None,
            )
            gaps.append(
                {"after_sample": previous, "before_sample": following, "reason": gap.reason}
            )
        intervals = []
        for left, right in zip(indices, indices[1:], strict=False):
            if right - left > 1:
                interval = {
                    "after_sample": available[left].id,
                    "before_sample": available[right].id,
                    "first_omitted_ordinal": available[left + 1].ordinal,
                    "last_omitted_ordinal": available[right - 1].ordinal,
                    "omitted_count": right - left - 1,
                }
                intervals.append(interval)
                gaps.append(
                    {
                        "after_sample": interval["after_sample"],
                        "before_sample": interval["before_sample"],
                        "reason": "uniform_sampling_omission",
                    }
                )
        if samples:
            time_basis = {"kind": "relative_time", "unit": "transport_seconds"}
            if (
                stream.modality == "text"
                and all(sample.relative_time is None for sample in available)
                and all(gap.relative_time is None for gap in stream.gaps)
            ):
                time_basis = {"kind": "ordinal", "unit": "sample"}
            request["observation_streams"].append(
                {
                    "id": stream.id,
                    "modality": stream.modality,
                    "encoding": stream.encoding,
                    "source_id": stream.source_id,
                    "time_basis": time_basis,
                    "samples": samples,
                    "gaps": gaps,
                }
            )
        coverage_streams.append(
            {
                "stream_id": stream.id,
                "available_count": len(available),
                "selected_sample_ids": [available[index].id for index in indices],
                "omitted_intervals": intervals,
                "original_gaps": [asdict(gap) for gap in stream.gaps],
                "sample_provenance": [
                    {"sample_id": sample.id, "provenance": sample.provenance}
                    for sample in available
                ],
            }
        )
    if not request["observation_streams"]:
        raise ValueError("Task instructions alone are not demonstration observations")
    guidance = {}
    priors = _priors(prior_smsl_documents)
    if priors:
        guidance["prior_smsl_documents"] = priors
    if demonstration.existing_facts is not None:
        guidance["existing_facts"] = detached(demonstration.existing_facts)
    unexported_alignment = []
    if demonstration.commands is not None:
        commands = detached(demonstration.commands)
        for command in commands:
            omitted_refs = [
                ref
                for ref in command["aligned_observations"]
                if (ref["stream_id"], ref["sample_id"]) not in retained_references
            ]
            command["aligned_observations"] = [
                ref
                for ref in command["aligned_observations"]
                if (ref["stream_id"], ref["sample_id"]) in retained_references
            ]
            if omitted_refs:
                unexported_alignment.append(
                    {"command_id": command["id"], "unexported_observations": omitted_refs}
                )
        guidance["recorded_commands"] = commands
    if guidance:
        request["guidance"] = guidance
    coverage = {
        "schema": "doom.demonstration-coverage/1",
        "manifest_sha256": demonstration.manifest_sha256,
        "source_id": demonstration.source_id,
        "source_assistance": demonstration.source_assistance,
        "selection": "uniform_available_frame_ordinals_including_first_and_last",
        "max_rgb_frames": max_rgb_frames,
        "streams": coverage_streams,
        "assets": asset_descriptors,
        "unexported_command_alignment": unexported_alignment,
    }
    return RequestExport(request, assets, coverage)


def write_request_export(path, export):
    if not isinstance(export, RequestExport):
        raise ValueError("A detached RequestExport is required")
    descriptors = export.coverage["assets"]
    if set(descriptors) != set(export.assets):
        raise ValueError("Export asset metadata does not cover its payloads")
    for asset_id, payload in export.assets.items():
        if (
            not isinstance(payload, bytes)
            or sha256(payload) != descriptors[asset_id]["payload_sha256"]
        ):
            raise ValueError("Export asset hash mismatch")
    root = Path(path)
    root.mkdir(parents=True, exist_ok=False)
    (root / "assets").mkdir()
    records = {}
    for index, (asset_id, payload) in enumerate(export.assets.items()):
        filename = f"assets/{index:08d}.rgb"
        with (root / filename).open("xb") as handle:
            handle.write(payload)
        records[asset_id] = {"path": filename, **detached(descriptors[asset_id])}
    documents = {}
    for filename, content in (("request.json", export.request), ("coverage.json", export.coverage)):
        payload = (
            json.dumps(content, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        ).encode("utf-8")
        with (root / filename).open("xb") as handle:
            handle.write(payload)
        documents[filename.removesuffix(".json")] = {"path": filename, "sha256": sha256(payload)}
    manifest = {
        "schema": "doom.demonstration-request-export/1",
        **documents,
        "assets": records,
        "transport_requirement": "Supply request, coverage and declared assets together; "
        "coverage includes assistance, encoding, dimensions and unobserved intervals.",
    }
    with (root / "manifest.json").open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, ensure_ascii=False, allow_nan=False)
        handle.write("\n")
    return root / "manifest.json"
