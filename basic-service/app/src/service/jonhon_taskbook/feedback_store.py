"""Transactional feedback records shared by the generation and administration apps."""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from pathlib import Path

RATINGS = {"good", "average", "poor"}
STATUSES = {"open", "in_progress", "resolved"}
_PUBLIC_FIELDS = {"jid", "username", "rating", "comment", "request_id"}
_EDIT_FIELDS = {"username", "rating", "comment", "status", "handling_note"}


class FeedbackConflictError(RuntimeError):
    """A retry changed its contents or an administrator edited a stale version."""


def _now():
    return datetime.now(timezone.utc).isoformat()


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def database_path() -> Path:
    default = Path(__file__).resolve().parents[3] / "runtime/feedback.sqlite3"
    return Path(os.getenv("JTB_FEEDBACK_DB") or default).resolve()


@lru_cache(maxsize=8)
def _store(path: str):
    return FeedbackStore(path)


def get_feedback_store():
    return _store(str(database_path()))


def _text(payload, key, limit, *, required=False, default=""):
    value = payload.get(key, default)
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError(f"{key} 必须是最多 {limit} 个字符的文本。")
    value = value.strip()
    if required and not value:
        raise ValueError(f"请填写 {key}。")
    return value


def _integer(value, name, *, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1 or (maximum and value > maximum):
        raise ValueError(f"{name} 超出允许范围。")
    return value


def _values(payload, *, create=False, admin=False):
    if not isinstance(payload, dict):
        raise ValueError("请提交完整的反馈记录。")  # noqa: TRY004 - request validation uses ValueError throughout.
    allowed = (_PUBLIC_FIELDS | ({"status", "handling_note"} if admin else set())) if create else _EDIT_FIELDS | {"expected_version"}
    if set(payload) - allowed:
        raise ValueError("请求包含不允许修改的字段。")
    result = {}
    for key, limit in (("username", 80), ("comment", 4000), ("handling_note", 4000)):
        if key in payload or (create and key in {"username", "comment"}):
            result[key] = _text(payload, key, limit, required=key == "username")
    if "rating" in payload or create:
        rating = payload.get("rating")
        if not isinstance(rating, str) or rating not in RATINGS:
            raise ValueError("评价必须是 good、average 或 poor。")
        result["rating"] = rating
    if "status" in payload:
        status = payload["status"]
        if not isinstance(status, str) or status not in STATUSES:
            raise ValueError("无效的处理状态。")
        result["status"] = status
    if create:
        result["jid"] = _text(payload, "jid", 80, required=True)
        request_id = _text(payload, "request_id", 80)
        if request_id:
            try:
                request_id = str(uuid.UUID(request_id))
            except (ValueError, AttributeError) as exc:
                raise ValueError("request_id 必须是有效的 UUID。") from exc
        result["request_id"] = request_id or None
        result.setdefault("status", "open")
        result.setdefault("handling_note", "")
    else:
        result["expected_version"] = _integer(payload.get("expected_version"), "expected_version")
        if not set(result) & _EDIT_FIELDS:
            raise ValueError("请提供需要修改的反馈字段。")
    return result


def validate_create(payload, *, admin=False):
    """Validate before resolving a task or touching the database."""
    return _values(payload, create=True, admin=admin)


def _date_bound(value, *, end=False):
    if not isinstance(value, str):
        raise ValueError("日期必须是 ISO 日期或时间。")  # noqa: TRY004 - a filter validation failure.
    if not value:
        return None, False
    try:
        if len(value) == 10:
            parsed_date = date.fromisoformat(value)
            parsed = datetime.combine(parsed_date, time.min, timezone.utc)
            return (parsed + timedelta(days=1) if end else parsed).isoformat(), end
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("时间必须包含时区。")
        return parsed.astimezone(timezone.utc).isoformat(), False
    except (ValueError, OverflowError) as exc:
        raise ValueError("请提供有效的 ISO 日期或带时区的时间。") from exc


class FeedbackStore:
    def __init__(self, path):
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection(write=True) as con:
            con.execute("""CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                username TEXT NOT NULL, rating TEXT NOT NULL, comment TEXT NOT NULL,
                status TEXT NOT NULL, handling_note TEXT NOT NULL,
                snapshot TEXT NOT NULL, identity TEXT NOT NULL DEFAULT '{}', search_text TEXT NOT NULL,
                request_id TEXT UNIQUE, request_payload TEXT NOT NULL,
                deleted_at TEXT
            )""")
            columns = {row["name"] for row in con.execute("PRAGMA table_info(feedback)")}
            if "identity" not in columns:
                con.execute("ALTER TABLE feedback ADD COLUMN identity TEXT NOT NULL DEFAULT '{}'")
            con.execute("CREATE INDEX IF NOT EXISTS feedback_filters ON feedback(deleted_at, rating, status, created_at)")

    @contextmanager
    def _connection(self, *, write=False):
        con = sqlite3.connect(self.path, timeout=30)
        con.row_factory = sqlite3.Row
        try:
            con.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield con
            con.commit()
        except Exception:
            con.rollback()
            raise
        finally:
            con.close()

    @staticmethod
    def _record(row):
        return {key: json.loads(row[key]) if key in {"snapshot", "identity"} else row[key]
                for key in ("id", "version", "created_at", "updated_at", "username", "rating", "comment", "status", "handling_note", "snapshot", "identity")}

    @staticmethod
    def _row(con, record_id):
        _integer(record_id, "id")
        row = con.execute("SELECT * FROM feedback WHERE id=? AND deleted_at IS NULL", (record_id,)).fetchone()
        if not row:
            raise FileNotFoundError("反馈记录不存在或已删除。")
        return row

    def get(self, record_id):
        with self._connection() as con:
            return self._record(self._row(con, record_id))

    def create(self, payload, *, snapshot, admin=False, identity=None):
        values = _values(payload, create=True, admin=admin)
        if not isinstance(snapshot, dict) or snapshot.get("jid") != values["jid"]:
            raise ValueError("任务快照与反馈任务不匹配。")
        # Only internal callers can supply identity, and credentials never enter
        # the stored allowlist. Historical rows retain an empty identity object.
        saved_identity = ({"userid": "", "name": values["username"], "source": "manual", "verified": False}
                          if identity is None else {key: identity[key] for key in ("userid", "name", "source", "verified")})
        # Manual submissions keep their historical retry format. Verified retries
        # bind to the account even if its name or an administrator's display text changes.
        request_values = values
        if identity is not None:
            request_values = {key: value for key, value in values.items() if key != "username"}
            request_values["identity"] = {key: saved_identity[key] for key in ("userid", "source", "verified")}
        request_payload = _json(request_values)
        with self._connection(write=True) as con:
            if values["request_id"]:
                existing = con.execute("SELECT * FROM feedback WHERE request_id=?", (values["request_id"],)).fetchone()
                if existing:
                    if existing["request_payload"] != request_payload or existing["deleted_at"]:
                        raise FeedbackConflictError("该提交标识已用于其他内容，或反馈记录已删除。")
                    return self._record(existing)
            now = _now()
            snapshot_json = _json(snapshot)
            identity_json = _json(saved_identity)
            search_text = "\n".join([values["username"], values["comment"], values["handling_note"], snapshot_json, identity_json])
            cursor = con.execute("""INSERT INTO feedback
                (created_at,updated_at,username,rating,comment,status,handling_note,snapshot,identity,search_text,request_id,request_payload)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (now, now, values["username"], values["rating"], values["comment"],
                values["status"], values["handling_note"], snapshot_json, identity_json, search_text, values["request_id"], request_payload))
            return self._record(self._row(con, cursor.lastrowid))

    def update(self, record_id, payload):
        values = _values(payload)
        expected = values.pop("expected_version")
        with self._connection(write=True) as con:
            existing = self._row(con, record_id)
            if existing["version"] != expected:
                raise FeedbackConflictError("反馈已被其他操作更新，请刷新后重试。")
            updated = {**dict(existing), **values}
            values["search_text"] = "\n".join([updated["username"], updated["comment"], updated["handling_note"], existing["snapshot"], existing["identity"]])
            values["updated_at"] = _now()
            assignments = ",".join(f"{key}=?" for key in values)
            con.execute(f"UPDATE feedback SET {assignments},version=version+1 WHERE id=?", [*values.values(), record_id])
            return self._record(self._row(con, record_id))

    def delete(self, record_id, expected_version):
        _integer(expected_version, "expected_version")
        with self._connection(write=True) as con:
            existing = self._row(con, record_id)
            if existing["version"] != expected_version:
                raise FeedbackConflictError("反馈已被其他操作更新，请刷新后重试。")
            con.execute("UPDATE feedback SET deleted_at=?,updated_at=?,version=version+1 WHERE id=?", (_now(), _now(), record_id))
            return {"ok": True}

    def search(self, *, q="", rating="", status="", date_from="", date_to="", page=1, page_size=20):
        _integer(page, "page")
        _integer(page_size, "page_size", maximum=100)
        if not isinstance(q, str) or len(q) > 500:
            raise ValueError("搜索词最多 500 个字符。")
        if not isinstance(rating, str) or (rating and rating not in RATINGS):
            raise ValueError("无效的评价筛选。")
        if not isinstance(status, str) or (status and status not in STATUSES):
            raise ValueError("无效的状态筛选。")
        start, _ = _date_bound(date_from)
        end, end_exclusive = _date_bound(date_to, end=True)
        if start and end and (start >= end if end_exclusive else start > end):
            raise ValueError("开始日期不能晚于结束日期。")
        conditions, args = ["deleted_at IS NULL"], []
        if q.strip():
            conditions.append("instr(lower(search_text), lower(?)) > 0")
            args.append(q.strip())
        for key, value in (("rating", rating), ("status", status)):
            if value:
                conditions.append(f"{key}=?")
                args.append(value)
        if start:
            conditions.append("created_at >= ?")
            args.append(start)
        if end:
            conditions.append("created_at < ?" if end_exclusive else "created_at <= ?")
            args.append(end)
        where = " AND ".join(conditions)
        with self._connection() as con:
            counts = con.execute(f"""SELECT count(*) AS total,
                coalesce(sum(rating='good'),0) AS good,coalesce(sum(rating='average'),0) AS average,
                coalesce(sum(rating='poor'),0) AS poor,coalesce(sum(status='open'),0) AS open,
                coalesce(sum(status='in_progress'),0) AS in_progress,coalesce(sum(status='resolved'),0) AS resolved
                FROM feedback WHERE {where}""", args).fetchone()
            stats = dict(counts)
            stats["good_rate"] = stats["good"] / stats["total"] if stats["total"] else 0.0
            rows = con.execute(f"SELECT * FROM feedback WHERE {where} ORDER BY id DESC LIMIT ? OFFSET ?", [*args, page_size, (page - 1) * page_size]).fetchall()
            return {"items": [self._record(row) for row in rows], "total": stats["total"],
                    "page": page, "page_size": page_size, "stats": stats}
