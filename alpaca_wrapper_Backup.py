"""
alpaca_wrapper.py
-----------------
Alpaca Paper Trading + HTML Modal + Buy/Sell (Market/Limit) + Connection Label
"""

import time
from flask import Blueprint, request, jsonify
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import (
    MarketOrderRequest,
    LimitOrderRequest,
    GetOrdersRequest,
)
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.data import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest

alpaca_app = Blueprint('alpaca', __name__)

# =================== HARDCODED CREDENTIALS ===================
APCA_API_KEY_ID = "PK755UFOVXASYQEI6NTANGPPPG"      # REPLACE WITH YOUR KEY
APCA_API_SECRET_KEY = "DkH5nEDVfRzW9avvxbz6MTqKmbqvw8oJiQJfmGLyQk51"  # REPLACE WITH YOUR SECRET
# ============================================================

class AlpacaTrader:
    def __init__(self):
        if not APCA_API_KEY_ID or not APCA_API_SECRET_KEY:
            raise ValueError("APCA_API_KEY_ID and APCA_API_SECRET_KEY must be set in alpaca_wrapper.py")

        self.trading_client = TradingClient(APCA_API_KEY_ID, APCA_API_SECRET_KEY, paper=True)
        self.data_client = StockHistoricalDataClient(APCA_API_KEY_ID, APCA_API_SECRET_KEY)

        try:
            self.account = self.trading_client.get_account()
            self.equity = float(self.account.equity)
            self.cash = float(self.account.cash)
            self.is_connected = True
            account_id_str = str(self.account.id)
            print(f"ALPACA PAPER CONNECTED – Account: {account_id_str[:8]}... | Equity: ${self.equity:,.2f}")
        except Exception as e:
            self.is_connected = False
            print(f"ALPACA CONNECTION FAILED: {e}")
            raise ConnectionError(f"Alpaca connection failed: {e}")

    def _wait_for_fill(self, order_id, max_wait=300):
        start = time.time()
        while time.time() - start < max_wait:
            try:
                order = self.trading_client.get_order_by_id(order_id)
                if order.status == QueryOrderStatus.FILLED:
                    return order
            except:
                pass
            time.sleep(2)
        return None

    def buy_stock(self, symbol: str, qty: int, order_type: str = 'market', limit_price: float = None, profit_target: float = None):
        if qty <= 0:
            return {'success': False, 'message': 'Quantity must be > 0'}
        if order_type == 'limit' and (limit_price is None or limit_price <= 0):
            return {'success': False, 'message': 'Valid limit price required for limit orders'}

        try:
            if order_type == 'market':
                req = MarketOrderRequest(
                    symbol=symbol, qty=qty, side=OrderSide.BUY, time_in_force=TimeInForce.GTC
                )
            else:
                req = LimitOrderRequest(
                    symbol=symbol, qty=qty, side=OrderSide.BUY, time_in_force=TimeInForce.GTC,
                    limit_price=round(limit_price, 2)
                )
            order = self.trading_client.submit_order(req)
            print(f"BUY {order_type.upper()} {order.id} – {qty} {symbol}")

            filled = self._wait_for_fill(order.id)
            if not filled:
                return {'success': False, 'message': f'Order not filled (status: {order.status.value})'}

            avg_price = float(filled.filled_avg_price)
            msg = f = f"Buy filled @ ${avg_price:.2f}"

            sell_order_id = None
            if profit_target and order_type == 'market':
                target_price = avg_price * (1 + profit_target / 100)
                sell_req = LimitOrderRequest(
                    symbol=symbol, qty=qty, side=OrderSide.SELL,
                    time_in_force=TimeInForce.GTC, limit_price=round(target_price, 2)
                )
                sell_order = self.trading_client.submit_order(sell_req)
                sell_order_id = sell_order.id
                msg += f" | Auto-sell limit @ ${target_price:.2f} (order {sell_order.id})"

            return {
                'success': True,
                'order_id': order.id,
                'avg_price': avg_price,
                'message': msg,
                'sell_order_id': sell_order_id
            }

        except Exception as e:
            return {'success': False, 'message': f'Buy error: {str(e)}'}

    def sell_stock(self, symbol: str, qty: int, order_type: str = 'market', limit_price: float = None):
        if qty <= 0:
            return {'success': False, 'message': 'Quantity must be > 0'}
        if order_type == 'limit' and (limit_price is None or limit_price <= 0):
            return {'success': False, 'message': 'Valid limit price required'}

        try:
            positions = self.trading_client.get_all_positions()
            pos = next((p for p in positions if p.symbol == symbol), None)
            if not pos or float(pos.qty) < qty:
                return {'success': False, 'message': f'Not enough shares: have {pos.qty if pos else 0}, need {qty}'}
        except Exception as e:
            return {'success': False, 'message': f'Position check failed: {e}'}

        try:
            if order_type == 'market':
                req = MarketOrderRequest(
                    symbol=symbol, qty=qty, side=OrderSide.SELL, time_in_force=TimeInForce.GTC
                )
            else:
                req = LimitOrderRequest(
                    symbol=symbol, qty=qty, side=OrderSide.SELL, time_in_force=TimeInForce.GTC,
                    limit_price=round(limit_price, 2)
                )
            order = self.trading_client.submit_order(req)
            print(f"SELL {order_type.upper()} {order.id} – {qty} {symbol}")

            filled = self._wait_for_fill(order.id)
            if not filled:
                return {'success': False, 'message': f'Order not filled (status: {order.status.value})'}

            avg_price = float(filled.filled_avg_price)
            return {
                'success': True,
                'order_id': order.id,
                'avg_price': avg_price,
                'message': f"Sell filled @ ${avg_price:.2f}"
            }

        except Exception as e:
            return {'success': False, 'message': f'Sell error: {str(e)}'}

    def get_positions_html(self) -> str:
        if not self.is_connected:
            return '<p style="color:#ef4444">Failed to connect to Alpaca Paper Trading.</p>'

        account_id_str = str(self.account.id)
        conn_label = f"""
        <div style="background:linear-gradient(135deg,#10b981,#34d399);color:white;padding:8px 12px;border-radius:8px;
                    font-weight:600;font-size:0.9rem;margin-bottom:12px;text-align:center;">
            Connected to Alpaca Paper Trading | ID: {account_id_str[:8]}... | Equity: ${self.equity:,.2f} | Cash: ${self.cash:,.2f}
        </div>
        """

        quick_form = """
        <div style="background:var(--glass);padding:10px;border-radius:8px;margin-bottom:12px;">
            <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr 1fr 1fr 1fr;gap:6px;align-items:end;">
                <input id="quickSymbol" placeholder="Symbol" style="padding:6px;font-size:0.85rem;">
                <input id="quickQty" type="number" min="1" placeholder="Qty" style="padding:6px;font-size:0.85rem;">
                <select id="quickType" style="padding:6px;font-size:0.85rem;">
                    <option value="market">Market</option>
                    <option value="limit">Limit</option>
                </select>
                <input id="quickLimit" type="number" step="0.01" placeholder="Limit $" style="padding:6px;font-size:0.85rem;">
                <input id="quickProfit" type="number" step="0.1" placeholder="Profit %" style="padding:6px;font-size:0.85rem;">
                <button onclick="quickBuy()" class="btn btn-success" style="padding:6px;font-size:0.8rem;">Buy</button>
                <button onclick="quickSell()" class="btn btn-danger" style="padding:6px;font-size:0.8rem;">Sell</button>
            </div>
        </div>
        """

        try:
            positions = self.trading_client.get_all_positions()
            if not positions:
                return conn_label + quick_form + "<p style='text-align:center;color:#888'>No open positions.</p>"

            symbols = [p.symbol for p in positions]
            quotes = self.data_client.get_stock_latest_quote(
                StockLatestQuoteRequest(symbols_or_symbols=symbols)
            )

            rows = []
            for pos in positions:
                sym = pos.symbol
                qty = float(pos.qty)
                entry = float(pos.avg_entry_price)
                cur = float(quotes[sym].askprice) if sym in quotes else 0.0
                unreal_pl = float(pos.unrealized_pl)
                unreal_pct = (unreal_pl / (qty * entry) * 100) if qty * entry else 0.0
                realized = float(pos.pl)

                action_btns = f"""
                <button onclick="placeOrder('{sym}','buy',{int(qty)})" class="btn btn-success" style="padding:3px 6px;font-size:0.75rem;margin:1px;">Buy</button>
                <button onclick="placeOrder('{sym}','sell',{int(qty)})" class="btn btn-danger" style="padding:3px 6px;font-size:0.75rem;margin:1px;">Sell</button>
                """

                rows.append(f"""
                <tr>
                    <td>{sym} {action_btns}</td>
                    <td style="text-align:right">{qty:,.0f}</td>
                    <td style="text-align:right">${entry:,.2f}</td>
                    <td style="text-align:right">${cur:,.2f}</td>
                    <td style="text-align:right;color:{'green' if unreal_pl>=0 else 'red'}">${unreal_pl:,.2f}</td>
                    <td style="text-align:right;color:{'green' if unreal_pl>=0 else 'red'}">{unreal_pct:+.2f}%</td>
                    <td style="text-align:right">${realized:,.2f}</td>
                </tr>
                """)

            table = f"""
            <table style="width:100%;border-collapse:collapse;font-size:0.85rem;">
                <thead>
                    <tr style="background:#1e293b;color:#e2e8f0;">
                        <th style="padding:6px;text-align:left;">Symbol</th>
                        <th style="padding:6px;text-align:right;">Qty</th>
                        <th style="padding:6px;text-align:right;">Entry</th>
                        <th style="padding:6px;text-align:right;">Current</th>
                        <th style="padding:6px;text-align:right;">Unreal $</th>
                        <th style="padding:6px;text-align:right;">Unreal %</th>
                        <th style="padding:6px;text-align:right;">Realized $</th>
                    </tr>
                </thead>
                <tbody>{''.join(rows)}</tbody>
            </table>
            """

            return conn_label + quick_form + table + """
            <script>
            function placeOrder(sym, side, qty) {
                const type = prompt('Order type: market or limit?', 'market').trim().toLowerCase();
                if (!['market','limit'].includes(type)) return alert('Invalid type');
                const limit = type === 'limit' ? parseFloat(prompt('Limit price:')) : null;
                if (type === 'limit' && (isNaN(limit) || limit <= 0)) return alert('Valid limit price required');
                const profit = side === 'buy' ? parseFloat(prompt('Profit target % (optional):') || 0) : 0;
                if (side === 'buy' && profit && isNaN(profit)) return alert('Invalid profit %');

                fetch('/alpaca/' + side, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({symbol: sym, qty: qty, order_type: type, limit_price: limit || null, profit_target: profit || null})
                })
                .then(r => r.json())
                .then(d => {
                    alert(d.message || (d.success ? 'Order placed!' : 'Error'));
                    openAlpacaModal();
                })
                .catch(() => alert('Order failed'));
            }
            function quickBuy() {
                const s = document.getElementById('quickSymbol').value.trim().toUpperCase();
                const q = parseInt(document.getElementById('quickQty').value);
                const t = document.getElementById('quickType').value;
                const l = t === 'limit' ? parseFloat(document.getElementById('quickLimit').value) : null;
                const p = parseFloat(document.getElementById('quickProfit').value) || null;
                if (!s || !q) return alert('Symbol & Qty required');
                fetch('/alpaca/buy', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({symbol: s, qty: q, order_type: t, limit_price: l, profit_target: p})
                })
                .then(r => r.json())
                .then(d => { alert(d.message); openAlpacaModal(); })
                .catch(() => alert('Buy failed'));
            }
            function quickSell() {
                const s = document.getElementById('quickSymbol').value.trim().toUpperCase();
                const q = parseInt(document.getElementById('quickQty').value);
                const t = document.getElementById('quickType').value;
                const l = t === 'limit' ? parseFloat(document.getElementById('quickLimit').value) : null;
                if (!s || !q) return alert('Symbol & Qty required');
                fetch('/alpaca/sell', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({symbol: s, qty: q, order_type: t, limit_price: l})
                })
                .then(r => r.json())
                .then(d => { alert(d.message); openAlpacaModal(); })
                .catch(() => alert('Sell failed'));
            }
            </script>
            """

        except Exception as e:
            return conn_label + f"<p style='color:#ef4444'>Error loading positions: {e}</p>"

    def cancel_all_orders(self):
        try:
            self.trading_client.cancel_all_orders()
            return "All open orders cancelled."
        except Exception as e:
            return f"Cancel error: {e}"


