from factw.env.core.recording.contract import number, text
from factw.env.core.recording.domain_actions import INTERFACES, validate_action

OPERATIONS = {"read", "inspect", "approve", "release", "revise", "clear"}
OUTCOMES = {
    "read": {"document_read"},
    "inspect": {"inspection_passed", "inspection_failed"},
    "approve": {"approval_passed", "approval_failed", "approval_denied"},
    "release": {"release_passed", "release_failed", "release_denied"},
    "revise": {"revision_changed"},
    "clear": {"clear"},
}


def keys(value: dict, names: set[str], description: str) -> None:
    if type(value) is not dict or set(value) != names:
        raise ValueError(f"Invalid {description} fields")


def action(value: dict, interface: str) -> None:
    if interface in INTERFACES:
        validate_action(value, interface)
    elif interface == "disk-target-v1":
        keys(value, {"disk", "target"}, "disk-target action")
        if type(value["disk"]) is not int or value["disk"] < 0:
            raise ValueError("Disk must be a nonnegative integer")
        if type(value["target"]) is not int or value["target"] not in range(3):
            raise ValueError("Target must be peg zero, one, or two")
    elif interface == "cartesian-jaw-setpoint-v1":
        keys(value, {"x", "y", "z", "grip"}, "Cartesian command")
        for name, coordinate in value.items():
            number(coordinate, name)
    elif interface == "review-command-v1":
        keys(value, {"operation", "document", "content"}, "review command")
        if type(value["operation"]) is not str or value["operation"] not in OPERATIONS:
            raise ValueError("Unknown review operation")
        text(value["document"], "Document ID")
        if value["operation"] == "revise":
            if type(value["content"]) is not str:
                raise ValueError("Revision content must be a string")
        elif value["content"] is not None:
            raise ValueError("Only revise commands contain content")


def review_observation(observation, *, initial: bool = False) -> None:
    graph, reply = observation.graph, observation.tool_result
    keys(graph, {"document", "nodes", "edges"}, "review graph")
    document = graph["document"]
    keys(document, {"id", "content", "revision"}, "review document")
    text(document["id"], "Document ID")
    if type(document["content"]) is not str:
        raise ValueError("Document content must be a string")
    if type(document["revision"]) is not int or document["revision"] < 1:
        raise ValueError("Revision must be a positive integer")
    if type(graph["nodes"]) is not list or type(graph["edges"]) is not list:
        raise ValueError("Graph nodes and edges must be lists")
    nodes = set()
    for node in graph["nodes"]:
        keys(node, {"id", "operation"}, "review graph node")
        text(node["id"], "Node ID")
        text(node["operation"], "Node operation")
        if node["id"] in nodes or node["operation"] not in OPERATIONS:
            raise ValueError("Graph nodes need unique IDs and known operations")
        nodes.add(node["id"])
    for edge in graph["edges"]:
        keys(edge, {"source", "target"}, "review graph edge")
        text(edge["source"], "Edge source")
        text(edge["target"], "Edge target")
        if edge["source"] not in nodes or edge["target"] not in nodes:
            raise ValueError("Graph edges must reference declared nodes")
    keys(reply, {"operation", "outcome", "document"}, "tool result")
    text(reply["operation"], "Tool operation")
    text(reply["outcome"], "Tool outcome")
    if reply["operation"] not in OUTCOMES or reply["outcome"] not in OUTCOMES[reply["operation"]]:
        raise ValueError("Invalid tool operation or outcome")
    if reply["document"] != document["id"]:
        raise ValueError("Tool result does not describe the observed document")
    if initial and (reply["operation"], reply["outcome"]) != ("read", "document_read"):
        raise ValueError("Initial review observation must be a neutral read")


def review_transition(before, command: dict, after, outcome: str) -> None:
    review_observation(after)
    reply = after.tool_result
    if (
        command["document"] != before.graph["document"]["id"]
        or command["document"] != reply["document"]
        or command["operation"] != reply["operation"]
        or outcome != reply["outcome"]
    ):
        raise ValueError("Review command, observation, and outcome are misaligned")
