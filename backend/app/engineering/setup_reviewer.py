"""Interactive local setup. Run with the project's Python environment."""

import getpass
import json

from ..config import Settings
from .auth import password_record


def main() -> None:
    settings = Settings.from_env()
    path = settings.reviewer_file
    if path is None:
        raise RuntimeError("Reviewer file path is not configured")
    name = input("Local engineer name: ").strip()
    password = getpass.getpass("Password (12+ characters): ")
    if password != getpass.getpass("Repeat password: "):
        raise ValueError("Passwords do not match")
    record = password_record(name, password)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and input("Replace existing reviewer credentials? [yes/no]: ") != "yes":
        return
    path.write_text(json.dumps(record), encoding="utf-8")
    print("Reviewer configured. Restart backend to invalidate existing sessions.")


if __name__ == "__main__":
    main()
