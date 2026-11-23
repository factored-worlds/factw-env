"""Load each scenario's State Language documents with unique instance scopes."""

import json

import smsl
from factw.env.worlds.doom.assets import document_sources


def resolved_documents(scenario, *, planner=None):
    documents = document_sources(scenario)
    if planner is not None:
        planner.validate(scenario)
        system = smsl.SystemDefinition.loads(documents["system.smsl"]).to_dict()
        component = next(item for item in system["components"] if item["id"] == "planner")
        component["blocks"][0]["provider"] = planner.provider_id
        documents["system.smsl"] = json.dumps(system)
    return documents


def load_definition(scenario="games.doom/retrieve-key-and-escape", scope=None, *, planner=None):
    documents = resolved_documents(scenario, planner=planner)
    sources = {
        name: smsl.Source(documents[name], "json")
        if planner is not None and name == "system.smsl"
        else smsl.Source(documents[name])
        for name in (part + ".smsl" for part in ("domain", "task", "system"))
    }
    application = smsl.ApplicationDefinition.loads(documents["application.smsl"], sources=sources)
    if scope is None:
        return application
    document = application.to_dict()
    for instance in document["instances"]:
        instance["context"]["scope"] += "-" + scope
    return smsl.ApplicationDefinition(document, sources=sources)
