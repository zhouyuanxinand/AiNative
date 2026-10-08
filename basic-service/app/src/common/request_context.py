from __future__ import annotations

from contextvars import ContextVar

# Per-request correlation id, injected by the CorrelationId middleware and
# surfaced in structured logs so a full request can be traced end-to-end.
correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="-")

# Background generation runs outside the request middleware lifecycle.  These
# values let every logger used by the pipeline (including the LLM client) carry
# the active task and stable stage without passing diagnostic fields through
# every business function.
job_id_var: ContextVar[str] = ContextVar("job_id", default="-")
job_stage_var: ContextVar[str] = ContextVar("job_stage", default="-")
