from __future__ import annotations

import argparse

from sqlalchemy.exc import IntegrityError

from src.db import SessionLocal
from src.platform.auth.password_service import PasswordService
from src.platform.auth.user_repository import UserRepository


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a goldenshare user")
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--display-name")
    parser.add_argument("--email")
    parser.add_argument("--admin", action="store_true")
    args = parser.parse_args()

    password_hash = PasswordService().hash_password(args.password)
    repository = UserRepository()

    with SessionLocal() as session:
        try:
            repository.create_user(
                session,
                username=args.username.strip(),
                password_hash=password_hash,
                display_name=args.display_name,
                email=args.email,
                is_admin=args.admin,
            )
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise SystemExit(f"user already exists: {args.username}") from exc

    print(f"created user: {args.username}")


if __name__ == "__main__":
    main()
