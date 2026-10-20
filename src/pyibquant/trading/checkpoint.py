"""Versioned strategy state and process ownership, separate from broker positions."""

from __future__ import annotations

from pathlib import Path
from typing import BinaryIO


class RunLease:
    """An OS-released lease prevents two local processes from executing one run."""

    def __init__(self, journal: Path, run_id: str) -> None:
        self.path = journal.with_name(journal.name + "." + run_id + ".lock")
        self._file: BinaryIO | None = None

    def acquire(self) -> None:
        from ..broker import BrokerError

        if self._file is not None:
            return
        try:
            import fcntl
        except ImportError as exc:
            raise BrokerError(
                "Execution recovery currently requires local POSIX file locks"
            ) from exc
        stream = self.path.open("a+b")
        self.path.chmod(0o600)
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            stream.close()
            raise BrokerError("Another local runner still owns this run") from exc
        self._file = stream

    def release(self) -> None:
        if self._file is not None:
            self._file.close()
            self._file = None
