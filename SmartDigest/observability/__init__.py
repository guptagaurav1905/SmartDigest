"""
SmartDigest observability package.

Drop-in observability layer for GenAI calls — wraps any LLM function with
tracing, metrics, validation, and a live Plotly Dash dashboard.

Quick start:
    from observability import observe, TraceStore, make_input_validator
    from observability import ScorerPromptInput, make_scoring_output_validator

    store = TraceStore("db/genai_traces.db")

    @observe(usecase="my-usecase", model="llama-3.3-70b-versatile", store=store)
    def call_llm(prompt: str) -> dict:
        ...
        return {"response": "...", "prompt_tokens": 100, "completion_tokens": 50}

Dashboard:
    python observability/dashboard/app.py   →   http://localhost:8050
"""

from .observer import observe, LLMTrace, estimate_cost, COST_PER_1K_TOKENS
from .store import TraceStore
from .validators import (
    make_input_validator,
    make_output_validator,
    make_scoring_output_validator,
    PromptInput,
    ScorerPromptInput,
    SummarizationInput,
    LLMResponse,
    check_dataframe_quality,
)
from .langfuse_client import get_langfuse_client

__all__ = [
    # Core decorator
    "observe",
    "LLMTrace",
    "estimate_cost",
    "COST_PER_1K_TOKENS",
    # Persistence
    "TraceStore",
    # Validators
    "make_input_validator",
    "make_output_validator",
    "make_scoring_output_validator",
    "PromptInput",
    "ScorerPromptInput",
    "SummarizationInput",
    "LLMResponse",
    "check_dataframe_quality",
    # Langfuse
    "get_langfuse_client",
]
