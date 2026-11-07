"""Administrative commands (run on the server, e.g. ``docker compose exec api algotrader ...``).

Every command writes an audit entry.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import getpass
import os
import sys

from app.auth.service import AuthError, OwnerExistsError
from app.core.config import get_settings
from app.core.security import WeakPasswordError
from app.main import build_context


def _read_password(confirm: bool = True) -> str:
    env_pw = os.environ.get("ALGOTRADER_OWNER_PASSWORD")  # for non-interactive provisioning
    if env_pw:
        return env_pw
    pw = getpass.getpass("Password: ")
    if confirm and getpass.getpass("Repeat password: ") != pw:
        sys.exit("Passwords do not match.")
    return pw


async def _run(args: argparse.Namespace) -> int:
    ctx = build_context(get_settings())
    try:
        async with ctx.sessionmaker() as db:
            try:
                if args.command == "create-owner":
                    user = await ctx.auth.create_owner(db, args.email, _read_password())
                    await db.commit()
                    print(f"Owner {user.email} created. Log in to enrol MFA (mandatory).")
                elif args.command == "reset-mfa":
                    await ctx.auth.reset_mfa(db, args.email)
                    await db.commit()
                    print("MFA reset and all sessions revoked. Re-enrol at next login.")
                elif args.command == "change-password":
                    await ctx.auth.change_password(db, args.email, _read_password())
                    await db.commit()
                    print("Password changed and all sessions revoked.")
            except (OwnerExistsError, AuthError, WeakPasswordError) as exc:
                print(f"Error: {exc}", file=sys.stderr)
                return 1
    finally:
        await ctx.redis.aclose()
        await ctx.engine.dispose()
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(prog="algotrader")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("create-owner", "reset-mfa", "change-password"):
        p = sub.add_parser(name)
        p.add_argument("--email", required=True)
    sub.add_parser("generate-master-key", help="print a new random base64 master key")
    args = parser.parse_args()
    if args.command == "generate-master-key":
        print(base64.b64encode(os.urandom(32)).decode())
        return
    sys.exit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
