from __future__ import annotations

from contextvars import ContextVar

# Per-request correlation id, injected by the CorrelationId middleware and
# surfaced in structured logs so a full request can be traced end-to-end.
correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="-")
