"""Saved paper configuration; files can never opt into order transmission."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any

from ..broker import money
from .runner import RunnerConfig


@dataclass(frozen=True)
class PaperProfile:
    version: int = 1
    symbol: str = "AAPL"
    host: str = "127.0.0.1"
    port: int = 7497
    broker_client_id: int = 276
    market_client_id: int = 277
    preflight_client_id: int = 288
    account: str | None = None
    journal: Path = Path("charts/paper/strategy.sqlite3")
    window: int = 20
    quantity: int = 1
    max_order_value: float = 500
    max_orders: int = 4
    max_session_loss: float = 25
    max_data_age: float = 15
    seconds: float = 600
    cancel_on_stop: bool = True

    def __post_init__(self) -> None:
        self.runner_config()
        if type(self.version) is not int or self.version != 1:
            raise ValueError("Unsupported paper profile version")
        if not isinstance(self.host, str) or not self.host or any(c.isspace() for c in self.host):
            raise ValueError("host must be a nonempty host name/address")
        for value in (
            self.port,
            self.broker_client_id,
            self.market_client_id,
            self.preflight_client_id,
        ):
            if type(value) is not int or value <= 0:
                raise ValueError("Port/client IDs must be positive integers")
        if (
            self.port > 65535
            or len({self.broker_client_id, self.market_client_id, self.preflight_client_id}) != 3
        ):
            raise ValueError("Use a valid port and three distinct client IDs")
        if self.account is not None and (
            not isinstance(self.account, str)
            or not self.account.startswith("DU")
            or not self.account[2:].isalnum()
        ):
            raise ValueError("Only a DU paper account may be selected")
        if any(
            type(v) not in (int, float)
            for v in (self.max_order_value, self.max_session_loss, self.max_data_age, self.seconds)
        ):
            raise ValueError("Risk caps, data age and duration must be JSON numbers")
        cap, duration = money(self.max_order_value), money(self.seconds)
        if isinstance(self.max_order_value, bool) or cap is None or cap <= 0:
            raise ValueError("max_order_value must be positive and finite")
        if isinstance(self.seconds, bool) or duration is None or not 0 < duration <= 3600:
            raise ValueError("seconds must be between 0 and 3600")
        if not isinstance(self.cancel_on_stop, bool):
            raise ValueError("cancel_on_stop must be a boolean")
        if not isinstance(self.journal, Path) or not self.journal.name:
            raise ValueError("journal must name a SQLite file")

    def runner_config(self, *, execute: bool = False) -> RunnerConfig:
        return RunnerConfig(
            self.symbol,
            window=self.window,
            quantity=self.quantity,
            dry_run=not execute,
            max_orders=self.max_orders,
            max_session_loss=self.max_session_loss,
            max_data_age=self.max_data_age,
        )

    def broker_options(self, *, execute: bool = False, preflight: bool = False) -> dict[str, Any]:
        if preflight and execute:
            raise ValueError("Preflight cannot enable order transmission")
        return dict(
            host=self.host,
            port=self.port,
            account=self.account,
            journal=self.journal,
            client_id=self.preflight_client_id if preflight else self.broker_client_id,
            max_order_value=self.max_order_value,
            max_quantity=self.quantity,
            readonly=not execute,
            paper_confirmed=execute,
        )

    @classmethod
    def load(cls, path: str | Path) -> PaperProfile:
        source = Path(path).expanduser().resolve()
        data = json.loads(source.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Paper profile must be a JSON object")
        try:
            profile = cls(
                **{**data, "journal": Path(data.get("journal", "../charts/paper/strategy.sqlite3"))}
            )
        except TypeError as exc:
            raise ValueError(f"Invalid paper profile fields: {exc}") from exc
        journal = profile.journal.expanduser()
        return replace(
            profile,
            journal=(source.parent / journal).resolve() if not journal.is_absolute() else journal,
        )

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "journal": str(self.journal)}
