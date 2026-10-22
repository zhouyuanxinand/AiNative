"""Optional semantic retrieval helpers for the controlled template router.

This module is deliberately advisory.  Embeddings and reranking may propose
template slots, but the live template heading tree and the LLM JSON contract
remain authoritative.  No document body text is generated here.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import os
from typing import Any, Iterable
from urllib.parse import urlsplit, urlunsplit

import httpx

from . import llm_client


@dataclass(frozen=True)
class RetrievalConfig:
    embedding_url: str
    embedding_model: str = "openai/bge-m3"
    embedding_model_id: str = "5328"
    rerank_url: str = ""
    rerank_model: str = "hosted_vllm/bge-reranker-v2-m3"
    rerank_model_id: str = "5327"
    timeout_seconds: float = 30.0


def _replace_endpoint(path: str, replacement: str) -> str:
    parts = urlsplit(path)
    root = parts.path.rstrip("/")
    if root.endswith("/chat/completions"):
        root = root[: -len("/chat/completions")]
    return urlunsplit((parts.scheme, parts.netloc, f"{root}/{replacement}", "", ""))


def config_from_environment() -> RetrievalConfig | None:
    """Build retrieval settings from the configured chat client.

    The API key is never returned by this function or included in status
    payloads.  The same in-memory/environment credential is used only when an
    actual retrieval request is explicitly enabled.
    """
    try:
        config = llm_client._active_config()
    except RuntimeError:
        return None
    embedding_url = os.getenv(
        "JTB_EMBEDDING_API_URL",
        _replace_endpoint(config.endpoint, "embeddings"),
    ).strip()
    rerank_url = os.getenv(
        "JTB_RERANK_API_URL",
        _replace_endpoint(config.endpoint, "rerank"),
    ).strip()
    return RetrievalConfig(
        embedding_url=embedding_url,
        embedding_model=os.getenv("JTB_EMBEDDING_MODEL", "openai/bge-m3").strip(),
        embedding_model_id=os.getenv("JTB_EMBEDDING_MODEL_ID", "5328").strip(),
        rerank_url=rerank_url,
        rerank_model=os.getenv(
            "JTB_RERANK_MODEL", "hosted_vllm/bge-reranker-v2-m3"
        ).strip(),
        rerank_model_id=os.getenv("JTB_RERANK_MODEL_ID", "5327").strip(),
        timeout_seconds=float(os.getenv("JTB_RETRIEVAL_TIMEOUT_SECONDS", "30")),
    )


def _headers(config: Any) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if config.app_id:
        headers[config.app_id_header] = config.app_id
        headers[config.api_key_header] = config.api_key
        if config.tenant_id and config.tenant_id_header:
            headers[config.tenant_id_header] = config.tenant_id
    else:
        # The credential is used only for the outbound request, never logged.
        headers["Authorization"] = f"Bearer {config.api_key}"
    return headers


def _active_pair() -> tuple[Any, RetrievalConfig]:
    config = llm_client._active_config()
    retrieval = config_from_environment()
    if retrieval is None:
        raise RuntimeError("semantic retrieval is not configured")
    return config, retrieval


def list_embedding_models() -> dict[str, Any]:
    """Return the provider's embedding-model catalogue for an admin probe."""
    config, retrieval = _active_pair()
    endpoint = os.getenv(
        "JTB_EMBEDDING_MODELS_API_URL",
        _replace_endpoint(config.endpoint, "embedding/models"),
    ).strip()
    response = httpx.get(
        endpoint,
        headers=_headers(config),
        timeout=retrieval.timeout_seconds,
        follow_redirects=False,
    )
    response.raise_for_status()
    payload = response.json()
    return payload if isinstance(payload, dict) else {"data": payload}


def embed_texts(texts: str | Iterable[str]) -> list[list[float]]:
    """Embed one or more semantic slot descriptions."""
    config, retrieval = _active_pair()
    values = [texts] if isinstance(texts, str) else [str(x) for x in texts]
    response = httpx.post(
        retrieval.embedding_url,
        headers=_headers(config),
        json={
            "model": retrieval.embedding_model,
            "input": values if len(values) > 1 else values[0],
            "extra_parameters": llm_client.request_extra_parameters(config, model_id=retrieval.embedding_model_id),
        },
        timeout=retrieval.timeout_seconds,
        follow_redirects=False,
    )
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("data", []) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        raise RuntimeError("embedding response data is not a list")
    rows = sorted(rows, key=lambda item: int(item.get("index", 0)))
    return [list(item.get("embedding", [])) for item in rows if isinstance(item, dict)]


