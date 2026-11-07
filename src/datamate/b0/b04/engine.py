import logging
import os
import re
import threading
import time
from typing import Optional
import duckdb

try:
    import pandas as pd
except ImportError:
    pd = None

from .schemas import (
    ExecutionRequest,
    ExecutionResponse,
    QueryTimeoutError,
    normalize_value,
)
from .sanitizer import extract_clean_sql, validate_read_only_sql
from .error_handler import classify_error, determine_route, format_error_message

logger = logging.getLogger(__name__)


def _load_directory_into_duckdb(con: duckdb.DuckDBPyConnection, dir_path: str) -> None:
    """
    Scans a directory for tabular data files (parquet, csv, tsv, json, xlsx)
    and loads each into an in-memory DuckDB table named after the file stem.
    """
    supported_extensions = {".parquet", ".csv", ".tsv", ".json", ".jsonl", ".xlsx", ".xls"}
    loaded_any = False

    def unique_name(base: str) -> str:
        name, counter = base, 1
        while name.lower() in used_names:
            counter += 1
            name = f"{base}_{counter}"
        used_names.add(name.lower())
        return name

    used_names: set[str] = set()
    for root, dirs, files in os.walk(dir_path):
        dirs.sort()
        for file_name in sorted(files):
            ext = os.path.splitext(file_name)[1].lower()
            if ext not in supported_extensions:
                continue

            file_path = os.path.join(root, file_name)
            # Create a clean, SQL-safe table name
            stem = os.path.splitext(file_name)[0]
            base_name = re.sub(r"[^a-zA-Z0-9_]", "_", stem) or f"tbl_{len(used_names)}"

            try:
                if ext in (".xlsx", ".xls"):
                    if pd is None:
                        continue
                    sheets = pd.read_excel(file_path, sheet_name=None)
                    for sheet_name, df in sheets.items():
                        suffix = re.sub(r"[^a-zA-Z0-9_]", "_", str(sheet_name))
                        candidate = base_name if len(sheets) == 1 else f"{base_name}_{suffix}"
                        table_name = unique_name(candidate)
                        tmp_id = f"_tmp_{table_name}"
                        con.register(tmp_id, df)
                        con.execute(f'CREATE TABLE "{table_name}" AS SELECT * FROM "{tmp_id}"')
                        con.unregister(tmp_id)
                        loaded_any = True
                    continue
                table_name = unique_name(base_name)
                if ext == ".parquet":
                    con.execute(f'CREATE TABLE "{table_name}" AS SELECT * FROM read_parquet(?)', [file_path])
                elif ext in (".csv", ".tsv"):
                    con.execute(f'CREATE TABLE "{table_name}" AS SELECT * FROM read_csv(?, header=true, auto_detect=true)', [file_path])
                elif ext in (".json", ".jsonl"):
                    con.execute(f'CREATE TABLE "{table_name}" AS SELECT * FROM read_json(?, auto_detect=true)', [file_path])
                loaded_any = True
            except Exception as e:
                logger.warning("Failed to load file '%s' into table '%s': %s", file_path, base_name, e)

    if not loaded_any:
        logger.info("No supported tabular data files found in directory '%s'.", dir_path)


