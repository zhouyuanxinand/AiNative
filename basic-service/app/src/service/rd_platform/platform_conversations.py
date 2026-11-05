"""Actor-owned platform conversations, with durable receipts and fenced model calls."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .assistant import _safe, _text
from .platform_chat import ask_platform
from .store import RdError

PAGE_SIZE = 20
MESSAGE_PAGE_SIZE = 40
PENDING_SECONDS = 60


def _now():
    return datetime.now(timezone.utc).isoformat()


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def _fingerprint(operation, conversation_id, payload):
    return hashlib.sha256(_json([operation, conversation_id, payload]).encode('utf-8')).hexdigest()


def _version(value):
    if type(value) is not int or value < 1:
        raise RdError(422, '会话版本必须为正整数。')
    return value


class PlatformConversations:
    def __init__(self, path):
        self.path = Path(path)
        with self._db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS rd_platform_conversations(
                    id TEXT PRIMARY KEY, actor TEXT NOT NULL, title TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    message_count INTEGER NOT NULL DEFAULT 0, source_id TEXT,
                    version INTEGER NOT NULL DEFAULT 1, draft TEXT NOT NULL DEFAULT '');
                CREATE INDEX IF NOT EXISTS rd_platform_conversation_owner
                    ON rd_platform_conversations(actor,updated_at,id);
                CREATE TABLE IF NOT EXISTS rd_platform_conversation_active(
                    actor TEXT PRIMARY KEY, conversation_id TEXT);
                CREATE TABLE IF NOT EXISTS rd_platform_conversation_messages(
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, id TEXT NOT NULL UNIQUE,
                    conversation_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL,
                    mode TEXT, actions TEXT, created_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS rd_platform_conversation_message_order
                    ON rd_platform_conversation_messages(conversation_id,seq);
                CREATE TABLE IF NOT EXISTS rd_platform_conversation_requests(
                    actor TEXT NOT NULL, request_key TEXT NOT NULL, conversation_id TEXT,
                    fingerprint TEXT NOT NULL, status TEXT NOT NULL, started_at REAL NOT NULL,
                    token TEXT NOT NULL, response TEXT, PRIMARY KEY(actor,request_key));
                CREATE INDEX IF NOT EXISTS rd_platform_conversation_pending
                    ON rd_platform_conversation_requests(actor,status);
            ''')

    @contextmanager
    def _db(self, write=False):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE' if write else 'BEGIN')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _owned(db, actor, conversation_id):
        row = db.execute('SELECT * FROM rd_platform_conversations WHERE id=? AND actor=?',
                         (conversation_id, actor)).fetchone()
        if row is None:
            raise RdError(404, '对话不存在或无权访问。')
        return row

    @staticmethod
    def _summary(row):
        return {key: row[key] for key in (
            'id', 'title', 'created_at', 'updated_at', 'message_count', 'source_id', 'version')}

    @staticmethod
    def _message(row):
        result = {key: row[key] for key in ('id', 'seq', 'role', 'content', 'created_at')}
        if row['mode'] is not None:
            result['mode'] = row['mode']
        if row['actions'] is not None:
            result['actions'] = json.loads(row['actions'])
        return result

    def _detail(self, db, row, before=None):
        clause, params = (' AND seq<?', (row['id'], before)) if before is not None else ('', (row['id'],))
        rows = db.execute('SELECT * FROM rd_platform_conversation_messages WHERE conversation_id=?'
                          + clause + ' ORDER BY seq DESC LIMIT ?', (*params, MESSAGE_PAGE_SIZE + 1)).fetchall()
        messages = [self._message(item) for item in reversed(rows[:MESSAGE_PAGE_SIZE])]
        has_more = len(rows) > MESSAGE_PAGE_SIZE
        return {**self._summary(row), 'draft': row['draft'], 'messages': messages,
                'has_more': has_more, 'next_before': messages[0]['seq'] if has_more else None}

    @staticmethod
    def _active_id(db, actor):
        row = db.execute('SELECT conversation_id FROM rd_platform_conversation_active WHERE actor=?',
                         (actor,)).fetchone()
        return row['conversation_id'] if row else None

    def _require_current(self, db, actor, row, expected_version):
        if self._active_id(db, actor) != row['id']:
            raise RdError(409, '此对话已保存在历史中，请从历史记录另开新对话。')
        if row['version'] != expected_version:
            raise RdError(409, '对话已更新，请重新读取后继续。')

    @staticmethod
    def _request(db, actor, key, fingerprint):
        row = db.execute('SELECT * FROM rd_platform_conversation_requests WHERE actor=? AND request_key=?',
                         (actor, key)).fetchone()
        if row is not None and row['fingerprint'] != fingerprint:
            raise RdError(409, '同一请求标识不能用于不同操作或内容。')
        return row

    @staticmethod
    def _idle(db, actor):
        # Expired workers lose their token before a new operation can change the conversation.
        db.execute("UPDATE rd_platform_conversation_requests SET status='failed',token='' "
                   "WHERE actor=? AND status='pending' AND started_at<=?", (actor, time.time() - PENDING_SECONDS))
        pending = db.execute("SELECT 1 FROM rd_platform_conversation_requests WHERE actor=? AND status='pending' LIMIT 1",
                             (actor,)).fetchone()
        if pending:
            raise RdError(409, '小航正在回复，请稍后使用同一请求标识重试。')

    @staticmethod
    def _receipt(db, actor, key, conversation_id, fingerprint, response):
        db.execute('INSERT INTO rd_platform_conversation_requests '
                   '(actor,request_key,conversation_id,fingerprint,status,started_at,token,response) '
                   "VALUES(?,?,?,?,'completed',?,'',?)",
                   (actor, key, conversation_id, fingerprint, time.time(), _json(response)))

    def list(self, actor, page=1):
        if type(page) is not int or page < 1:
            raise RdError(422, '页码必须为正整数。')
        with self._db() as db:
            total = db.execute('SELECT COUNT(*) FROM rd_platform_conversations WHERE actor=?', (actor,)).fetchone()[0]
            rows = db.execute('SELECT * FROM rd_platform_conversations WHERE actor=? '
                              'ORDER BY updated_at DESC,id DESC LIMIT ? OFFSET ?',
                              (actor, PAGE_SIZE, (page - 1) * PAGE_SIZE)).fetchall()
            return {'items': [self._summary(row) for row in rows], 'total': total,
                    'page': page, 'page_size': PAGE_SIZE, 'active_id': self._active_id(db, actor)}

    def get(self, actor, conversation_id, *, before=None):
        if before is not None and (type(before) is not int or before < 1):
            raise RdError(422, '历史游标必须为正整数。')
        with self._db() as db:
            return self._detail(db, self._owned(db, actor, conversation_id), before)

    def create(self, actor, key, source_id=None):
        key = _text(key, '请求标识', 128, True)
        if source_id is not None:
            source_id = _text(source_id, '来源对话', 128, True)
        fingerprint = _fingerprint('create', None, {'source_id': source_id})
        with self._db(write=True) as db:
            request = self._request(db, actor, key, fingerprint)
            if request is not None and request['status'] == 'completed':
                return json.loads(request['response'])
            source = self._owned(db, actor, source_id) if source_id else None
            self._idle(db, actor)
            conversation_id, now = uuid.uuid4().hex, _now()
            title = ('续聊 · ' + source['title'])[:100] if source else '新对话'
            count = source['message_count'] if source else 0
            db.execute('INSERT INTO rd_platform_conversations '
                       '(id,actor,title,created_at,updated_at,message_count,source_id) VALUES(?,?,?,?,?,?,?)',
                       (conversation_id, actor, title, now, now, count, source_id))
            if source:
                for message in db.execute('SELECT * FROM rd_platform_conversation_messages '
                                          'WHERE conversation_id=? ORDER BY seq', (source_id,)).fetchall():
                    db.execute('INSERT INTO rd_platform_conversation_messages '
                               '(id,conversation_id,role,content,mode,actions,created_at) VALUES(?,?,?,?,?,?,?)',
                               (uuid.uuid4().hex, conversation_id, message['role'], message['content'],
                                message['mode'], message['actions'], message['created_at']))
            db.execute('INSERT INTO rd_platform_conversation_active(actor,conversation_id) VALUES(?,?) '
                       'ON CONFLICT(actor) DO UPDATE SET conversation_id=excluded.conversation_id', (actor, conversation_id))
            response = self._detail(db, self._owned(db, actor, conversation_id))
            self._receipt(db, actor, key, conversation_id, fingerprint, response)
            return response

    def ask(self, actor, conversation_id, message, expected_version, key):
        message = _text(message, '问题', 2000, True)
        key = _text(key, '请求标识', 128, True)
        expected_version = _version(expected_version)
        fingerprint = _fingerprint('message', conversation_id, {'message': message, 'expected_version': expected_version})
        safe_message = _safe(message, 2000)
        token = uuid.uuid4().hex
        with self._db(write=True) as db:
            row = self._owned(db, actor, conversation_id)
            request = self._request(db, actor, key, fingerprint)
            if request is not None and request['status'] == 'completed':
                return json.loads(request['response'])
            self._require_current(db, actor, row, expected_version)
            self._idle(db, actor)
            history = db.execute('SELECT role,content FROM rd_platform_conversation_messages '
                                 'WHERE conversation_id=? ORDER BY seq DESC LIMIT 12', (conversation_id,)).fetchall()
            history = [dict(item) for item in reversed(history)]
            db.execute('INSERT INTO rd_platform_conversation_requests '
                       '(actor,request_key,conversation_id,fingerprint,status,started_at,token) '
                       "VALUES(?,?,?,?,'pending',?,?) ON CONFLICT(actor,request_key) DO UPDATE SET "
                       "status='pending',started_at=excluded.started_at,token=excluded.token,response=NULL",
                       (actor, key, conversation_id, fingerprint, time.time(), token))
        try:
            answer = ask_platform(actor, safe_message, history)
        except Exception:
            with self._db(write=True) as db:
                db.execute("UPDATE rd_platform_conversation_requests SET status='failed',token='' "
                           "WHERE actor=? AND request_key=? AND status='pending' AND token=?", (actor, key, token))
            raise
        with self._db(write=True) as db:
            row = self._owned(db, actor, conversation_id)
            request = self._request(db, actor, key, fingerprint)
            if request['status'] == 'completed':
                return json.loads(request['response'])
            if request['status'] != 'pending' or request['token'] != token or time.time() - request['started_at'] >= PENDING_SECONDS:
                raise RdError(409, '本次回复等待已结束，未保存晚到结果；请重新读取对话后重试。')
            self._require_current(db, actor, row, expected_version)
            now = _now()
            for role, content, mode, actions in (
                ('user', safe_message, None, None),
                ('assistant', _safe(answer['content'], 5000), answer['mode'], _json(answer.get('actions', []))),
            ):
                db.execute('INSERT INTO rd_platform_conversation_messages '
                           '(id,conversation_id,role,content,mode,actions,created_at) VALUES(?,?,?,?,?,?,?)',
                           (uuid.uuid4().hex, conversation_id, role, content, mode, actions, now))
            title = ' '.join(safe_message.split())[:60] if row['message_count'] == 0 and row['source_id'] is None else row['title']
            db.execute("UPDATE rd_platform_conversations SET title=?,updated_at=?,message_count=message_count+2,version=version+1,draft='' WHERE id=?",
                       (title, now, conversation_id))
            response = self._detail(db, self._owned(db, actor, conversation_id))
            db.execute("UPDATE rd_platform_conversation_requests SET status='completed',response=?,token='' WHERE actor=? AND request_key=?",
                       (_json(response), actor, key))
            return response

    def close(self, actor, conversation_id, choice, draft, expected_version, key):
        if choice not in {'keep', 'end'}:
            raise RdError(422, '请选择保留并收起或结束并退出。')
        draft = _text(draft, '草稿', 2000)
        key = _text(key, '请求标识', 128, True)
        expected_version = _version(expected_version)
        fingerprint = _fingerprint('close', conversation_id, {'choice': choice, 'draft': draft, 'expected_version': expected_version})
        with self._db(write=True) as db:
            row = self._owned(db, actor, conversation_id)
            request = self._request(db, actor, key, fingerprint)
            if request is not None and request['status'] == 'completed':
                return json.loads(request['response'])
            self._require_current(db, actor, row, expected_version)
            self._idle(db, actor)
            db.execute('UPDATE rd_platform_conversations SET draft=?,version=version+1,updated_at=? WHERE id=?',
                       (_safe(draft, 2000) if choice == 'keep' else '', _now(), conversation_id))
            active_id = conversation_id if choice == 'keep' else None
            db.execute('UPDATE rd_platform_conversation_active SET conversation_id=? WHERE actor=?', (active_id, actor))
            response = {'active_id': active_id}
            self._receipt(db, actor, key, conversation_id, fingerprint, response)
            return response
