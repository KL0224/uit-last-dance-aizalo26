import re
from typing import Optional
import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

from .schemas import EmptyQueryError, SecurityViolation

FORBIDDEN_AST_NODES = (
    exp.Drop,
    exp.Delete,
    exp.Update,
    exp.Insert,
    exp.Create,
    exp.Alter,
    exp.Copy,
    exp.Attach,
    exp.Detach,
    exp.Install,
    exp.Command,
    exp.Pragma,
    exp.Set,
    exp.Transaction,
    exp.Commit,
    exp.Rollback,
)

FORBIDDEN_FUNCTIONS = {
    "read_csv",
    "read_csv_auto",
    "read_parquet",
    "read_json",
    "read_json_auto",
    "read_text",
    "read_blob",
    "scan_parquet",
    "scan_csv",
    "parquet_scan",
    "write_parquet",
    "write_csv",
    "copy",
}

FORBIDDEN_KEYWORDS = (
    "drop",
    "delete",
    "update",
    "insert",
    "create",
    "alter",
    "copy",
    "attach",
    "detach",
    "install",
    "load",
    "pragma",
)

ALLOWED_ROOT_NODES = (
    exp.Select,
    exp.Union,
    exp.Intersect,
    exp.Except,
)


def extract_clean_sql(raw_sql: str) -> str:
    """
    Extracts SQL query from markdown code blocks if present,
    strips whitespace, comments, and trailing semicolons.
    Raises EmptyQueryError if the resulting string is empty.
    """
    if not raw_sql or not raw_sql.strip():
        raise EmptyQueryError("SQL query is empty.")

    text = raw_sql.strip()

    # Match ```sql ... ``` or ``` ... ```
    pattern = r"```(?:sql)?\s*([\s\S]*?)\s*```"
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        extracted = match.group(1).strip()
    else:
        extracted = text

    # Strip trailing semicolons and whitespace
    extracted = re.sub(r";+\s*$", "", extracted).strip()

    if not extracted:
        raise EmptyQueryError("SQL query is empty after stripping markdown and formatting.")

    return extracted


def validate_read_only_sql(sql: str) -> str:
    """
    Statically analyzes SQL AST to ensure query safety.
    - Ensures single statement (prevents multi-statement injection)
    - Validates no DDL/DML/administrative/file-access operations
    - Allows genuine syntax errors to pass through to DuckDB for precise line diagnostics
    Raises SecurityViolation or EmptyQueryError.
    """
    cleaned_sql = extract_clean_sql(sql)

    fast_check = cleaned_sql.lower()

    # Fast-path check for forbidden file functions
    for forbidden_func in FORBIDDEN_FUNCTIONS:
        if re.search(rf"\b{forbidden_func}\b", fast_check):
            raise SecurityViolation(f"File reading or direct table function '{forbidden_func}' is forbidden.")

    # Fast-path check for explicit destructive keywords
    for word in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{word}\b", fast_check):
            raise SecurityViolation(f"Forbidden SQL operation '{word}' detected.")

    try:
        parsed_statements = sqlglot.parse(cleaned_sql, read="duckdb")
    except ParseError:
        # If sqlglot cannot parse, let DuckDB's native parser generate precise line/column hints
        return cleaned_sql

    valid_stmts = [s for s in parsed_statements if s is not None]

    if not valid_stmts:
        raise EmptyQueryError("No valid SQL statement found.")

    if len(valid_stmts) > 1:
        raise SecurityViolation(
            f"Multiple SQL statements detected ({len(valid_stmts)} statements). Only single queries are allowed."
        )

    stmt = valid_stmts[0]

    # Check for forbidden AST nodes anywhere in the tree
    for node in stmt.walk():
        if isinstance(node, FORBIDDEN_AST_NODES):
            raise SecurityViolation(
                f"Forbidden operation '{type(node).__name__}' is not allowed in read-only execution."
            )

        if isinstance(node, (exp.Func, exp.Anonymous, exp.Table)):
            name = node.name.lower() if hasattr(node, "name") and node.name else ""
            if name in FORBIDDEN_FUNCTIONS:
                raise SecurityViolation(f"Forbidden function or table source '{name}' detected.")

    return cleaned_sql
