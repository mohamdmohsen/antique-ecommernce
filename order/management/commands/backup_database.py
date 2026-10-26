import os
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import subprocess

from django.core.management.base import BaseCommand, CommandError
from django.db import connections


class Command(BaseCommand):
    help = "Create a private, consistent SQLite or PostgreSQL backup without overwriting files"

    def add_arguments(self, parser):
        parser.add_argument("--directory", required=True)

    def handle(self, *args, **options):
        directory = Path(options["directory"]).expanduser().resolve()
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        db = connections["default"]
        engine = db.settings_dict["ENGINE"]
        suffix = ".sqlite3" if engine.endswith("sqlite3") else ".dump"
        path = directory / ("antique-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + suffix)
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            if engine.endswith("sqlite3"):
                os.close(fd)
                fd = None
                db.ensure_connection()
                destination = sqlite3.connect(str(path))
                try:
                    db.connection.backup(destination)
                    if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                        raise CommandError("Backup integrity check failed.")
                finally:
                    destination.close()
            elif engine.endswith("postgresql"):
                with os.fdopen(fd, "wb") as output:
                    fd = None
                    cfg = db.settings_dict
                    env = {**os.environ, "PGPASSWORD": cfg.get("PASSWORD", "")}
                    command = ["pg_dump", "--format=custom", "--no-owner", "--no-acl", "--lock-wait-timeout=30s", "--dbname", cfg["NAME"]]
                    for key, flag in [("HOST", "--host"), ("PORT", "--port"), ("USER", "--username")]:
                        if cfg.get(key):
                            command += [flag, str(cfg[key])]
                    result = subprocess.run(command, env=env, stdout=output, stderr=subprocess.PIPE, check=False, timeout=300)
                    if result.returncode:
                        raise CommandError("pg_dump failed. Check database access and the installed client version.")
            else:
                raise CommandError("Only SQLite and PostgreSQL backups are supported.")
        except Exception as exc:
            if fd is not None:
                os.close(fd)
            path.unlink(missing_ok=True)
            if isinstance(exc, CommandError):
                raise
            raise CommandError("Backup failed. Check database and directory permissions.") from exc
        self.stdout.write(str(path))
