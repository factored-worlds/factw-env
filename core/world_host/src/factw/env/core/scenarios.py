"""Behavior identities from installed, case-owned scenario descriptors."""

import json
from importlib.resources import files


def identity(package, scenario_id):
    descriptors = []
    for directory in files(package).joinpath("scenarios").iterdir():
        resource = directory.joinpath("scenario.json")
        if directory.is_dir() and resource.is_file():
            descriptor = json.loads(resource.read_text())
            if descriptor["scenario_id"] == scenario_id:
                descriptors.append(descriptor)
    if len(descriptors) != 1:
        raise ValueError("Installed scenario identity must select exactly one descriptor")
    revision = descriptors[0]["behavior_revision"]
    if type(revision) is not int or revision < 1:
        raise ValueError("Installed scenario identity or behavior revision is invalid")
    return {"scenario_id": scenario_id, "scenario_revision": revision}
