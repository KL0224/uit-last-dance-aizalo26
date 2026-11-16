"""Streaming CSV, XLSX and read-only SQLite readers with physical row provenance."""

from __future__ import annotations

import csv
import hashlib
import re
import sqlite3
import unicodedata
from abc import ABC, abstractmethod
from collections.abc import Iterator
from itertools import islice
from pathlib import Path
from typing import Any

from openpyxl import load_workbook

from .models import SourceRow, SourceTable


def fold(value: str) -> str:
    value = (
        re.sub(r"([a-z])([A-Z])", r"\1 \2", value).replace("Đ", "D").replace("đ", "d")
    )
    return " ".join(
        re.sub(
            r"[^a-z0-9]+",
            " ",
            unicodedata.normalize("NFKD", value)
            .encode("ascii", "ignore")
            .decode()
            .lower(),
        ).split()
    )


def sql_name(value: str, prefix: str = "c") -> str:
    base = fold(value).replace(" ", "_") or prefix
    if base[0].isdigit() or base.startswith("__dm"):
        base = prefix + "_" + base
    return base


def column_names(headers: tuple[str, ...]) -> tuple[str, ...]:
    used: set[str] = set()
    result: list[str] = []
    for index, name in enumerate(headers):
        base = sql_name(name)
        candidate = base
        if candidate in used:
            candidate = f"{base}_{index + 1}"
        while candidate in used:
            candidate += "_"
        used.add(candidate)
        result.append(candidate)
    return tuple(result)


