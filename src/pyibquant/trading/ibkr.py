"""Dedicated TWS broker transport. SDK objects never escape the public broker API."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from math import isfinite
from threading import Event, Lock, Thread
from typing import Any

from ibapi import get_version_string
from ibapi.client import EClient
from ibapi.contract import Contract
from ibapi.execution import ExecutionFilter
from ibapi.order import Order
from ibapi.wrapper import EWrapper

from ..broker import BrokerError, money
from ..quotes import Option

if tuple(int(v) for v in get_version_string().split(".")[:2]) < (10, 33):
    raise ImportError("PaperBroker requires the official TWS API 10.33 or newer")


def number(value: Any) -> str | None:
    result = money(value)
    return str(result) if result is not None else None


def instrument(contract: Any) -> dict[str, Any]:
    return dict(
        con_id=contract.conId,
        symbol=contract.symbol,
        asset_type=contract.secType,
        currency=contract.currency,
        multiplier=getattr(contract, "multiplier", ""),
        expiry=getattr(contract, "lastTradeDateOrContractMonth", ""),
        local_symbol=getattr(contract, "localSymbol", ""),
    )


class BrokerAdapter(EWrapper, EClient):
    def __init__(self, host: str, port: int, client_id: int, timeout: float) -> None:
        if not 1 <= port <= 65535 or client_id <= 0 or not isfinite(timeout) or timeout <= 0:
            raise ValueError("Use a valid port, positive dedicated client_id and timeout")
        EClient.__init__(self, self)
        self.host, self.port, self.client_id, self.timeout = host, port, client_id, timeout
        self.sink: Callable[[str, dict[str, Any]], None] = lambda kind, data: None
        self.prepare: Callable[[], None] = lambda: None
        self._ready, self._accounts_ready = Event(), Event()
        self.accounts: list[str] = []
        self.account = ""
        self._next_id = 0
        self._id_lock = Lock()
        self._thread: Thread | None = None
        self._errors: list[str] = []
        self._request = 9000
        self._summary_id = -1
        self._execution_id = -1
        self._pnl_id = -1
        self._contract_id = -1
        self._contract_done = Event()
        self._contracts: list[Any] = []
        self._details: list[Any] = []
        self._rules: dict[int, tuple[tuple[Decimal, Decimal], ...]] = {}
        self._rule_done = Event()
        self._rule_id = -1
        self._contract_error: str | None = None
        self._closing = False
        self._completed_lock = Lock()
        self._completed_done = Event()
        self._completed_busy = False
        self._completed_failed = False
        self._completed_rows: list[dict[str, Any]] = []

    def completed_orders(self, account: str) -> list[dict[str, Any]]:
        """Serialized read-only download. A timed-out untagged request cannot be reused."""
        with self._completed_lock:
            if self._completed_busy or self._completed_failed:
                raise BrokerError("Completed-order request unresolved; open a new broker session")
            if not self.isConnected():
                raise BrokerError("Broker is disconnected")
            self._completed_busy = True
            self._completed_rows = []
            self._completed_done.clear()
        try:
            self.reqCompletedOrders(False)
            if not self._completed_done.wait(self.timeout) or not self.isConnected():
                raise BrokerError("Completed-order download incomplete; no terminal state inferred")
            with self._completed_lock:
                return [dict(row) for row in self._completed_rows if row["account"] == account]
        except BaseException:
            with self._completed_lock:
                self._completed_failed = True
            raise
        finally:
            with self._completed_lock:
                self._completed_busy = False

    def completedOrder(self, contract: Any, order: Any, orderState: Any) -> None:
        with self._completed_lock:
            if not self._completed_busy or self._completed_failed or self._completed_done.is_set():
                return
            self._completed_rows.append(dict(
                account=order.account,
                **instrument(contract),
                order_id=order.orderId,
                client_id=order.clientId,
                perm_id=order.permId,
                order_ref=order.orderRef,
                side=order.action,
                quantity=number(order.totalQuantity),
                filled=number(order.filledQuantity),
                status=orderState.status,
                completed_time=orderState.completedTime,
                completed_status=orderState.completedStatus,
            ))

    def completedOrdersEnd(self) -> None:
        with self._completed_lock:
            if self._completed_busy and not self._completed_failed:
                self._completed_done.set()

    def open(self) -> list[str]:
        self.connect(self.host, self.port, self.client_id)
        self._thread = Thread(target=self.run, daemon=True, name="pyibquant-paper-api")
        self._thread.start()
        if not self._ready.wait(self.timeout):
            raise BrokerError("Broker handshake failed: " + "; ".join(self._errors))
        self.reqManagedAccts()
        if not self._accounts_ready.wait(self.timeout) or not self.isConnected():
            raise BrokerError("Managed-account download failed")
        return list(self.accounts)

    def nextValidId(self, orderId: int) -> None:
        with self._id_lock:
            self._next_id = max(self._next_id, orderId)
        self._ready.set()

    def seed_order_id(self, minimum: int) -> None:
        with self._id_lock:
            self._next_id = max(self._next_id, minimum)

    def allocate_id(self) -> int:
        with self._id_lock:
            if not self._ready.is_set() or not self.isConnected():
                raise BrokerError("No valid order ID while disconnected")
            oid = self._next_id
            self._next_id += 1
            return oid

    def managedAccounts(self, accountsList: str) -> None:
        self.accounts = [a for a in accountsList.split(",") if a]
        self._accounts_ready.set()

    def subscribe(self, account: str) -> None:
        self.account = account
        self.refresh(account)
        self.request_pnl(account)

    def request_pnl(self, account: str) -> int:
        """Renew the read-only subscription; generations reject late old callbacks."""
        if not self.isConnected():
            raise BrokerError("Broker is disconnected")
        if self._pnl_id >= 0:
            self.cancelPnL(self._pnl_id)
        self._request += 10
        self._pnl_id = self._request
        self.reqPnL(self._pnl_id, account, "")
        return self._pnl_id

    def refresh(self, account: str) -> None:
        if not self.isConnected():
            raise BrokerError("Broker is disconnected")
        self.prepare()
        self.reqAccountUpdates(False, account)
        self._request += 10
        self._execution_id = self._request + 1
        self.reqAccountUpdates(True, account)
        # Account summary is a persistent subscription, not a snapshot request.
        # Cancellation is asynchronous: recreating it on rapid refreshes can hit
        # TWS's active-summary limit before canceled subscriptions are released.
        if self._summary_id < 0:
            self._summary_id = self._request
            self.reqAccountSummary(
                self._summary_id,
                "All",
                "AccountType,NetLiquidation,TotalCashValue,SettledCash,"
                "BuyingPower,AvailableFunds,ExcessLiquidity,InitMarginReq,"
                "MaintMarginReq,GrossPositionValue",
            )
        self.cancelPositions()
        self.reqPositions()
        self.reqAllOpenOrders()
        filt = ExecutionFilter()
        filt.acctCode = account
        self.reqExecutions(self._execution_id, filt)

    def accountSummary(self, reqId: int, account: str, tag: str, value: str, currency: str) -> None:
        if reqId == self._summary_id:
            self.sink(
                "value",
                dict(
                    account=account,
                    tag=tag,
                    value=value,
                    currency=currency,
                    source="account_summary",
                ),
            )

    def accountSummaryEnd(self, reqId: int) -> None:
        if reqId == self._summary_id:
            self.sink("barrier", dict(name="summary"))

    def updateAccountValue(self, key: str, val: str, currency: str, accountName: str) -> None:
        self.sink(
            "value",
            dict(
                account=accountName, tag=key, currency=currency, value=val, source="account_updates"
            ),
        )

    def accountDownloadEnd(self, accountName: str) -> None:
        if accountName == self.account:
            self.sink("barrier", dict(name="account"))

    def updateAccountTime(self, timeStamp: str) -> None:
        self.sink("heartbeat", dict(broker_time=timeStamp))

    def position(self, account: str, contract: Any, position: Decimal, avgCost: float) -> None:
        self.sink(
            "position",
            dict(
                account=account,
                **instrument(contract),
                quantity=number(position),
                average_cost=number(avgCost),
            ),
        )

    def positionEnd(self) -> None:
        self.sink("barrier", dict(name="positions"))

    def updatePortfolio(
        self,
        contract: Any,
        position: Decimal,
        marketPrice: float,
        marketValue: float,
        averageCost: float,
        unrealizedPNL: float,
        realizedPNL: float,
        accountName: str,
    ) -> None:
        self.sink(
            "portfolio",
            dict(
                account=accountName,
                **instrument(contract),
                quantity=number(position),
                average_cost=number(averageCost),
                market_price=number(marketPrice),
                market_value=number(marketValue),
                unrealized_pnl=number(unrealizedPNL),
                realized_pnl=number(realizedPNL),
            ),
        )

    def pnl(self, reqId: int, dailyPnL: float, unrealizedPnL: float, realizedPnL: float) -> None:
        if reqId != self._pnl_id:
            return
        self.sink(
            "pnl",
            dict(
                daily=number(dailyPnL),
                unrealized=number(unrealizedPnL),
                realized=number(realizedPnL),
                source="reqPnL",
                request_id=reqId,
            ),
        )

    def openOrder(self, orderId: int, contract: Any, order: Any, orderState: Any) -> None:
        with self._id_lock:
            self._next_id = max(self._next_id, orderId + 1)
        self.sink(
            "order",
            dict(
                account=order.account,
                **instrument(contract),
                order_id=orderId,
                client_id=order.clientId,
                perm_id=order.permId,
                order_ref=order.orderRef,
                side=order.action,
                quantity=number(order.totalQuantity),
                order_type=order.orderType,
                limit_price=number(order.lmtPrice),
                status=orderState.status,
            ),
        )

    def openOrderEnd(self) -> None:
        self.sink("barrier", dict(name="orders"))

    def orderStatus(
        self,
        orderId: int,
        status: str,
        filled: Decimal,
        remaining: Decimal,
        avgFillPrice: float,
        permId: int,
        parentId: int,
        lastFillPrice: float,
        clientId: int,
        whyHeld: str,
        mktCapPrice: float,
    ) -> None:
        with self._id_lock:
            self._next_id = max(self._next_id, orderId + 1)
        self.sink(
            "order_status",
            dict(
                order_id=orderId,
                status=status,
                filled=number(filled),
                remaining=number(remaining),
                average_fill_price=number(avgFillPrice),
                perm_id=permId,
                client_id=clientId,
                held_reason=whyHeld,
            ),
        )

    def execDetails(self, reqId: int, contract: Any, execution: Any) -> None:
        self.sink(
            "execution",
            dict(
                account=execution.acctNumber,
                **instrument(contract),
                exec_id=execution.execId,
                order_id=execution.orderId,
                client_id=execution.clientId,
                perm_id=execution.permId,
                order_ref=execution.orderRef,
                side=execution.side,
                quantity=number(execution.shares),
                price=number(execution.price),
                cumulative_quantity=number(execution.cumQty),
                average_fill_price=number(execution.avgPrice),
                broker_time=execution.time,
            ),
        )

    def execDetailsEnd(self, reqId: int) -> None:
        if reqId == self._execution_id:
            self.sink("barrier", dict(name="executions"))

    def commissionAndFeesReport(self, commissionAndFeesReport: Any) -> None:
        r = commissionAndFeesReport
        self.sink(
            "fee",
            dict(
                exec_id=r.execId,
                commission=number(r.commissionAndFees),
                fee_currency=r.currency,
                realized_pnl=number(r.realizedPNL),
            ),
        )

    def commissionReport(self, commissionReport: Any) -> None:
        # SDK versions before commissionAndFeesReport use this callback.
        r = commissionReport
        self.sink(
            "fee",
            dict(
                exec_id=r.execId,
                commission=number(r.commission),
                fee_currency=r.currency,
                realized_pnl=number(r.realizedPNL),
            ),
        )

    def error(self, *args: Any) -> None:
        if len(args) >= 4 and isinstance(args[2], int):
            req_id, code, message = args[0], args[2], args[3]
        elif len(args) >= 3:
            req_id, code, message = args[:3]
        else:
            return
        if code in {2104, 2106, 2107, 2108, 2158}:
            return
        description = f"IBKR {code}: {message}"
        if self.account:
            description = description.replace(self.account, "<account>")
        self._errors.append(description)
        if req_id == self._contract_id:
            self._contract_error = description
            self._contract_done.set()
        fatal = code in {502, 504, 1100, 1300, 326} or (
            req_id == self._summary_id
            and code in {321, 322}
            and "accountsummary" in message.lower()
        )
        if code == 1100:
            self.sink("disconnected", dict(message=description))
        else:
            self.sink("error", dict(message=description, code=code, request_id=req_id, fatal=fatal))

    def connectionClosed(self) -> None:
        self.sink("disconnected", dict(message="API socket closed; reconcile before resuming"))

    def resolve(self, symbol: str) -> Any:
        self._request += 1
        self._contract_id = self._request
        self._contracts = []
        self._details = []
        self._contract_error = None
        self._contract_done.clear()
        c = Contract()
        c.symbol, c.secType, c.exchange, c.currency = symbol, "STK", "SMART", "USD"
        self.reqContractDetails(self._contract_id, c)
        if not self._contract_done.wait(self.timeout) or self._contract_error:
            raise BrokerError(self._contract_error or "Equity contract resolution timed out")
        if len(self._contracts) != 1:
            raise BrokerError("Equity contract resolution must return exactly one contract")
        result = self._contracts[0]
        if result.secType != "STK" or result.currency != "USD" or result.conId <= 0:
            raise BrokerError("Only resolved USD equities are supported")
        return result

    def resolve_option(self, selector: Option) -> tuple[Any, tuple[tuple[Decimal, Decimal], ...]]:
        """Resolve an exact USD option plus its SMART price-increment ladder."""
        self._request += 1
        self._contract_id = self._request
        self._contract_done.clear()
        self._contracts, self._details = [], []
        self._contract_error = None
        c = Contract()
        c.symbol, c.secType, c.currency, c.exchange = selector.symbol, "OPT", "USD", "SMART"
        c.lastTradeDateOrContractMonth = selector.expiry.strftime("%Y%m%d")
        c.strike, c.right, c.tradingClass = selector.strike, selector.right, selector.trading_class
        if selector.multiplier is not None:
            c.multiplier = str(selector.multiplier)
        self.reqContractDetails(self._contract_id, c)
        if not self._contract_done.wait(self.timeout) or self._contract_error:
            raise BrokerError(self._contract_error or "Option resolution incomplete")
        if len(self._details) != 1:
            raise BrokerError("Option must resolve to exactly one contract")
        detail = self._details[0]
        contract = detail.contract
        multiplier = money(contract.multiplier)
        if (
            contract.secType != "OPT" or contract.currency != "USD" or contract.conId <= 0
            or contract.symbol != selector.symbol or contract.right != selector.right
            or money(contract.strike) != money(selector.strike)
            or contract.lastTradeDateOrContractMonth[:8] != selector.expiry.strftime("%Y%m%d")
            or multiplier is None or multiplier <= 0
            or (selector.multiplier is not None and multiplier != money(selector.multiplier))
            or (selector.trading_class and contract.tradingClass != selector.trading_class)
        ):
            raise BrokerError("Resolved option identity or multiplier mismatch")
        venues = detail.validExchanges.split(",")
        rule_ids = detail.marketRuleIds.split(",")
        if len(venues) != len(rule_ids) or "SMART" not in venues:
            raise BrokerError("No explicit SMART option tick rule")
        raw_rule = rule_ids[venues.index("SMART")]
        if not raw_rule.isdigit() or int(raw_rule) <= 0:
            raise BrokerError("Missing SMART option tick rule")
        rule_id = int(raw_rule)
        if rule_id not in self._rules:
            self._rule_id = rule_id
            self._rule_done.clear()
            self.reqMarketRule(rule_id)
            if not self._rule_done.wait(self.timeout):
                raise BrokerError("Option price-increment download incomplete")
        rules = self._rules.get(rule_id, ())
        if not rules or rules[0][0] != 0:
            raise BrokerError("Invalid or missing option price-increment ladder")
        contract.exchange = "SMART"
        return contract, rules

    def marketRule(self, marketRuleId: int, priceIncrements: list[Any]) -> None:
        if marketRuleId != self._rule_id:
            return
        rows = [(money(p.lowEdge), money(p.increment)) for p in priceIncrements]
        if rows and all(edge is not None and edge >= 0 and tick is not None and tick > 0
                        for edge, tick in rows):
            valid = [(edge, tick) for edge, tick in rows if edge is not None and tick is not None]
            if all(valid[i][0] < valid[i + 1][0] for i in range(len(valid) - 1)):
                self._rules[marketRuleId] = tuple(valid)
        self._rule_done.set()

    def contractDetails(self, reqId: int, contractDetails: Any) -> None:
        if reqId == self._contract_id:
            self._contracts.append(contractDetails.contract)
            self._details.append(contractDetails)

    def contractDetailsEnd(self, reqId: int) -> None:
        if reqId == self._contract_id:
            self._contract_done.set()

    def send_order(
        self,
        oid: int,
        contract: Any,
        side: str,
        quantity: int,
        price: Decimal | None,
        account: str,
        ref: str,
    ) -> None:
        order = Order()
        order.account, order.orderRef, order.action = account, ref, side
        order.totalQuantity = Decimal(quantity)
        order.orderType = "MKT" if price is None else "LMT"
        if price is not None:
            order.lmtPrice = float(price)
        order.tif, order.outsideRth, order.transmit = "DAY", False, True
        self.placeOrder(oid, contract, order)

    def cancel_order(self, oid: int) -> None:
        try:
            from ibapi.order_cancel import OrderCancel
        except ImportError:
            self.cancelOrder(oid, "")
        else:
            self.cancelOrder(oid, OrderCancel())

    def close(self) -> None:
        self._closing = True
        if self.isConnected():
            self.reqAccountUpdates(False, self.account)
            self.cancelPositions()
            if self._summary_id >= 0:
                self.cancelAccountSummary(self._summary_id)
            if self._pnl_id >= 0:
                self.cancelPnL(self._pnl_id)
            self.disconnect()
        if self._thread is not None:
            self._thread.join(3)
