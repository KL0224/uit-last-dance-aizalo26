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
    exp.Subquery,
)

SYNTAX_FRAGMENT_NODES = (
    exp.Alias,
    exp.Column,
    exp.Identifier,
    exp.Anonymous,
    exp.Literal,
)

# Leading words of statements that must never reach DuckDB even if sqlglot cannot parse them.
NON_QUERY_LEADING_WORDS = {
    "truncate", "export", "call", "set", "reset", "use", "vacuum", "checkpoint",
    "begin", "commit", "rollback", "grant", "revoke", "merge", "replace",
    "import", "show", "describe", "summarize", "explain", "force", "comment",
}

_MASK_PATTERN = re.compile(
    r"'(?:''|[^'])*'"      # string literal
    r'|"(?:""|[^"])*"'      # quoted identifier
    r"|--[^\n]*"           # line comment
    r"|/\*[\s\S]*?\*/",     # block comment
)


def _mask_literals_and_comments(sql: str) -> str:
    """Blank out literals, quoted identifiers and comments so keyword scans see code only."""
    return _MASK_PATTERN.sub(" ", sql)


def _strip_literals_and_comments(sql: str) -> str:
    """Strip block/line comments and blank out string literals and quoted identifiers."""
    sql = re.sub(r"/\*[\s\S]*?\*/", " ", sql)
    sql = re.sub(r"--[^\n]*", " ", sql)
    sql = re.sub(r"'(?:''|[^'])*'", "''", sql)
    sql = re.sub(r'"(?:""|[^"])*"', '""', sql)
    return sql.lower()


def extract_clean_sql(raw_sql: str) -> str:
    """
    Extracts SQL query from markdown code blocks if present (picking the last block
    when multiple markdown blocks exist), strips <think> blocks, trailing comments,
    and trailing semicolons.
    Raises EmptyQueryError if the resulting string is empty.
    """
    if not raw_sql or not raw_sql.strip():
        raise EmptyQueryError("SQL query is empty.")

    text = raw_sql.strip()

    text = re.sub(r"<think>[\s\S]*?</think>", "", text, flags=re.IGNORECASE).strip()
    if not text:
        raise EmptyQueryError("SQL query is empty.")

    # Match all ```sql ... ``` or ``` ... ``` blocks and take the last one
    pattern = r"```(?:sql)?\s*([\s\S]*?)\s*```"
    matches = re.findall(pattern, text, re.IGNORECASE)
    extracted = matches[-1].strip() if matches else text

    # Strip trailing comments before stripping trailing semicolons
    extracted = re.sub(r"/\*[\s\S]*?\*/\s*$", "", extracted).strip()
    extracted = re.sub(r"--[^\n]*$", "", extracted).strip()
    extracted = re.sub(r";+\s*$", "", extracted).strip()
    extracted = re.sub(r"--[^\n]*$", "", extracted).strip()

    if not extracted:
        raise EmptyQueryError("SQL query is empty after stripping markdown and formatting.")

    return extracted


def validate_read_only_sql(sql: str) -> str:
    """
    Statically analyzes SQL AST to ensure query safety.
    - Parses AST first via sqlglot to avoid false positives on literals/comments
    - Ensures single statement (prevents multi-statement injection)
    - Validates root node is in ALLOWED_ROOT_NODES (or syntax fragment for DuckDB error reporting)
    - Validates no DDL/DML/administrative/file-access operations or duckdb_* system functions
    - Falls back to literal-stripped regex scanning only when sqlglot raises ParseError
    Raises SecurityViolation or EmptyQueryError.
    """
    cleaned_sql = extract_clean_sql(sql)
    masked_check = _mask_literals_and_comments(cleaned_sql).lower()

    try:
        parsed_statements = sqlglot.parse(cleaned_sql, read="duckdb")
        valid_stmts = [s for s in parsed_statements if s is not None]

        if not valid_stmts:
            raise EmptyQueryError("No valid SQL statement found.")

        if len(valid_stmts) > 1:
            raise SecurityViolation(
                f"Multiple SQL statements detected ({len(valid_stmts)} statements). Only single queries are allowed."
            )

        stmt = valid_stmts[0]

        # Expression fragments (typos such as "SELEC * FORM t" parse as an Alias) are not
        # statements; DuckDB rejects them with a precise syntax error for the retry loop,
        # provided they are not leading with an administrative/DDL keyword.
        if not isinstance(stmt, ALLOWED_ROOT_NODES + SYNTAX_FRAGMENT_NODES):
            raise SecurityViolation(
                f"Only SELECT queries are allowed, got '{type(stmt).__name__}'."
            )

        if isinstance(stmt, SYNTAX_FRAGMENT_NODES):
            first_word = re.match(r"[a-z_]+", masked_check.strip())
            if first_word and (
                first_word.group(0) in NON_QUERY_LEADING_WORDS
                or first_word.group(0) in FORBIDDEN_KEYWORDS
            ):
                raise SecurityViolation(
                    f"Only SELECT queries are allowed, got '{first_word.group(0)}'."
                )

        # Check for forbidden AST nodes and functions anywhere in the tree
        for node in stmt.walk():
            if isinstance(node, FORBIDDEN_AST_NODES):
                raise SecurityViolation(
                    f"Forbidden operation '{type(node).__name__}' is not allowed in read-only execution."
                )

            if isinstance(node, (exp.Func, exp.Anonymous, exp.Table)):
                name = (node.name or "").lower() if hasattr(node, "name") else ""
                if name in FORBIDDEN_FUNCTIONS or name.startswith("duckdb_"):
                    raise SecurityViolation(f"Forbidden function or table source '{name}' detected.")

    except ParseError:
        # If sqlglot cannot parse, scan masked SQL (with literals & comments stripped)
        masked_sql = _strip_literals_and_comments(cleaned_sql)
        code = masked_sql.strip().rstrip(";").strip()
        if ";" in code:
            raise SecurityViolation("Multiple SQL statements detected. Only single queries are allowed.")

        for func in FORBIDDEN_FUNCTIONS:
            if re.search(rf"\b{func}\b", masked_sql):
                raise SecurityViolation(f"File reading or direct table function '{func}' is forbidden.")

        if re.search(r"\bduckdb_[a-z0-9_]+\s*\(", masked_sql):
            raise SecurityViolation("System function 'duckdb_*' is forbidden.")

        for word in FORBIDDEN_KEYWORDS:
            if re.search(rf"\b{word}\b", masked_sql):
                raise SecurityViolation(f"Forbidden SQL operation '{word}' detected.")

        first_word = re.match(r"[a-z_]+", code)
        if first_word and first_word.group(0) in NON_QUERY_LEADING_WORDS:
            raise SecurityViolation(f"Only SELECT queries are allowed, got '{first_word.group(0)}'.")

    return cleaned_sql