def rerank_documents(
    query: str, documents: Iterable[str], *, top_n: int = 12
) -> list[dict[str, Any]]:
    """Rank live template-slot descriptions; never returns generated prose."""
    config, retrieval = _active_pair()
    docs = [str(x) for x in documents]
    if not docs:
        return []
    response = httpx.post(
        retrieval.rerank_url,
        headers=_headers(config),
        json={
            "model": retrieval.rerank_model,
            "query": str(query),
            "documents": docs,
            "top_n": min(max(int(top_n), 1), len(docs)),
            "return_documents": True,
            "extra_parameters": llm_client.request_extra_parameters(config, model_id=retrieval.rerank_model_id),
        },
        timeout=retrieval.timeout_seconds,
        follow_redirects=False,
    )
    response.raise_for_status()
    payload = response.json()
    rows = payload.get("results", payload.get("data", [])) if isinstance(payload, dict) else []
    if not isinstance(rows, list):
        raise RuntimeError("rerank response results is not a list")
    normalized: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        normalized.append({
            "index": int(row.get("index", 0)),
            "score": float(row.get("relevance_score", row.get("score", 0.0))),
            "document": row.get("document", ""),
        })
    return normalized


def retrieval_status() -> dict[str, Any]:
    """Expose only non-sensitive readiness metadata for the web health page."""
    status = llm_client.get_status()
    configured = bool(status.get("configured"))
    retrieval = config_from_environment() if configured else None
    return {
        "configured": bool(retrieval and retrieval.embedding_url and retrieval.rerank_url),
        "embedding_model": retrieval.embedding_model if retrieval else "",
        "rerank_model": retrieval.rerank_model if retrieval else "",
    }


def build_slot_candidates(
    slots: list[dict[str, Any]], source_sections: list[dict[str, Any]], *, top_k: int = 12
) -> dict[str, list[str]]:
    """Return advisory slot IDs for each source section using BGE-M3.

    The IDs come from the current template scan.  Chapter numbers are never
    embedded, persisted, or used as routing keys.
    """
    if not slots or not source_sections:
        return {}
    slot_texts = [
        " / ".join(
            str(x) for x in (
                slot.get("semantic_path"),
                slot.get("heading"),
                " ".join(slot.get("instructions") or []),
                " ".join(slot.get("table_headers") or []),
            ) if x
        )
        for slot in slots
    ]
    query_texts = [
        " / ".join(
            str(x) for x in (
                section.get("semantic_path"),
                section.get("heading"),
                section.get("preview"),
            ) if x
        )
        for section in source_sections
    ]
    vectors = embed_texts([*slot_texts, *query_texts])
    if len(vectors) != len(slot_texts) + len(query_texts):
        return {}
    slot_vectors = vectors[: len(slot_texts)]
    query_vectors = vectors[len(slot_texts):]

    def cosine(left: list[float], right: list[float]) -> float:
        dot = sum(a * b for a, b in zip(left, right))
        norm_left = math.sqrt(sum(a * a for a in left))
        norm_right = math.sqrt(sum(b * b for b in right))
        return dot / (norm_left * norm_right) if norm_left and norm_right else 0.0

    result: dict[str, list[str]] = {}
    for section, query_text, query in zip(source_sections, query_texts, query_vectors):
        ranked = sorted(
            ((cosine(query, vector), slot["id"]) for slot, vector in zip(slots, slot_vectors)),
            reverse=True,
        )
        candidate_pairs = ranked[: max(top_k, 24)]
        if os.getenv("JTB_SEMANTIC_RERANK", "0").strip().lower() in {
            "1", "true", "yes", "on"
        }:
            by_id = {slot["id"]: text for slot, text in zip(slots, slot_texts)}
            reranked = rerank_documents(
                query_text, [by_id[sid] for _score, sid in candidate_pairs], top_n=top_k
            )
            ids = []
            for item in reranked:
                index = int(item.get("index", -1))
                if 0 <= index < len(candidate_pairs):
                    ids.append(candidate_pairs[index][1])
            result[str(section["source_section_id"])] = list(dict.fromkeys(ids))
        else:
            result[str(section["source_section_id"])] = [sid for _score, sid in candidate_pairs[:top_k]]
    return result
