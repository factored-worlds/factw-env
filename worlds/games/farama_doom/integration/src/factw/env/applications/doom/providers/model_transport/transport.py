"""Reuse the harness Responses adapter with explicit media, budgets and audit."""

import asyncio
import hashlib
import json
from dataclasses import asdict
from importlib.metadata import version

from .configuration import PURPOSES
from .images import encoded, image_inputs
from .ledger import BudgetExceeded, BudgetLedger

SYSTEM = (
    "Perform the supplied State Language discovery or observation-grounding task. "
    "Use only the supplied observations, document sources and declared task priors. "
    "Preserve unknowns and the original goal; do not invent private simulator data. "
    "Emit the exact requested JSON document as the content string of emit_result."
)
TOOL_DESCRIPTION = "Return the complete JSON document required by the task."
TOOL_PARAMETERS = {
    "type": "object",
    "properties": {"content": {"type": "string"}},
    "required": ["content"],
    "additionalProperties": False,
}


def _content(arguments):
    if (
        not isinstance(arguments, dict)
        or set(arguments) != {"content"}
        or not isinstance(arguments["content"], str)
        or not arguments["content"].strip()
    ):
        raise ValueError("emit_result requires exactly one nonempty content string")


class MeteredModel:
    def __init__(self, configuration, model, *, clock=None):
        if version("smsl-harness") != "0.2.0rc14":
            raise ValueError("The selected smsl-harness==0.2.0rc14 dependency is required")
        self.configuration = configuration
        self.model = model
        self.ledger = BudgetLedger(configuration, **({} if clock is None else {"clock": clock}))

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def describe(self):
        return {
            **self.configuration.describe(),
            "ledger_path": str(self.configuration.ledger_path),
            "episode_id": self.configuration.episode_id,
            "usage": self.ledger.describe(),
        }

    def generate(self, payload, assets):
        from smsl_harness.models import Message, Request, Tool

        payload = json.loads(encoded(payload))
        assets = dict(assets)
        if not isinstance(payload, dict) or payload.get("purpose") not in PURPOSES:
            raise ValueError("An explicit supported task purpose is required")
        if not isinstance(payload.get("instructions"), str) or not payload["instructions"].strip():
            raise ValueError("Explicit task instructions are required")
        if not isinstance(payload.get("output_schema"), dict):
            raise ValueError("An explicit task output schema is required")
        for sample in payload.get("observation_sequence", []):
            if sample.get("modality") not in ("rgb", "text"):
                raise ValueError("This model transport supports only text and RGB observations")
        media, label_bytes, image_tokens, pngs = image_inputs(payload, assets)
        payload_bytes = encoded(payload)
        text_bound = len(payload_bytes) + len(SYSTEM.encode()) + label_bytes
        text_bound += len(encoded(TOOL_PARAMETERS)) + len(TOOL_DESCRIPTION.encode()) + 4096
        input_bound = text_bound + image_tokens
        grounding = payload["purpose"] == "observation_grounding"
        description = self.configuration.describe()
        prefix = "grounding" if grounding else "candidate"
        input_limit = description[f"{prefix}_input_tokens_per_call"]
        output_limit = description[f"{prefix}_output_tokens_per_call"]
        if input_bound > input_limit:
            raise BudgetExceeded("model_input_tokens_per_request")
        content = [{"type": "input_text", "text": payload_bytes.decode("utf-8")}, *media]
        items = ({"role": "user", "content": content},)
        request = Request(
            messages=(Message("system", SYSTEM), Message("user", continuation=items)),
            tools=(Tool("emit_result", TOOL_DESCRIPTION, TOOL_PARAMETERS, _content),),
            max_output_tokens=output_limit,
        )
        api_request = {
            "model": self.configuration.model,
            "input": [{"role": "system", "content": SYSTEM}, *items],
            "tools": [
                {
                    "type": "function",
                    "name": "emit_result",
                    "description": TOOL_DESCRIPTION,
                    "parameters": TOOL_PARAMETERS,
                    "strict": True,
                }
            ],
            "tool_choice": "required",
            "parallel_tool_calls": False,
            "max_output_tokens": output_limit,
            "store": False,
            "include": ["reasoning.encrypted_content"],
        }
        request_bytes = encoded(api_request)
        call_id = self.ledger.reserve(
            payload["purpose"],
            input_limit,
            output_limit,
            hashlib.sha256(request_bytes).hexdigest(),
        )
        audit = self.configuration.ledger_path.with_suffix("") / f"call_{call_id:04d}"
        audit.mkdir(parents=True, exist_ok=False)
        returned = False
        try:
            (audit / "configuration.json").write_bytes(encoded(description))
            (audit / "payload.json").write_bytes(payload_bytes)
            (audit / "api_request.json").write_bytes(request_bytes)
            manifest = []
            for ordinal, (asset_id, png) in enumerate(pngs.items()):
                stem = f"image_{ordinal:04d}"
                (audit / f"{stem}.rgb").write_bytes(assets[asset_id])
                (audit / f"{stem}.png").write_bytes(png)
                manifest.append(
                    {"asset_id": asset_id, "rgb_file": f"{stem}.rgb", "png_file": f"{stem}.png"}
                )
            (audit / "images.json").write_bytes(encoded(manifest))
            timeout = description["request_timeout_seconds"]
            if grounding:
                timeout = min(timeout, self.ledger.remaining_seconds())

            async def complete():
                return await asyncio.wait_for(self.model.complete(request), timeout=timeout)

            reply = asyncio.run(complete())
            returned = True
            (audit / "reply.json").write_bytes(encoded(asdict(reply)))
            self.ledger.settle(call_id, model=reply.model, usage=reply.usage)
            if grounding:
                self.ledger.remaining_seconds()
            if reply.message.text.strip() or len(reply.message.calls) != 1:
                raise ValueError("The model must return exactly one emit_result call")
            call = reply.message.calls[0]
            if call.name != "emit_result":
                raise ValueError("The model called an unregistered result tool")
            _content(call.arguments)
            result = call.arguments["content"].encode("utf-8")
            (audit / "result.json").write_bytes(result)
            return result
        finally:
            if not returned:
                self.ledger.fail(call_id, "transport_did_not_return")
            (audit / "ledger.json").write_bytes(encoded(self.ledger.describe()))


def openai_transport(configuration, api_key):
    if not isinstance(api_key, str) or not api_key.strip():
        raise ValueError("An explicitly supplied OpenAI API key is required")

    class Model:
        async def complete(self, request):
            from openai import AsyncOpenAI
            from smsl_harness.models.openai import OpenAIModel

            async with AsyncOpenAI(
                api_key=api_key,
                base_url="https://api.openai.com/v1",
                max_retries=0,
                timeout=180,
            ) as client:
                return await OpenAIModel(client, configuration.model).complete(request)

    return MeteredModel(configuration, Model())
