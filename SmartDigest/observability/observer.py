"""
GenAI Observability Core — observer.py
Wraps any LLM call with tracing, metrics, validation, and logging.
Works with OpenAI, Anthropic, LangChain, Groq, or raw HTTP calls.
"""

import time
import uuid
import json
import functools
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional
from dataclasses import dataclass, field, asdict

import structlog
from prometheus_client import Counter, Histogram, Gauge

# ---------------------------------------------------------------------------
# Structured logger (JSON output)
# ---------------------------------------------------------------------------
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.add_log_level,
        structlog.processors.JSONRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(20),  # INFO+
)
log = structlog.get_logger("genai.observer")


# ---------------------------------------------------------------------------
# Prometheus metrics (auto-registered on import)
# ---------------------------------------------------------------------------
LLM_CALL_COUNT = Counter(
    "llm_calls_total",
    "Total LLM API calls",
    ["model", "usecase", "status"],
)
LLM_LATENCY = Histogram(
    "llm_latency_seconds",
    "End-to-end LLM call latency",
    ["model", "usecase"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)
TOKEN_USAGE = Counter(
    "llm_tokens_total",
    "Total tokens consumed",
    ["model", "usecase", "token_type"],  # token_type: prompt / completion
)
ERROR_COUNT = Counter(
    "llm_errors_total",
    "LLM errors by type",
    ["model", "usecase", "error_type"],
)
DATA_QUALITY_FAILURES = Counter(
    "data_quality_failures_total",
    "Input/output validation failures",
    ["usecase", "check_name"],
)
ACTIVE_REQUESTS = Gauge(
    "llm_active_requests",
    "Currently in-flight LLM requests",
    ["usecase"],
)


# ---------------------------------------------------------------------------
# Trace record (persisted to SQLite)
# ---------------------------------------------------------------------------
@dataclass
class LLMTrace:
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    usecase: str = "default"
    model: str = "unknown"
    prompt: str = ""
    response: str = ""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    status: str = "ok"          # ok | error | timeout | validation_fail
    error_message: str = ""
    cost_usd: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Cost estimator (extend with current pricing)
# ---------------------------------------------------------------------------
COST_PER_1K_TOKENS: Dict[str, Dict[str, float]] = {
    "gpt-4o":                       {"prompt": 0.005,    "completion": 0.015},
    "gpt-4o-mini":                  {"prompt": 0.00015,  "completion": 0.0006},
    "gpt-3.5-turbo":                {"prompt": 0.0005,   "completion": 0.0015},
    "claude-3-5-sonnet":            {"prompt": 0.003,    "completion": 0.015},
    "claude-3-haiku":               {"prompt": 0.00025,  "completion": 0.00125},
    "claude-sonnet-4-6":            {"prompt": 0.003,    "completion": 0.015},
    "gemini-1.5-pro":               {"prompt": 0.00125,  "completion": 0.005},
    # Groq-hosted open models (free tier — $0 but track for comparison)
    "llama-3.3-70b-versatile":      {"prompt": 0.0,      "completion": 0.0},
    "llama-3.1-8b-instant":         {"prompt": 0.0,      "completion": 0.0},
    "mixtral-8x7b-32768":           {"prompt": 0.0,      "completion": 0.0},
    "gemma2-9b-it":                 {"prompt": 0.0,      "completion": 0.0},
}


def estimate_cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    pricing = COST_PER_1K_TOKENS.get(model, {"prompt": 0.001, "completion": 0.002})
    return (
        prompt_tokens * pricing["prompt"] / 1000
        + completion_tokens * pricing["completion"] / 1000
    )


# ---------------------------------------------------------------------------
# Main decorator — wrap any LLM call function
# ---------------------------------------------------------------------------
def observe(
    usecase: str = "default",
    model: str = "unknown",
    store: Optional["TraceStore"] = None,
    langfuse_client=None,
    input_validator: Optional[Callable] = None,
    output_validator: Optional[Callable] = None,
):
    """
    Decorator that instruments an LLM call with:
    - Latency + token metrics (Prometheus)
    - Structured JSON logging (structlog)
    - Trace persistence (SQLite via TraceStore)
    - Input/output validation

    Usage:
        @observe(usecase="relevance-scorer", model="llama-3.3-70b-versatile", store=my_store)
        def call_llm(prompt: str) -> dict:
            ...  # must return {"response": str, "prompt_tokens": int, "completion_tokens": int}
    """
    def decorator(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs) -> Any:
            trace = LLMTrace(usecase=usecase, model=model)

            # Extract prompt string if first arg is str or kwargs has 'prompt'
            raw_prompt = kwargs.get("prompt") or (args[0] if args and isinstance(args[0], str) else "")
            trace.prompt = raw_prompt[:4000]  # cap for storage

            # --- input validation ---
            if input_validator:
                try:
                    input_validator(raw_prompt)
                except Exception as ve:
                    DATA_QUALITY_FAILURES.labels(usecase=usecase, check_name="input").inc()
                    log.warning("input_validation_failed", usecase=usecase, error=str(ve))

            ACTIVE_REQUESTS.labels(usecase=usecase).inc()
            t0 = time.perf_counter()

            try:
                result = fn(*args, **kwargs)

                latency = (time.perf_counter() - t0) * 1000
                trace.latency_ms = round(latency, 2)
                trace.status = "ok"

                # Unpack result
                if isinstance(result, dict):
                    trace.response = str(result.get("response", ""))[:4000]
                    trace.prompt_tokens = result.get("prompt_tokens", 0)
                    trace.completion_tokens = result.get("completion_tokens", 0)
                    trace.total_tokens = trace.prompt_tokens + trace.completion_tokens
                    trace.metadata = result.get("metadata", {})
                else:
                    trace.response = str(result)[:4000]

                trace.cost_usd = estimate_cost(model, trace.prompt_tokens, trace.completion_tokens)

                # --- output validation ---
                if output_validator:
                    try:
                        output_validator(trace.response)
                    except Exception as ve:
                        DATA_QUALITY_FAILURES.labels(usecase=usecase, check_name="output").inc()
                        log.warning("output_validation_failed", usecase=usecase, error=str(ve))
                        trace.status = "validation_fail"

                # Prometheus
                LLM_CALL_COUNT.labels(model=model, usecase=usecase, status="ok").inc()
                LLM_LATENCY.labels(model=model, usecase=usecase).observe(latency / 1000)
                TOKEN_USAGE.labels(model=model, usecase=usecase, token_type="prompt").inc(trace.prompt_tokens)
                TOKEN_USAGE.labels(model=model, usecase=usecase, token_type="completion").inc(trace.completion_tokens)

                log.info(
                    "llm_call_ok",
                    trace_id=trace.trace_id,
                    usecase=usecase,
                    model=model,
                    latency_ms=trace.latency_ms,
                    total_tokens=trace.total_tokens,
                    cost_usd=round(trace.cost_usd, 6),
                )

                return result

            except Exception as exc:
                latency = (time.perf_counter() - t0) * 1000
                trace.latency_ms = round(latency, 2)
                trace.status = "error"
                trace.error_message = str(exc)

                ERROR_COUNT.labels(model=model, usecase=usecase, error_type=type(exc).__name__).inc()
                LLM_CALL_COUNT.labels(model=model, usecase=usecase, status="error").inc()

                log.error(
                    "llm_call_failed",
                    trace_id=trace.trace_id,
                    usecase=usecase,
                    model=model,
                    error=str(exc),
                    latency_ms=trace.latency_ms,
                )
                raise

            finally:
                ACTIVE_REQUESTS.labels(usecase=usecase).dec()

                # Persist trace
                if store:
                    store.save(trace)

                if langfuse_client:
                    _send_to_langfuse(langfuse_client, trace)

        return wrapper
    return decorator


def _send_to_langfuse(client, trace: LLMTrace):
    """Push trace to Langfuse via HTTP API (no SDK required)."""
    try:
        ok = client.send_generation(
            trace_id=trace.trace_id,
            name=trace.usecase,
            model=trace.model,
            input_text=trace.prompt,
            output_text=trace.response,
            prompt_tokens=trace.prompt_tokens,
            completion_tokens=trace.completion_tokens,
            latency_ms=trace.latency_ms,
            status=trace.status,
            error_message=trace.error_message,
            metadata={"cost_usd": trace.cost_usd, **trace.metadata},
        )
        if ok:
            log.info("langfuse_trace_sent", trace_id=trace.trace_id, usecase=trace.usecase)
        else:
            log.warning("langfuse_trace_failed", trace_id=trace.trace_id)
    except Exception as e:
        log.warning("langfuse_push_failed", error=str(e))
