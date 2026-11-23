"""An explicit, revision-pinned first multimodal inference configuration."""

from dataclasses import dataclass
from pathlib import Path

MODEL = "gpt-5.4-2026-03-05"
PURPOSES = ("candidate_discovery", "candidate_repair", "observation_grounding")
INPUT_LIMIT = 262144
OUTPUT_LIMIT = 32768
COST_LIMIT_NANO_USD = 5000000000
INPUT_NANO_USD_PER_TOKEN = 2500
OUTPUT_NANO_USD_PER_TOKEN = 15000


@dataclass(frozen=True, slots=True)
class ModelConfiguration:
    provider: str
    model: str
    condition_id: str
    ledger_path: Path
    episode_id: str | None = None

    def __post_init__(self):
        if self.provider != "openai" or self.model != MODEL:
            raise ValueError("This pilot requires openai/gpt-5.4-2026-03-05")
        if not isinstance(self.condition_id, str) or not self.condition_id.strip():
            raise ValueError("An explicit condition identity is required")
        if not isinstance(self.ledger_path, Path):
            raise ValueError("An explicit pathlib ledger path is required")
        if self.episode_id is not None and (
            not isinstance(self.episode_id, str) or not self.episode_id.strip()
        ):
            raise ValueError("An execution episode identity must be nonempty")

    def describe(self):
        return {
            "schema": "doom.model_configuration/1",
            "provider": self.provider,
            "model": self.model,
            "condition_id": self.condition_id,
            "transport": "smsl_harness.models.openai.OpenAIModel",
            "harness_version": "0.2.0rc14",
            "modalities": ["text", "rgb"],
            "image_detail": "high",
            "image_accounting": "ceil(min(raw_32px_patches,2500)*1.2)+1",
            "reasoning_effort": "none (provider default)",
            "text_accounting": "UTF-8 byte upper bound plus 4096 framing tokens",
            "input_tokens_per_condition": INPUT_LIMIT,
            "output_tokens_per_condition": OUTPUT_LIMIT,
            "cost_limit_nano_usd": COST_LIMIT_NANO_USD,
            "input_nano_usd_per_token": INPUT_NANO_USD_PER_TOKEN,
            "output_nano_usd_per_token": OUTPUT_NANO_USD_PER_TOKEN,
            "candidate_requests_per_condition": 2,
            "grounding_requests_per_episode": 64,
            "wall_seconds_per_episode": 1200,
            "candidate_input_tokens_per_call": 131072,
            "candidate_output_tokens_per_call": 16384,
            "grounding_input_tokens_per_call": 32768,
            "grounding_output_tokens_per_call": 2048,
            "request_timeout_seconds": 180,
            "retries": 0,
            "pricing_source": "https://developers.openai.com/api/docs/models/gpt-5.4",
            "image_accounting_source": (
                "https://developers.openai.com/api/docs/guides/images-vision"
            ),
        }
