"""Persistent, editable failure evidence shared by the UI and generation."""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
FIELDS = {
    "product_type": ("产品类型", 120), "product_name": ("数据所属产品", 500),
    "product_series": ("产品系列", 200), "product_model": ("所属型号", 2000),
    "failure_location": ("失效部位", 500), "failure_mode": ("故障现象", 20000),
    "failure_analysis": ("故障原因", 20000), "improvement": ("改进措施与经验", 20000),
}


class FailureConflictError(RuntimeError):
    pass


def _now():
    return datetime.now(timezone.utc).isoformat()


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def database_path() -> Path:
    return Path(os.getenv("JTB_FAILURE_DATABASE_PATH") or ROOT.parents[2] / "runtime/failure_database.sqlite3").resolve()


@lru_cache(maxsize=8)
def _database(path: str):
    return FailureDatabase(path)


def get_failure_database():
    return _database(str(database_path()))


class FailureDatabase:
    def __init__(self, path, *, seed_path=None, catalog_path=None):
        self.path = Path(path).resolve()
        self.seed_path = Path(seed_path or ROOT / "resources/mappings/failure_mode_database_20260722.xlsx")
        self.catalog_path = Path(catalog_path or ROOT.parent / "config/template_catalog.yaml")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connection(self, *, write=False):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _products(self):
        catalog = yaml.safe_load(self.catalog_path.read_text(encoding="utf-8"))
        return {key: value.get("label", key) for key, value in catalog["product_types"].items()}

    def _initialize(self):
        with self._connection(write=True) as con:
            con.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            columns = ", ".join(f"{field} TEXT NOT NULL DEFAULT ''" for field in FIELDS)
            con.execute(f"""CREATE TABLE IF NOT EXISTS failures (
                id INTEGER PRIMARY KEY AUTOINCREMENT, {columns},
                version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                source_file TEXT NOT NULL DEFAULT '', source_sheet TEXT NOT NULL DEFAULT '',
                source_row INTEGER, source_data TEXT NOT NULL DEFAULT '{{}}', deleted_at TEXT)
            """)
            con.execute("""CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT, record_id INTEGER NOT NULL,
                action TEXT NOT NULL, at TEXT NOT NULL, before_data TEXT, after_data TEXT)
            """)
            con.execute("CREATE INDEX IF NOT EXISTS failures_product ON failures(product_type, deleted_at)")
            if con.execute("SELECT 1 FROM metadata WHERE key='seed_sha256'").fetchone():
                return
            # Keep every original column for provenance; infer no series aliases.
            from .failure_mode_matcher import _database_rows, _parent_product_name, _failure_location, _product_name_matches
            products = self._products()
            audit = {"data_sheets": []}
            count, now = 0, _now()
            for sheet, row_number, values in _database_rows(self.seed_path, audit, include_extra=True):
                source_name, model = values["数据所属产品的产品名称"], values["所属型号"]
                if not source_name and not model:
                    continue
                matches = [(key, label) for key, label in products.items() if _product_name_matches(label, source_name)]
                product_type = max(matches, key=lambda item: len(item[1]))[0] if matches else ""
                record = {
                    "product_type": product_type, "product_name": _parent_product_name(source_name),
                    "product_series": "", "product_model": model,
                    "failure_location": _failure_location(source_name), "failure_mode": values["故障描述"],
                    "failure_analysis": values["故障原因"], "improvement": values["设计改进措施"],
                    "created_at": now, "updated_at": now,
                    "source_file": self.seed_path.name, "source_sheet": sheet, "source_row": row_number,
                    "source_data": _json(values),
                }
                self._insert(con, record)
                count += 1
            con.executemany("INSERT INTO metadata(key,value) VALUES (?,?)", [
                ("seed_sha256", hashlib.sha256(self.seed_path.read_bytes()).hexdigest()),
                ("seed_file", self.seed_path.name), ("seed_count", str(count)), ("revision", "1"),
            ])

    @staticmethod
    def _insert(con, data):
        columns = ",".join(data)
        return con.execute(f"INSERT INTO failures({columns}) VALUES ({','.join('?' for _ in data)})", list(data.values())).lastrowid

    @staticmethod
    def _record(row, *, detail=True):
        result = dict(row)
        raw = result.pop("source_data", "{}")
        if detail:
            result["source_data"] = json.loads(raw)
        return result

    def _get(self, con, record_id):
        row = con.execute("SELECT * FROM failures WHERE id=? AND deleted_at IS NULL", (record_id,)).fetchone()
        if row is None:
            raise FileNotFoundError("故障记录不存在或已删除，请刷新列表。")
        return self._record(row)

    def get(self, record_id):
        with self._connection() as con:
            return self._get(con, record_id)

    def options(self):
        with self._connection() as con:
            counts = dict(con.execute("SELECT product_type, COUNT(*) FROM failures WHERE deleted_at IS NULL GROUP BY product_type").fetchall())
            meta = dict(con.execute("SELECT key,value FROM metadata").fetchall())
        return {"products": [{"id": key, "label": label, "count": counts.get(key, 0)} for key, label in self._products().items()],
                "unclassified_count": counts.get("", 0), "total": sum(counts.values()),
                "source_file": meta["seed_file"], "imported_count": int(meta["seed_count"])}

    def search(self, *, q="", product_type="", series="", page=1, page_size=20):
        if page < 1 or not 1 <= page_size <= 100:
            raise ValueError("页码须大于 0，每页最多 100 条。")
        clauses, args = ["deleted_at IS NULL"], []
        if product_type:
            clauses.append("product_type=?")
            args.append("" if product_type == "__unclassified__" else product_type)
        def like(value):
            return "%" + value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        if q.strip():
            columns = [field for field in FIELDS if field != "product_type"]
            clauses.append("(" + " OR ".join(f"{field} LIKE ? ESCAPE '\\'" for field in columns) + ")")
            args.extend([like(q.strip())] * len(columns))
        if series.strip():
            clauses.append("(product_series LIKE ? ESCAPE '\\' OR product_model LIKE ? ESCAPE '\\')")
            args.extend([like(series.strip())] * 2)
        where = " AND ".join(clauses)
        with self._connection() as con:
            total = con.execute(f"SELECT COUNT(*) FROM failures WHERE {where}", args).fetchone()[0]
            rows = con.execute(f"SELECT * FROM failures WHERE {where} ORDER BY updated_at DESC,id DESC LIMIT ? OFFSET ?",
                               [*args, page_size, (page - 1) * page_size]).fetchall()
        return {"items": [self._record(row, detail=False) for row in rows], "total": total,
                "page": page, "page_size": page_size, "pages": max(1, (total + page_size - 1) // page_size)}

    def _validate(self, payload, previous=None):
        if not isinstance(payload, dict) or set(payload) - (set(FIELDS) | {"expected_version"}):
            raise ValueError("故障记录包含无法识别的字段。")
        data = {}
        for name, (label, limit) in FIELDS.items():
            value = payload.get(name, "")
            if not isinstance(value, str) or "\0" in value or len(value) > limit:
                raise ValueError(f"{label}须为文字，且不超过 {limit} 字。")
            data[name] = value.replace("\r\n", "\n").strip()
        if data["product_type"] and data["product_type"] not in self._products():
            raise ValueError("请选择目录中的产品类型。")
        if previous is None and not data["product_type"]:
            raise ValueError("请选择产品类型。")
        if not data["product_name"] or not data["failure_mode"]:
            raise ValueError("请填写数据所属产品和故障现象。")
        if not data["product_series"] and not data["product_model"]:
            raise ValueError("请至少填写产品系列或所属型号。")
        return data

    @staticmethod
    def _check_version(previous, expected_version):
        if type(expected_version) is not int or expected_version != previous["version"]:
            raise FailureConflictError("记录已被其他操作更新，请重新打开最新记录后修改。")

    @staticmethod
    def _event(con, record_id, action, before, after):
        con.execute("INSERT INTO events(record_id,action,at,before_data,after_data) VALUES (?,?,?,?,?)",
                    (record_id, action, _now(), _json(before) if before else None, _json(after) if after else None))
        con.execute("UPDATE metadata SET value=CAST(value AS INTEGER)+1 WHERE key='revision'")

    def create(self, payload):
        data, now = self._validate(payload), _now()
        with self._connection(write=True) as con:
            record_id = self._insert(con, {**data, "created_at": now, "updated_at": now})
            result = self._get(con, record_id)
            self._event(con, record_id, "create", None, result)
            return result

    def update(self, record_id, payload):
        with self._connection(write=True) as con:
            previous = self._get(con, record_id)
            self._check_version(previous, payload.get("expected_version"))
            data = self._validate(payload, previous)
            data.update(updated_at=_now(), version=previous["version"] + 1)
            con.execute(f"UPDATE failures SET {','.join(field + '=?' for field in data)} WHERE id=?",
                        [*data.values(), record_id])
            result = self._get(con, record_id)
            self._event(con, record_id, "update", previous, result)
            return result

    def delete(self, record_id, expected_version):
        with self._connection(write=True) as con:
            previous = self._get(con, record_id)
            self._check_version(previous, expected_version)
            con.execute("UPDATE failures SET deleted_at=?,version=version+1 WHERE id=?", (_now(), record_id))
            self._event(con, record_id, "delete", previous, None)
        return {"deleted": True, "id": record_id}

    def snapshot(self):
        """One SQLite read transaction gives each generation a consistent view."""
        with self._connection() as con:
            rows = [self._record(row) for row in con.execute("SELECT * FROM failures WHERE deleted_at IS NULL ORDER BY id")]
            revision = int(con.execute("SELECT value FROM metadata WHERE key='revision'").fetchone()[0])
        digest = hashlib.sha256(_json(rows).encode("utf-8")).hexdigest()
        return rows, {"database": str(self.path), "database_revision": revision, "database_sha256": digest}

    def matching_rows(self, audit):
        records, identity = self.snapshot()
        audit.update(identity)
        products = self._products()
        audit["data_sheets"].append({"name": "故障数据库", "header_row": 0})
        for record in records:
            source_name = record["product_name"] + ("-" + record["failure_location"] if record["failure_location"] else "")
            yield record["source_sheet"] or "故障数据库", record["source_row"] or record["id"], {
                "数据所属产品的产品名称": source_name, "所属型号": record["product_model"] or record["product_series"],
                "故障描述": record["failure_mode"], "故障原因": record["failure_analysis"], "设计改进措施": record["improvement"],
                "controlled_product_label": products.get(record["product_type"], ""),
                "controlled_series": record["product_series"], "product_name": record["product_name"],
                "failure_location": record["failure_location"], "record_id": record["id"], "record_version": record["version"],
            }