def quote(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _family(path: Path, sheet: str | None, region: int) -> str:
    stem = re.sub(r"_(?:\d+)$", "", path.stem)
    if path.parent.as_posix() != ".":
        stem = path.parent.as_posix() + "_" + stem
    folded_sheet = fold(sheet) if sheet else ""
    month_sheet = bool(
        sheet
        and re.search(r"(?:19|20)\d{2}", sheet)
        and (
            re.search(
                r"(?:^| )(?:thang\s*(?:0?[1-9]|1[0-2])|t(?:0?[1-9]|1[0-2]))(?: |$)",
                folded_sheet,
                re.IGNORECASE,
            )
            or re.search(
                r"(?:^|[^A-Za-z0-9])(?:0?[1-9]|1[0-2])\s*[./_-]\s*(?:19|20)\d{2}",
                sheet,
            )
            or re.search(
                r"(?:19|20)\d{2}\s*[./_-]\s*(?:0?[1-9]|1[0-2])(?:$|[^A-Za-z0-9])",
                sheet,
            )
        )
    )
    label = (
        stem
        if not sheet or month_sheet or sheet.lower() in {"sheet1", "sheet"}
        else f"{stem}_{sheet}"
    )
    if region:
        label += f"_region_{region + 1}"
    return label


def _source(
    path: Path,
    relative: str,
    sheet: str | None,
    headers: tuple[str, ...],
    start: int,
    end: int | None,
    region: int = 0,
    **kwargs: Any,
) -> SourceTable:
    identity = f"{relative}#{sheet or ''}:{start}"
    source_id = "s_" + hashlib.sha256(identity.encode()).hexdigest()[:12]
    year_match = re.search(r"(?:19|20)\d{2}", sheet or "")
    return SourceTable(
        path,
        relative,
        source_id,
        sheet,
        headers,
        start,
        end,
        year=int(year_match.group()) if year_match else None,
        logical_family=_family(Path(relative), sheet, region),
        **kwargs,
    )


_HEADER_WORDS = {
    "ma",
    "ngay",
    "ten",
    "tien",
    "luong",
    "gia",
    "status",
    "amount",
    "qty",
    "quantity",
    "date",
    "id",
    "name",
    "value",
    "stt",
    "sl",
    "unit",
    "khach",
    "don",
    "hang",
    "han",
    "phone",
    "sku",
}


def _score(values: tuple[Any, ...]) -> tuple[int, int]:
    cells = [
        str(value).strip()
        for value in values
        if value is not None and str(value).strip()
    ]
    if not cells or any(
        not isinstance(value, str) for value in values if value is not None
    ):
        return (0, 0)
    known = sum(bool(set(fold(cell).split()) & _HEADER_WORDS) for cell in cells)
    if len(set(cells)) != len(cells):
        return (0, 0)
    return known, len(cells)


def _headers(values: tuple[Any, ...]) -> tuple[str, ...]:
    trimmed = list(values)
    while trimmed and (trimmed[-1] is None or str(trimmed[-1]).strip() == ""):
        trimmed.pop()
    return tuple(
        str(value).strip()
        if value is not None and str(value).strip()
        else f"column_{index + 1}"
        for index, value in enumerate(trimmed)
    )


_AUTO_HEADER = re.compile(r"column_\d+")


def _is_repeated_header(values: tuple[Any, ...], headers: tuple[str, ...]) -> bool:
    """A data row equal to the header is a repeated header, unless the header contains synthetic names."""
    if any(_AUTO_HEADER.fullmatch(name) for name in headers):
        return False
    return _headers(tuple(values)) == headers


class BaseReader(ABC):
    @abstractmethod
    def discover(
        self, path: Path, relative: str, overrides: dict[str, dict[str, Any]]
    ) -> list[SourceTable]:
        raise NotImplementedError

    @abstractmethod
    def rows(self, source: SourceTable) -> Iterator[SourceRow]:
        raise NotImplementedError


class CSVReader(BaseReader):
    def discover(
        self, path: Path, relative: str, overrides: dict[str, dict[str, Any]]
    ) -> list[SourceTable]:
        options = overrides.get(relative, {})
        encoding = options.get("encoding")
        if encoding is None:
            for candidate in ("utf-8-sig", "cp1258"):
                try:
                    with path.open(encoding=candidate) as stream:
                        while stream.read(1024 * 1024):
                            pass
                    encoding = candidate
                    break
                except UnicodeDecodeError:
                    continue
            if encoding is None:
                raise ValueError(
                    f"cannot decode CSV {relative}; provide encoding override"
                )
        with path.open(encoding=encoding, newline="") as stream:
            sample = stream.read(65536)
            delimiter = options.get("delimiter")
            if delimiter is None:
                try:
                    delimiter = (
                        csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
                    )
                except csv.Error as exc:
                    raise ValueError(
                        f"ambiguous CSV delimiter: {relative}; configure delimiter"
                    ) from exc
            stream.seek(0)
            start = options.get("header_row", 1)
            reader = csv.reader(stream, delimiter=delimiter, strict=True)
            for _ in range(start - 1):
                next(reader)
            headers = _headers(tuple(next(reader)))
            if not headers:
                raise ValueError(f"empty CSV header: {relative}")
        return [
            _source(
                path,
                relative,
                None,
                headers,
                start,
                None,
                encoding=encoding,
                delimiter=delimiter,
            )
        ]

    def rows(self, source: SourceTable) -> Iterator[SourceRow]:
        with source.path.open(encoding=source.encoding, newline="") as stream:
            reader = csv.reader(stream, delimiter=source.delimiter, strict=True)
            for _ in range(source.header_row):
                next(reader)
            for row in reader:
                number = reader.line_num
                if not any(value.strip() for value in row):
                    continue
                if _is_repeated_header(tuple(row), source.headers):
                    continue
                if len(row) > len(source.headers):
                    raise ValueError(
                        f"CSV row wider than header: {source.relative_path}:{number}"
                    )
                yield SourceRow(
                    number, tuple(row) + (None,) * (len(source.headers) - len(row))
                )


class XLSXReader(BaseReader):
    def discover(
        self, path: Path, relative: str, overrides: dict[str, dict[str, Any]]
    ) -> list[SourceTable]:
        workbook = load_workbook(path, read_only=True, data_only=True, keep_links=False)
        sources: list[SourceTable] = []
        original = None  # formula workbook, opened lazily and at most once
        try:
            for sheet in workbook:
                sheet.reset_dimensions()
                options = overrides.get(
                    f"{relative}#{sheet.title}", overrides.get(relative, {})
                )
                initial = list(islice(sheet.iter_rows(values_only=True), 30))
                if (
                    not any(any(value is not None for value in row) for row in initial)
                    and "header_row" not in options
                ):
                    # Empty cached prefix is not proof of an empty sheet: data may
                    # start later or consist of formulas without cached values.
                    if original is None:
                        original = load_workbook(
                            path, read_only=True, data_only=False, keep_links=False
                        )
                    original_sheet = original[sheet.title]
                    original_sheet.reset_dimensions()
                    if any(
                        any(value is not None for value in row)
                        for row in original_sheet.iter_rows(values_only=True)
                    ):
                        raise ValueError(
                            f"nonempty XLSX sheet beyond header scan or missing cache: {relative}#{sheet.title}; configure header_row"
                        )
                    continue
                if "header_row" in options:
                    start = options["header_row"]
                    values = next(
                        islice(
                            sheet.iter_rows(
                                min_row=start, max_row=start, values_only=True
                            ),
                            1,
                        )
                    )
                else:
                    ranked = sorted(
                        (
                            (_score(tuple(row)), -i, row)
                            for i, row in enumerate(initial, 1)
                        ),
                        reverse=True,
                        key=lambda item: (item[0], item[1]),
                    )
                    score, neg_start, values = ranked[0]
                    if score[0] == 0:
                        raise ValueError(
                            f"ambiguous XLSX header: {relative}#{sheet.title}; configure header_row"
                        )
                    start = -neg_start
                    # A later, wider table must not cause preceding data to disappear.
                    for prefix in initial[: start - 1]:
                        if any(
                            value is not None and not isinstance(value, str)
                            for value in prefix
                        ):
                            raise ValueError(
                                f"ambiguous data before header: {relative}#{sheet.title}; configure header_row"
                            )
                headers = _headers(tuple(values))
                regions: list[tuple[int, tuple[str, ...]]] = [(start, headers)]
                blank = False
                # A new distinct header following a blank separator starts another region.
                for number, row in enumerate(
                    sheet.iter_rows(min_row=start + 1, values_only=True), start + 1
                ):
                    if not any(
                        value is not None and str(value).strip() for value in row
                    ):
                        blank = True
                        continue
                    score = _score(tuple(row))
                    if (
                        blank
                        and score[0] >= 2
                        and score[0] == score[1]
                        and _headers(tuple(row)) != regions[-1][1]
                    ):
                        regions.append((number, _headers(tuple(row))))
                    blank = False
                for index, (header_row, region_headers) in enumerate(regions):
                    end = (
                        regions[index + 1][0] - 1 if index + 1 < len(regions) else None
                    )
                    sources.append(
                        _source(
                            path,
                            relative,
                            sheet.title,
                            region_headers,
                            header_row,
                            end,
                            index,
                            epoch="1904" if workbook.epoch.year == 1904 else "1900",
                        )
                    )
        finally:
            workbook.close()
            if original is not None:
                original.close()
        return sources

    def rows(self, source: SourceTable) -> Iterator[SourceRow]:
        cached = load_workbook(
            source.path, read_only=True, data_only=True, keep_links=False
        )
        formulas = load_workbook(
            source.path, read_only=True, data_only=False, keep_links=False
        )
        try:
            sheet = cached[source.sheet]
            formula_sheet = formulas[source.sheet]
            sheet.reset_dimensions()
            formula_sheet.reset_dimensions()
            values_iter = sheet.iter_rows(
                min_row=source.header_row + 1, max_row=source.end_row, values_only=True
            )
            formula_iter = formula_sheet.iter_rows(
                min_row=source.header_row + 1, max_row=source.end_row
            )
            for number, (values, cells) in enumerate(
                zip(values_iter, formula_iter, strict=True), source.header_row + 1
            ):
                if not any(value is not None for value in values) and not any(
                    cell.data_type == "f" for cell in cells
                ):
                    continue
                if _is_repeated_header(tuple(values), source.headers):
                    continue
                if any(value is not None for value in values[len(source.headers) :]):
                    raise ValueError(
                        f"XLSX row wider than header: {source.relative_path}#{source.sheet}:{number}"
                    )
                row = list(values[: len(source.headers)])
                row.extend([None] * (len(source.headers) - len(row)))
                cache: dict[str, Any] = {}
                for index, cell in enumerate(cells[: len(source.headers)]):
                    if cell.data_type == "f":
                        cache[str(index)] = row[index]
                        row[index] = cell.value
                yield SourceRow(number, tuple(row), cache)
        finally:
            cached.close()
            formulas.close()


class SQLiteReader(BaseReader):
    def discover(
        self, path: Path, relative: str, overrides: dict[str, dict[str, Any]]
    ) -> list[SourceTable]:
        result: list[SourceTable] = []
        if path.with_name(path.name + "-wal").exists():
            raise ValueError(
                "SQLite WAL source requires a checkpointed snapshot; no source writes performed"
            )
        connection = sqlite3.connect(
            path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True
        )
        try:
            connection.execute("PRAGMA query_only=ON")
            for (table,) in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            ):
                info = connection.execute(
                    f"PRAGMA table_info({quote(table)})"
                ).fetchall()
                fks = connection.execute(
                    f"PRAGMA foreign_key_list({quote(table)})"
                ).fetchall()
                foreign_keys = tuple(
                    {
                        "id": row[0],
                        "seq": row[1],
                        "table": row[2],
                        "from": row[3],
                        "to": row[4],
                    }
                    for row in fks
                )
                result.append(
                    _source(
                        path,
                        relative,
                        table,
                        tuple(item[1] for item in info),
                        0,
                        None,
                        sqlite_types=tuple(item[2] for item in info),
                        sqlite_foreign_keys=foreign_keys,
                    )
                )
        finally:
            connection.close()
        return result

    def rows(self, source: SourceTable) -> Iterator[SourceRow]:
        connection = sqlite3.connect(
            source.path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True
        )
        try:
            connection.execute("PRAGMA query_only=ON")
            cursor = connection.execute(f"SELECT * FROM {quote(source.sheet)}")
            number = 0
            while rows := cursor.fetchmany(10_000):
                for row in rows:
                    number += 1
                    yield SourceRow(number, tuple(row))
        finally:
            connection.close()


READERS: dict[str, BaseReader] = {
    ".csv": CSVReader(),
    ".xlsx": XLSXReader(),
    ".sqlite": SQLiteReader(),
}
