"""DuckDB setup and queries for jobs and applications."""
from __future__ import annotations

import logging

import duckdb

from backend.config import settings

logger = logging.getLogger(__name__)

_con: duckdb.DuckDBPyConnection | None = None


def get_connection() -> duckdb.DuckDBPyConnection:
    global _con
    if _con is None:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        _con = duckdb.connect(str(settings.db_path))
        _initialize_tables(_con)
        logger.info("DuckDB connected at %s", settings.db_path)
    return _con


def _initialize_tables(con: duckdb.DuckDBPyConnection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id VARCHAR PRIMARY KEY,
            title VARCHAR,
            company VARCHAR,
            location VARCHAR,
            url VARCHAR,
            description VARCHAR,
            source VARCHAR,
            date_posted VARCHAR,
            job_type VARCHAR,
            is_remote BOOLEAN DEFAULT FALSE,
            status VARCHAR DEFAULT 'new',
            match_score DOUBLE DEFAULT 0.0,
            ats_platform VARCHAR DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    con.execute("""
        CREATE TABLE IF NOT EXISTS applications (
            id VARCHAR PRIMARY KEY,
            job_id VARCHAR,
            job_url VARCHAR,
            company VARCHAR,
            title VARCHAR,
            status VARCHAR DEFAULT 'started',
            fields_filled INTEGER DEFAULT 0,
            fields_total INTEGER DEFAULT 0,
            cover_letter_path VARCHAR DEFAULT '',
            notes VARCHAR DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)


def close() -> None:
    global _con
    if _con:
        _con.close()
        _con = None