# Global instance
_trader = None
def get_trader() -> AlpacaTrader:
    global _trader
    if _trader is None:
        _trader = AlpacaTrader()
    return _trader


# Routes
@alpaca_app.route('/positions')
def positions_modal():
    return get_trader().get_positions_html()

@alpaca_app.route('/orders')
def orders_modal():
    status = request.args.get('status', 'open')
    trader = get_trader()
    try:
        req = GetOrdersRequest(status=status) if status != "all" else GetOrdersRequest()
        orders = trader.trading_client.get_orders(req)
        if not orders:
            return "<p>No orders.</p>"
        rows = [f"""
        <tr>
            <td>{o.id[:8]}...</td>
            <td>{o.symbol}</td>
            <td>{o.side.value}</td>
            <td>{o.qty}</td>
            <td>{o.type.value}</td>
            <td>{o.status.value}</td>
            <td>{o.submitted_at.strftime('%H:%M') if o.submitted_at else '-'}</td>
        </tr>
        """ for o in orders]
        return f"""
        <table style="width:100%;border-collapse:collapse;font-size:0.8rem;">
            <thead><tr style="background:#1e293b;color:#e2e8f0;">
                <th>ID</th><th>Sym</th><th>Side</th><th>Qty</th><th>Type</th><th>Status</th><th>Time</th>
            </tr></thead>
            <tbody>{''.join(rows)}</tbody>
        </table>
        """
    except Exception as e:
        return f"<p style='color:#ef4444'>Orders error: {e}</p>"

@alpaca_app.route('/buy', methods=['POST'])
def buy_endpoint():
    data = request.get_json() or {}
    return jsonify(get_trader().buy_stock(
        symbol=data.get('symbol', '').upper(),
        qty=int(data.get('qty', 0)),
        order_type=data.get('order_type', 'market'),
        limit_price=data.get('limit_price'),
        profit_target=data.get('profit_target')
    ))

@alpaca_app.route('/sell', methods=['POST'])
def sell_endpoint():
    data = request.get_json() or {}
    return jsonify(get_trader().sell_stock(
        symbol=data.get('symbol', '').upper(),
        qty=int(data.get('qty', 0)),
        order_type=data.get('order_type', 'market'),
        limit_price=data.get('limit_price')
    ))

@alpaca_app.route('/cancel_all', methods=['POST'])
def cancel_all():
    msg = get_trader().cancel_all_orders()
    return jsonify({"msg": msg})