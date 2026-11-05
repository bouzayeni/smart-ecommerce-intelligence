"""Create (or promote) an admin user. Self-registration only creates viewers.

The password is read from the ADMIN_PASSWORD environment variable or prompted for; it is
never accepted as a command-line argument (shell history, process lists).

Usage (from the repo root):
    uv run --all-groups python backend/scripts/create_admin.py --email you@example.com --name "You"
"""

import argparse
import getpass
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.db.session import app_engine  # noqa: E402
from app.models.entities import User  # noqa: E402
from app.schemas.auth import RegisterRequest  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--email", required=True)
    parser.add_argument("--name", required=True)
    args = parser.parse_args()
    password = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Admin password: ")
    RegisterRequest(email=args.email, password=password, full_name=args.name)  # same rules
    email = args.email.lower()

    with Session(app_engine()) as session, session.begin():
        user = session.scalar(select(User).where(User.email == email))
        if user:
            user.role, action = "admin", "promoted"
        else:
            session.add(
                User(
                    email=email,
                    full_name=args.name,
                    password_hash=hash_password(password),
                    role="admin",
                )
            )
            action = "created"
    print(f"Admin {action}: {email}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
