"""Global assistant boundary, sharing RD authentication and same-origin rules."""
from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.controller.rd_controller import RdRoute, _actor, _key, _store
from src.service.rd_platform.platform_chat import ask_platform
from src.service.rd_platform.platform_conversations import PlatformConversations


router = APIRouter(route_class=RdRoute)


class HistoryMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class PlatformQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    message: str = Field(min_length=1, max_length=2000)
    history: list[HistoryMessage] = Field(default_factory=list, max_length=12)

    @field_validator("message")
    @classmethod
    def nonempty_message(cls, value):
        if not value.strip() or "\x00" in value:
            raise ValueError("请先填写要询问的问题")
        return value.strip()


@router.post("/assistant/chat")
async def platform_chat(payload: PlatformQuestion, request: Request):
    return await asyncio.to_thread(ask_platform, _actor(request), payload.message,
                                   [row.model_dump() for row in payload.history])


class CreateConversation(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    source_id: str | None = Field(default=None, min_length=1, max_length=128)


class ConversationQuestion(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    message: str = Field(min_length=1, max_length=2000)
    expected_version: int = Field(ge=1)

    @field_validator('message')
    @classmethod
    def nonempty_message(cls, value):
        return PlatformQuestion.nonempty_message(value)


class CloseConversation(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    choice: Literal['keep', 'end']
    draft: str = Field(max_length=2000)
    expected_version: int = Field(ge=1)


async def _conversation_call(request, method, *args, **kwargs):
    path, actor = _store(request).path, _actor(request)
    def call():
        return getattr(PlatformConversations(path), method)(actor, *args, **kwargs)
    return await asyncio.to_thread(call)


@router.get('/assistant/conversations')
async def list_conversations(request: Request, page: int = Query(default=1, ge=1)):
    return await _conversation_call(request, 'list', page)


@router.get('/assistant/conversations/{conversation_id}')
async def get_conversation(conversation_id: str, request: Request, before: int | None = Query(default=None, ge=1)):
    return await _conversation_call(request, 'get', conversation_id, before=before)


@router.post('/assistant/conversations')
async def create_conversation(payload: CreateConversation, request: Request):
    return await _conversation_call(request, 'create', _key(request), payload.source_id)


@router.post('/assistant/conversations/{conversation_id}/messages')
async def ask_conversation(conversation_id: str, payload: ConversationQuestion, request: Request):
    return await _conversation_call(request, 'ask', conversation_id, payload.message, payload.expected_version, _key(request))


@router.post('/assistant/conversations/{conversation_id}/close')
async def close_conversation(conversation_id: str, payload: CloseConversation, request: Request):
    return await _conversation_call(request, 'close', conversation_id, payload.choice, payload.draft,
                                    payload.expected_version, _key(request))
