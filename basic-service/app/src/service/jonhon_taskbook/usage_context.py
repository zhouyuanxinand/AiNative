"""Request-local OA identity used for MaaS usage attribution, never credentials."""
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Iterator


model_user_id_var: ContextVar[str] = ContextVar("model_user_id", default="")


@contextmanager
def model_user_scope(userid: str = "") -> Iterator[None]:
    """Keep identity isolated across requests and inherited background work."""
    token = model_user_id_var.set(userid)
    try:
        yield
    finally:
        model_user_id_var.reset(token)
