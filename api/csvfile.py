import csv
import io
import unicodedata
from collections.abc import Iterable, Iterator
from pathlib import Path

DELIMITERS = ",;\t|"


class Unreadable(Exception):
    pass


def detect(path: Path) -> tuple[str, str]:
    # ponytail: reads the whole file to pick the encoding; fine under the 30 MB upload cap
    data = path.read_bytes()
    if b"\x00" in data:
        raise Unreadable
    try:
        data.decode("utf-8-sig")
        encoding = "utf-8-sig"
    except UnicodeDecodeError:
        encoding = "latin-1"
    # decided on the header line only: csv.Sniffer picks "," in BR files that use ";" and decimal commas
    first_line = data.split(b"\n", 1)[0].decode(encoding)
    delimiter = max(DELIMITERS, key=first_line.count)
    if first_line.count(delimiter) == 0:
        raise Unreadable
    return encoding, delimiter


def rows(path: Path) -> Iterator[list[str]]:
    encoding, delimiter = detect(path)
    with path.open(newline="", encoding=encoding) as f:
        try:
            yield from csv.reader(f, delimiter=delimiter)
        except csv.Error:
            raise Unreadable


def header(path: Path) -> list[str]:
    encoding, delimiter = detect(path)
    with path.open(newline="", encoding=encoding) as f:
        try:
            first = next(csv.reader(f, delimiter=delimiter), [])
        except csv.Error:
            raise Unreadable
    columns = [c.strip() for c in first]
    if len(columns) < 2 or not all(columns):
        raise Unreadable
    return columns


def normalize(column: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", column.lower()) if c.isalnum())


def safe(cell: str) -> str:
    # Excel runs a cell that starts with these as a formula; names come from people. Only text goes through here:
    # a number we format may start with "-"
    return "'" + cell if cell.startswith(("=", "+", "-", "@", "\t", "\r")) else cell


def decimal(value: float | None, digits: int = 2) -> str:
    # a decimal comma and no thousands separator: Excel in pt-BR reads "1234,5" as a number
    return "" if value is None else f"{value:.{digits}f}".replace(".", ",")


def to_csv(header: list[str], rows: Iterable[list]) -> str:
    # ";" and a decimal comma, with a BOM: what Excel in pt-BR opens without the import wizard
    out = io.StringIO()
    writer = csv.writer(out, delimiter=";", lineterminator="\n")
    writer.writerow(header)
    writer.writerows(rows)
    return "\ufeff" + out.getvalue()
