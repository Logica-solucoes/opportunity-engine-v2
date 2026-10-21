import argparse
import logging
import sys

from api.accounts import create_platform_admin
from api.db import SessionLocal


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(prog="python -m api.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    create_admin = commands.add_parser("create-admin", help="cria ou promove um platform admin")
    create_admin.add_argument("email")
    create_admin.add_argument("name")
    args = parser.parse_args(argv)

    with SessionLocal() as db:
        temp = create_platform_admin(db, args.email, args.name)
    # the temp password is the command's output, not a log line: it must never go through logging
    sys.stdout.write(f"senha temporária: {temp}\n")


if __name__ == "__main__":
    main()
