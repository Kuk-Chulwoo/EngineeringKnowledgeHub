"""Local worker; external calls require an explicitly authorized queued run and policy."""

import argparse
import logging
import time

from ..ai.config import ProviderPolicy
from ..config import Settings
from ..database import Database
from ..repository import Repository
from ..services import HubService
from ..storage import LocalStorage
from .repository import EngineeringRepository
from .service import EngineeringService


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Process at most one queued run")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(message)s")
    settings = Settings.from_env()
    database = Database(settings.database_path)
    database.initialize()
    hub = HubService(
        Repository(database), LocalStorage(settings.storage_root), settings.max_upload_bytes
    )
    service = EngineeringService(EngineeringRepository(database), hub, ProviderPolicy.from_env())
    while True:
        worked = service.work_once()
        if args.once:
            return
        if not worked:
            time.sleep(1)


if __name__ == "__main__":
    main()
