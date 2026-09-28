"""Test fixtures. Every service test runs on SQLite, and also on Microsoft
SQL Server when HEYGEN_TEST_MSSQL=1 and the HEYGEN_MSSQL_* connection
settings point at a server where the login may create databases. Each SQL
Server test gets its own throwaway database, dropped afterwards."""

import os
import uuid

import pytest

from heygen_passport import config, db

ENGINES = ["sqlite"] + (["mssql"] if os.environ.get("HEYGEN_TEST_MSSQL") == "1" else [])


@pytest.fixture(params=ENGINES)
def fresh_conn(request, tmp_path, monkeypatch):
    if request.param == "sqlite":
        conn = db.connect(tmp_path / "t.db")
        yield conn
        conn.close()
        return
    name = f"hp_test_{uuid.uuid4().hex[:12]}"
    monkeypatch.setattr(config, "MSSQL_DATABASE", name)
    monkeypatch.setattr(config, "DB_ENGINE", "mssql")
    db.create_mssql_database(name)
    conn = db.connect(engine="mssql")
    try:
        yield conn
    finally:
        conn.close()
        master = db.pyodbc.connect(db.mssql_connection_string("master"), autocommit=True)
        master.cursor().execute(f"ALTER DATABASE [{name}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; "
                                f"DROP DATABASE [{name}]")
        master.close()
