"""Append-only SQLite migrations; project documents remain compatible."""


def migrate(conn):
    version = conn.execute('PRAGMA user_version').fetchone()[0]
    if version > 2:
        raise RuntimeError('研发数据库版本高于当前服务，请升级服务')
    if version == 0:
        conn.execute('CREATE TABLE projects (id TEXT PRIMARY KEY, version INTEGER NOT NULL, document TEXT NOT NULL)')
        conn.execute('CREATE TABLE requests (scope TEXT NOT NULL, actor_id TEXT NOT NULL, request_key TEXT NOT NULL, fingerprint TEXT NOT NULL, response TEXT NOT NULL, PRIMARY KEY(scope,actor_id,request_key))')
        conn.execute('CREATE TABLE generations (jid TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES projects(id), binding TEXT NOT NULL)')
        conn.execute('CREATE INDEX generations_project ON generations(project_id)')
    if version < 2:
        conn.execute('CREATE TABLE taskbook_runs (run_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, task_id TEXT NOT NULL, document TEXT NOT NULL)')
        conn.execute('CREATE INDEX taskbook_runs_task ON taskbook_runs(project_id,task_id)')
        conn.execute('CREATE TABLE taskbook_drafts (scope TEXT PRIMARY KEY, revision INTEGER NOT NULL, document TEXT NOT NULL)')
        conn.execute('PRAGMA user_version=2')
