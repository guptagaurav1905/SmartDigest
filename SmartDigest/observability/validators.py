"""
validators.py — Input/output data quality checks using Pydantic.
Includes base validators from the observability boilerplate plus
SmartDigest-specific validators for the Groq relevance scorer.

Plug any validator into @observe(..., input_validator=..., output_validator=...).
"""

import json
from pydantic import BaseModel, field_validator, ValidationError
from typing import Optional, List


# ---------------------------------------------------------------------------
# Reusable base validators
# ---------------------------------------------------------------------------

class PromptInput(BaseModel):
    """Validates a raw prompt string before sending to LLM."""
    text: str

    @field_validator("text")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Prompt must not be empty")
        return v

    @field_validator("text")
    @classmethod
    def max_length(cls, v: str) -> str:
        if len(v) > 32_000:
            raise ValueError(f"Prompt too long: {len(v)} chars (max 32000)")
        return v


class LLMResponse(BaseModel):
    """Validates the text content of an LLM response."""
    text: str
    min_length: int = 1

    @field_validator("text")
    @classmethod
    def not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("LLM response was empty")
        return v


class SummarizationInput(PromptInput):
    """Domain-specific: summarization usecase."""

    @field_validator("text")
    @classmethod
    def has_enough_content(cls, v: str) -> str:
        if len(v.split()) < 10:
            raise ValueError("Text too short to summarize (< 10 words)")
        return v


class QAInput(BaseModel):
    """Domain-specific: question-answering usecase."""
    question: str
    context: Optional[str] = None

    @field_validator("question")
    @classmethod
    def ends_with_question_mark(cls, v: str) -> str:
        # Soft check — does not block
        return v


# ---------------------------------------------------------------------------
# SmartDigest-specific validators
# ---------------------------------------------------------------------------

class ScorerPromptInput(PromptInput):
    """
    Validates the scoring batch prompt sent to Groq in groq_scorer.py.
    Ensures the prompt is well-formed before burning API tokens.
    """

    @field_validator("text")
    @classmethod
    def has_items_to_score(cls, v: str) -> str:
        if "ITEMS TO SCORE:" not in v:
            raise ValueError("Scoring prompt missing 'ITEMS TO SCORE:' section")
        return v

    @field_validator("text")
    @classmethod
    def has_user_interests(cls, v: str) -> str:
        if "USER INTERESTS:" not in v:
            raise ValueError("Scoring prompt missing 'USER INTERESTS:' section")
        return v


def make_scoring_output_validator():
    """
    Returns a callable that validates Groq's scoring response.
    Expects a JSON array of {index, score, reason} objects.
    Compatible with @observe(output_validator=...).
    """
    def _validate(response: str):
        stripped = response.strip()
        if not stripped:
            raise ValueError("Empty response from Groq scorer")
        # Strip any accidental markdown fences
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            stripped = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError as e:
            raise ValueError(f"Scorer response is not valid JSON: {e}")
        if not isinstance(parsed, list):
            raise ValueError(f"Scorer response must be a JSON array, got {type(parsed).__name__}")
        for obj in parsed:
            if not isinstance(obj, dict):
                raise ValueError("Each scoring item must be a JSON object")
            if "score" not in obj:
                raise ValueError("Scoring item missing 'score' field")
    return _validate


# ---------------------------------------------------------------------------
# Validator factory — returns callables for @observe()
# ---------------------------------------------------------------------------

def make_input_validator(schema: type[BaseModel]):
    """
    Returns a callable that validates a prompt string against a Pydantic model.
    Compatible with @observe(input_validator=...).
    """
    def _validate(prompt: str):
        schema(text=prompt)
    return _validate


def make_output_validator(
    min_length: int = 5,
    forbidden_phrases: Optional[List[str]] = None,
):
    """
    Returns a callable that validates LLM output text.
    Compatible with @observe(output_validator=...).
    """
    banned = forbidden_phrases or []

    def _validate(response: str):
        LLMResponse(text=response)
        if len(response.strip()) < min_length:
            raise ValueError(f"Response too short (< {min_length} chars)")
        for phrase in banned:
            if phrase.lower() in response.lower():
                raise ValueError(f"Forbidden phrase in output: '{phrase}'")
    return _validate


# ---------------------------------------------------------------------------
# Standalone data-frame quality checks (for batch / RAG pipelines)
# ---------------------------------------------------------------------------

def check_dataframe_quality(df, checks: dict) -> dict:
    """
    Run named quality checks on a pandas DataFrame.
    checks = {
        "no_nulls_in_prompt": lambda df: df["prompt"].notna().all(),
        "latency_under_5s":   lambda df: (df["latency_ms"] < 5000).all(),
    }
    Returns {check_name: bool}.
    """
    results = {}
    for name, fn in checks.items():
        try:
            results[name] = bool(fn(df))
        except Exception:
            results[name] = False
    return results
