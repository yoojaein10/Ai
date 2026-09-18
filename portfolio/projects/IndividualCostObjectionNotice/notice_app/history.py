from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path


class SendHistory:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute(
            """
            CREATE TABLE IF NOT EXISTS send_history (
                notice_month TEXT NOT NULL,
                recipient_id TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                PRIMARY KEY (notice_month, recipient_id)
            )
            """
        )
        self.connection.commit()

    def was_sent(self, notice_month: str, recipient_id: str) -> bool:
        row = self.connection.execute(
            "SELECT 1 FROM send_history WHERE notice_month = ? AND recipient_id = ?",
            (notice_month, recipient_id),
        ).fetchone()
        return row is not None

    def mark_sent(self, notice_month: str, recipient_id: str) -> None:
        self.connection.execute(
            "INSERT OR IGNORE INTO send_history(notice_month, recipient_id, sent_at) VALUES (?, ?, ?)",
            (notice_month, recipient_id, datetime.now().astimezone().isoformat(timespec="seconds")),
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "SendHistory":
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

