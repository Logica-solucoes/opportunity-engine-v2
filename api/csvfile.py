import csv
from collections.abc import Iterator
from pathlib import Path

DELIMITERS = ",;\t|"


class Unreadable(Exception):
    pass


def detect(path: Path) -> tuple[str, str]:
    # ponytail: reads the whole file to pick the encoding; fine under the 30 MB upload cap
    data = path.read_bytes()
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
        yield from csv.reader(f, delimiter=delimiter)


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
