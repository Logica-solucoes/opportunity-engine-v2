import argparse
import logging
import sys

from sqlalchemy import select
from sqlalchemy.orm import Session

from api import runs
from api.accounts import ActiveRun, create_platform_admin, purge_trash, purge_workspace
from api.db import SessionLocal
from api.models import Run, Workspace


def delete_workspace(db: Session, slug: str, yes: bool) -> int:
    workspace = db.scalar(select(Workspace).where(Workspace.slug == slug))
    if workspace is None:
        sys.stderr.write(f"workspace {slug} não existe\n")
        return 1
    if not yes:
        typed = input(f"Apaga {workspace.name} ({slug}) de vez, sem volta. Digite o slug para confirmar: ")
        if typed.strip() != slug:
            sys.stderr.write("confirmação não confere; nada foi apagado\n")
            return 1
    runs.fail_stale(db, Run.workspace_id == workspace.id)
    try:
        purge_workspace(db, workspace, by="cli")
    except ActiveRun:
        sys.stderr.write("há uma execução em andamento; nada foi apagado\n")
        return 1
    sys.stdout.write(f"{slug} apagado de vez\n")
    return 0


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO)
    parser = argparse.ArgumentParser(prog="python -m api.cli")
    commands = parser.add_subparsers(dest="command", required=True)
    create_admin = commands.add_parser("create-admin", help="cria ou promove um platform admin")
    create_admin.add_argument("email")
    create_admin.add_argument("name")
    commands.add_parser("purge-workspaces", help="apaga de vez os workspaces na lixeira há mais de 7 dias")
    delete = commands.add_parser("delete-workspace", help="apaga de vez um workspace agora, ativo ou na lixeira")
    delete.add_argument("slug")
    delete.add_argument("--yes", action="store_true", help="não pede para digitar o slug de novo")
    args = parser.parse_args(argv)

    code = 0
    with SessionLocal() as db:
        if args.command == "create-admin":
            temp = create_platform_admin(db, args.email, args.name)
            # the temp password is the command's output, not a log line: it must never go through logging
            sys.stdout.write(f"senha temporária: {temp}\n")
        elif args.command == "purge-workspaces":
            sys.stdout.write(f"{purge_trash(db)} workspace(s) apagado(s) de vez\n")
        else:
            code = delete_workspace(db, args.slug, args.yes)
    if code:
        sys.exit(code)


if __name__ == "__main__":
    main()
