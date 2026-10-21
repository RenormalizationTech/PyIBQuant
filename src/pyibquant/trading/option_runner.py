"""Selected long-option automation from completed underlying bars.

Shares lifecycle, risk, ownership and checkpoints with EquityRunner. Contract
selection is explicit; no rolling, expiry-day execution or multi-leg lifecycle.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from decimal import ROUND_DOWN, ROUND_UP, Decimal, InvalidOperation
from typing import Any

from ..bars import BarSeries
from ..broker import BrokerError, PaperBroker, money
from ..quotes import Option, Quote
from .funding import NY
from .option_order import round_limit, tick_at
from .runner import EquityRunner, RunnerConfig


class OptionRunner(EquityRunner):
    """One long selected contract, driven by underlying above/below-SMA targets.

    Completion/warmup uses the independent underlying one-minute bar feed.
    Execution uses the exact selected option's live quote and SMART tick ladder.
    Observation is the default via RunnerConfig.dry_run. Stops retain holdings.
    """

    def __init__(self, broker: PaperBroker, config: RunnerConfig, selector: Option,
                 *, entry_when: str = "above_sma", premium_grid: Decimal = Decimal(".05")) -> None:
        if selector.symbol != config.symbol or config.quantity != 1:
            raise ValueError("Option runner requires a matching underlying and one contract")
        if entry_when not in {"above_sma", "below_sma"}:
            raise ValueError("entry_when must be above_sma or below_sma")
        if (not isinstance(premium_grid, Decimal) or not premium_grid.is_finite()
            or premium_grid <= 0):
            raise ValueError("premium_grid must be a positive finite Decimal")
        super().__init__(broker, config)
        self.premium_grid = premium_grid
        self.selector, self.entry_when = selector, entry_when
        self._option_id: int | None = None
        self._multiplier: Decimal | None = None
        self._rules: tuple[tuple[Decimal, Decimal], ...] = ()

    @property
    def trade_instrument_id(self) -> int | None:
        return self._option_id

    def _prepare_contract(self, series: BarSeries) -> None:
        contract, rules = self.broker._adapter.resolve_option(self.selector)
        multiplier = money(contract.multiplier)
        if (type(contract.conId) is not int or contract.conId <= 0
            or multiplier is None or multiplier <= 0):
            raise BrokerError("Option runner requires resolved contract identity and multiplier")
        if ((self._option_id is not None and self._option_id != contract.conId)
            or (self._multiplier is not None and self._multiplier != multiplier)):
            raise BrokerError("Resolved option differs from the persisted trading contract")
        tick_at(Decimal(0), rules)
        self._option_id, self._multiplier, self._rules = contract.conId, multiplier, rules

    def _check_lifecycle(self, at: datetime) -> None:
        if self.selector.expiry <= at.astimezone(NY).date():
            raise BrokerError("Expiry-day and expired option strategies are unsupported")

    def _quote_matches(self, quote: Quote) -> bool:
        q = quote.instrument
        return (super()._quote_matches(quote) and q.asset_type == "option" and q.currency == "USD"
                and money(q.multiplier) == self._multiplier
                and q.expiry == self.selector.expiry.strftime("%Y%m%d")
                and money(q.strike) == money(self.selector.strike)
                and q.right == self.selector.right
                and (not self.selector.trading_class
                     or q.trading_class == self.selector.trading_class))

    def _limit_price(self, quote: Quote, side: str) -> Decimal:
        raw = Decimal(str(quote.ask if side == "BUY" else quote.bid))
        # TWS paper options do not reliably simulate penny fills. Use a coarser
        # explicit grid and still require the result to satisfy the real SMART rule.
        price = (raw / self.premium_grid).to_integral_value(
            rounding=ROUND_UP if side == "BUY" else ROUND_DOWN,
        ) * self.premium_grid
        if price <= 0:
            raise BrokerError("Option premium is below the configured execution grid")
        price = round_limit(price, side, self._rules)
        if price % self.premium_grid:
            raise BrokerError("Option premium grid conflicts with the broker tick ladder")
        return price

    def _notional(self, price: Decimal, quantity: Decimal) -> Decimal:
        if self._multiplier is None:
            raise BrokerError("Option multiplier is unresolved")
        return price * quantity * self._multiplier

    def _submit_order(self, side: str, quantity: int, price: Decimal, quote: Quote,
                      *, key: str) -> int:
        return self.broker.submit_option_limit(self.selector, side, quantity, float(price),
                                               quote=quote, tag=self.run_id, key=key)

    def _target(self, closes: list[float]) -> int:
        if self.entry_when == "above_sma":
            return super()._target(closes)
        return int(closes[-1] < sum(closes[-self.config.window:]) / self.config.window)

    def _execution_checkpoint(self) -> dict[str, Any]:
        return dict(kind="option", selector={**asdict(self.selector),
                    "expiry": self.selector.expiry.isoformat()}, entry_when=self.entry_when,
                    instrument_id=self._option_id,
                    multiplier=str(self._multiplier) if self._multiplier is not None else None,
                    premium_grid=str(self.premium_grid),
                    rules=[[str(edge), str(tick)] for edge, tick in self._rules])

    @classmethod
    def from_execution_checkpoint(cls, broker: PaperBroker, config: RunnerConfig,
                                  value: dict[str, Any]) -> OptionRunner:
        try:
            selector = Option(**{**value["selector"],
                                 "expiry": date.fromisoformat(value["selector"]["expiry"])})
            runner = cls(broker, config, selector, entry_when=value["entry_when"],
                         premium_grid=Decimal(value.get("premium_grid", ".05")))
            identity, multiplier = value["instrument_id"], money(value["multiplier"])
            rules = tuple((Decimal(e), Decimal(t)) for e, t in value["rules"])
            if type(identity) is not int or identity <= 0 or multiplier is None or multiplier <= 0:
                raise ValueError("invalid resolved option identity/multiplier")
            tick_at(Decimal(0), rules)
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise BrokerError(f"Invalid option runner checkpoint: {exc}") from exc
        runner._option_id, runner._multiplier, runner._rules = identity, multiplier, rules
        return runner
