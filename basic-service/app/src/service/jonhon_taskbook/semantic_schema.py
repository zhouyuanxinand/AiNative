from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class SourceBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    source: Literal["tech", "spec"]
    source_path: str
    chapter_id: str
    section: str
    heading_number: str = ""
    heading_text: str = ""
    parent_headings: list[str] = Field(default_factory=list)
    type: Literal["paragraph", "table"]
    body_index: int = Field(ge=0)
    text: str
    content_hash: str = Field(min_length=64, max_length=64)
    has_drawing: bool = False
    # A figure and its immediately adjacent caption are copied as one atomic
    # media group.  These fields are structural provenance, not generated
    # document content, but they must be part of the validated plan schema.
    media_group_id: str = ""
    media_group_members: list[str] = Field(default_factory=list)
    # A paragraph may contain several independent semantic facts.  In that
    # case the classifier is allowed to partition its *existing* text into
    # exact, non-overlapping spans.  The model still cannot generate text:
    # concatenating all sibling fragments must reproduce the parent text.
    is_fragment: bool = False
    parent_source_id: str = ""
    fragment_index: int = Field(default=-1, ge=-1)
    source_span_start: int = Field(default=-1, ge=-1)
    source_span_end: int = Field(default=-1, ge=-1)
    element_content_hash: str = ""


class TemplateSlot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    heading: str
    title: str = ""
    semantic_path: str = ""
    level: int = Field(default=1, ge=1, le=9)
    parent_id: str = ""
    paragraph_index: int = Field(default=-1, ge=-1)
    occurrence: int = Field(default=1, ge=1)
    instructions: list[str] = Field(default_factory=list)
    has_table: bool = False
    table_headers: list[str] = Field(default_factory=list)


class RouteDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_slot: str
    source_ids: list[str]
    operation: Literal["copy_exact"]
    edit_action: Literal[
        "append", "replace", "insert_before", "insert_after", "preserve", "delete"
    ] = "append"
    anchor_slot: str = ""
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str = ""


class SemanticPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")
    llm_may_generate_text: Literal[False] = False
    allowed_operations: list[Literal["copy_exact"]] = Field(
        default_factory=lambda: ["copy_exact"]
    )
    allowed_edit_actions: list[
        Literal["append", "replace", "insert_before", "insert_after", "preserve", "delete"]
    ] = Field(
        default_factory=lambda: [
            "append", "replace", "insert_before", "insert_after", "preserve", "delete"
        ]
    )
    delete_requires_explicit_rule: Literal[True] = True


class SemanticPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: str
    policy: SemanticPolicy
    roles: dict[str, Any]
    scope: dict[str, Any]
    slots: list[TemplateSlot]
    source_blocks: list[SourceBlock]
    section_mappings: list[dict[str, Any]]
    decisions: list[RouteDecision]
    route_audit: dict[str, Any] = Field(default_factory=dict)
