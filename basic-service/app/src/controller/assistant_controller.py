"""Authenticated assistant facade; all business writes use existing commands."""
from typing import Any, Literal

from fastapi import APIRouter, Query, Response
from pydantic import Field, field_validator

from .rd_dependencies import Actor, RequestBody, RdRoute
from src.service.rd_platform.runtime import get_store
from src.service.assistant.conversation import answer_question, build_context
from src.service.assistant.operations import capabilities, confirm_operation, prepare_operation

router = APIRouter(prefix='/api/assistant', tags=['小航助手'], route_class=RdRoute)


class HistoryMessage(RequestBody):
    role: Literal['user', 'assistant']
    content: str = Field(min_length=1, max_length=6000)


class ChatBody(RequestBody):
    mode: Literal['auto', 'platform', 'general'] = 'auto'
    message: str = Field(min_length=1, max_length=4000)
    history: list[HistoryMessage] = Field(default_factory=list, max_length=12)
    project_id: str | None = Field(default=None, min_length=1, max_length=128)

    @field_validator('message')
    @classmethod
    def nonempty(cls, value):
        if not value.strip():
            raise ValueError('问题不能为空')
        return value.strip()


class OperationBody(RequestBody):
    project_id: str = Field(min_length=1, max_length=128)
    action: str = Field(min_length=1, max_length=80)
    payload: dict[str, Any]


class ConfirmBody(RequestBody):
    pass


@router.get('/context')
def context(actor: Actor, response: Response, project_id: str | None = Query(default=None, min_length=1, max_length=128)):
    response.headers['Cache-Control'] = 'no-store'
    return build_context(get_store(), actor, project_id)


@router.post('/chat')
async def chat(body: ChatBody, actor: Actor, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return await answer_question(get_store(), actor, body.mode, body.message, [item.model_dump() for item in body.history], body.project_id)


@router.get('/capabilities')
def list_capabilities(actor: Actor, response: Response, project_id: str | None = Query(default=None, min_length=1, max_length=128)):
    response.headers['Cache-Control'] = 'no-store'
    if not project_id:
        return {'capabilities': []}
    return {'capabilities': capabilities(get_store().detail(project_id, actor['user_id']), actor)}


@router.post('/operations/prepare')
def prepare(body: OperationBody, actor: Actor, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return prepare_operation(get_store(), actor, body.project_id, body.action, body.payload)


@router.post('/operations/{proposal_id}/confirm')
def confirm(proposal_id: str, body: ConfirmBody, actor: Actor, response: Response):
    response.headers['Cache-Control'] = 'no-store'
    return confirm_operation(get_store(), actor, proposal_id)