def execute_query(request: ExecutionRequest) -> ExecutionResponse:
    """
    Executes an SQL query in a sandboxed, read-only DuckDB environment.
    Guarantees:
    - Pre-execution static AST security check (read-only queries only)
    - Sandbox resource limits (memory, threads, disabled external file access)
    - Hard timeout enforcement via con.interrupt()
    - Memory safety with max_rows row-limit
    - Deterministic routing ('yes', 'recoverable', 'abstain')
    - JSON-safe primitive data output
    """
    start_time = time.perf_counter()
    cleaned_sql: Optional[str] = None
    con: Optional[duckdb.DuckDBPyConnection] = None
    timed_out = [False]
    timer: Optional[threading.Timer] = None

    try:
        # Step 1: Pre-execution static analysis and sanitation
        cleaned_sql = validate_read_only_sql(request.sql_query)

        # Step 2: Establish connection based on db_path
        if request.db_path == ":memory:":
            con = duckdb.connect(database=":memory:")
        elif os.path.isfile(request.db_path):
            con = duckdb.connect(database=request.db_path, read_only=True)
        elif os.path.isdir(request.db_path):
            bundle_db = os.path.join(request.db_path, "data.duckdb")
            if os.path.isfile(bundle_db):
                # Prepared B0.1 bundle: query the normalized store directly.
                con = duckdb.connect(database=bundle_db, read_only=True)
            else:
                con = duckdb.connect(database=":memory:")
                _load_directory_into_duckdb(con, request.db_path)
        else:
            raise FileNotFoundError(f"Database path '{request.db_path}' does not exist.")

        # Step 3: Configure sandbox constraints
        # Set conservative limits to prevent runaway resource consumption
        for config_sql in [
            "SET max_memory = '2GB'",
            "SET threads = 2",
            "SET enable_external_access = false",
            "SET lock_configuration = true",
        ]:
            try:
                con.execute(config_sql)
            except Exception as conf_err:
                logger.debug("Sandbox setting '%s' ignored or locked: %s", config_sql, conf_err)

        # Step 4: Setup interrupt timer
        def on_timeout():
            timed_out[0] = True
            if con:
                try:
                    con.interrupt()
                except Exception:
                    pass

        timer = threading.Timer(request.timeout_sec, on_timeout)
        timer.start()

        # Step 5: Execute query
        try:
            cursor = con.execute(cleaned_sql)
            columns = [desc[0] for desc in cursor.description] if cursor.description else []
            raw_rows = cursor.fetchmany(request.max_rows + 1)
            truncated = len(raw_rows) > request.max_rows
            raw_rows = raw_rows[: request.max_rows]
            # Hide B0.1 internal lineage columns (e.g. __dm_row_id) leaked by SELECT *.
            visible = [i for i, name in enumerate(columns) if not name.startswith("__dm_")]
            if visible and len(visible) < len(columns):
                columns = [columns[i] for i in visible]
                raw_rows = [tuple(row[i] for i in visible) for row in raw_rows]
        except Exception as exec_err:
            if timed_out[0]:
                raise QueryTimeoutError(
                    f"Query execution timed out after {request.timeout_sec:.1f}s."
                ) from exec_err
            raise

        execution_time_ms = (time.perf_counter() - start_time) * 1000.0

        # Step 6: Normalize output records to JSON-safe primitives
        rows = []
        for raw_row in raw_rows:
            row_dict = {}
            for col_name, val in zip(columns, raw_row):
                row_dict[col_name] = normalize_value(val)
            rows.append(row_dict)

        return ExecutionResponse(
            question_id=request.question_id,
            is_valid=True,
            route="yes",
            cleaned_sql=cleaned_sql,
            columns=columns,
            rows=rows,
            row_count=len(rows),
            error_type=None,
            error_message=None,
            execution_time_ms=execution_time_ms,
            truncated=truncated,
        )

    except Exception as exc:
        execution_time_ms = (time.perf_counter() - start_time) * 1000.0

        # Attempt to recover cleaned_sql for diagnostics if not already set
        if cleaned_sql is None:
            try:
                cleaned_sql = extract_clean_sql(request.sql_query)
            except Exception:
                cleaned_sql = request.sql_query.strip() if request.sql_query else None

        error_type, is_recoverable = classify_error(exc)
        route = determine_route(
            error_type=error_type,
            is_recoverable=is_recoverable,
            retry_count=request.retry_count,
            max_retries=request.max_retries,
        )
        error_message = format_error_message(exc, error_type, timeout_sec=request.timeout_sec)

        return ExecutionResponse(
            question_id=request.question_id,
            is_valid=False,
            route=route,
            cleaned_sql=cleaned_sql,
            columns=None,
            rows=None,
            row_count=0,
            error_type=error_type,
            error_message=error_message,
            execution_time_ms=execution_time_ms,
        )

    finally:
        if timer:
            timer.cancel()
        if con:
            try:
                con.close()
            except Exception:
                pass

