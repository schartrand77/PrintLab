from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth import hash_password


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a PrintLab password hash.")
    parser.add_argument("password", nargs="?", help="Plaintext password. If omitted, prompts securely.")
    args = parser.parse_args()

    password = args.password or getpass.getpass("Password: ")
    if not password:
        raise SystemExit("Password cannot be empty.")

    print(hash_password(password))


if __name__ == "__main__":
    main()
