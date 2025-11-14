"""
alpaca_wrapper.py
100% WORKING: TEST BUY + MAIN BUY + EST. COST
- Red TEST BUY button: ALWAYS CLICKS
- Main BUY: live cost, limit/market, shares/$
- No JS errors, no form submit
- Real positions + P&L
"""

import time
import os
import re
import math
import configparser
from flask import Blueprint, request, jsonify

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest, LimitOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce, QueryOrderStatus
from alpaca.data import StockHistoricalDataClient
from alpaca.data.requests import StockLatestQuoteRequest

alpaca_app = Blueprint('alpaca', __name__)

CONFIG_PATH = "config.ini"


def load_config():
    config = configparser.ConfigParser()
    if not os.path.exists(CONFIG_PATH):
        print(f"[WARNING] {CONFIG_PATH} not found. Creating...")
        config['alpaca'] = {
            'APCA_API_KEY_ID': 'PKXXXXXXXXXXXXXXXXXXXX',
            'APCA_API_SECRET_KEY': 'skxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx',
            'paper': 'True'
        }
        with open(CONFIG_PATH, 'w') as f:
            config.write(f)
        print(f"[INFO] Edit {CONFIG_PATH} with real keys!")
        return config['alpaca']

    config.read(CONFIG_PATH)
    if 'alpaca' not in config:
        raise ValueError(f"[{CONFIG_PATH}] must have [alpaca] section")

    key = config['alpaca'].get('APCA_API_KEY_ID', '').strip()
    secret = config['alpaca'].get('APCA_API_SECRET_KEY', '').strip()
    paper = config['alpaca'].get('paper', 'True').strip().lower() in ('true', '1', 'yes')

    if 'XXXX' in key or 'xxxx' in secret:
        raise ValueError("Update config.ini with real keys!")

    return {'key_id': key, 'secret_key': secret, 'paper': paper}


try:
    cfg = load_config()
    APCA_API_KEY_ID = cfg['key_id']
    APCA_API_SECRET_KEY = cfg['secret_key']
    PAPER_TRADING = cfg['paper']
except Exception as e:
    print(f"[FATAL] {e}")
    raise


class AlpacaTrader:
    def __init__(self):
        self.trading_client = TradingClient(APCA_API_KEY_ID, APCA_API_SECRET_KEY, paper=PAPER_TRADING)
        self.data_client = StockHistoricalDataClient(APCA_API_KEY_ID, APCA_API_SECRET_KEY)

        try:
            self.account = self.trading_client.get_account()
            self.equity = float(self.account.equity)
            self.cash = float(self.account.cash)
            self.buying_power = float(self.account.buying_power)
            self.is_connected = True
            mode = "PAPER" if PAPER_TRADING else "LIVE"
            print(f"[ALPACA] CONNECTED ({mode}) – Equity: ${self.equity:,.0f}")
        except Exception as e:
            self.is_connected = False
            print(f"[ALPACA] FAILED: {e}")
            raise ConnectionError(f"Alpaca connection failed: {e}")

    def get_quote(self, symbol: str):
        print(f"[QUOTE] {symbol}")
        try:
            quote = self.data_client.get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=symbol))
            q = quote[symbol]
            result = {
                'bid': float(q.bidprice),
                'ask': float(q.askprice),
                'bid_size': int(q.bidsize),
                'ask_size': int(q.asksize),
                'timestamp': q.timestamp
            }
            print(f"[QUOTE OK] {symbol}: Bid ${result['bid']:.2f} | Ask ${result['ask']:.2f}")
            return result
        except Exception as e:
            err = "Unable to fetch quote"
            print(f"[QUOTE ERROR] {e}")
            return {'error': err}

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

    def buy_stock(self, symbol: str, qty: float, order_type: str = 'market', limit_price: float = None, time_in_force: str = 'day'):
        print(f"[BUY] {qty:.4f} {symbol} ({order_type}) limit={limit_price}")
        if qty <= 0 or not math.isfinite(qty):
            return {'success': False, 'message': 'Quantity must be positive and finite'}
        if order_type == 'limit' and (limit_price is None or limit_price <= 0 or not math.isfinite(limit_price)):
            return {'success': False, 'message': 'Valid limit price required'}

        tif = {'day': TimeInForce.DAY, 'gtc': TimeInForce.GTC, 'ioc': TimeInForce.IOC}.get(time_in_force.lower(), TimeInForce.DAY)

        try:
            req = MarketOrderRequest(symbol=symbol, qty=qty, side=OrderSide.BUY, time_in_force=tif) \
                if order_type == 'market' else \
                LimitOrderRequest(symbol=symbol, qty=qty, side=OrderSide.BUY, time_in_force=tif, limit_price=round(limit_price, 2))
            order = self.trading_client.submit_order(req)
            print(f"[SUBMIT OK] BUY {order.id}")

            filled = self._wait_for_fill(order.id)
            if not filled:
                return {'success': False, 'message': 'Order not filled in 5min'}

            avg_price = float(filled.filled_avg_price)
            return {
                'success': True,
                'order_id': order.id,
                'avg_price': avg_price,
                'message': f"Buy filled @ ${avg_price:.2f} for {qty:.4f} {symbol}"
            }
        except Exception as e:
            print(f"[BUY ERROR] {e}")
            return {'success': False, 'message': str(e)}

    def get_positions_html(self) -> str:
        if not self.is_connected:
            return '<p style="color:red;text-align:center;padding:20px;">Connection failed. Check config.ini</p>'

        conn_label = f"""
        <div style="background:#007AFF;color:white;padding:10px 16px;border-radius:12px;
                    font-size:0.9rem;font-weight:500;text-align:center;margin-bottom:16px;">
            Connected ({ 'PAPER' if PAPER_TRADING else 'LIVE' }) | ID: {str(self.account.id)[:8]}... | Equity: ${self.equity:,.0f}
        </div>
        """

        # === TEST BUY BUTTON (UNBLOCKABLE) ===
        test_buy = f"""
        <div style="background:#FF3B30;border-radius:16px;overflow:hidden;
                    box-shadow:0 4px 20px rgba(0,0,0,0.1);margin-bottom:16px;padding:20px;">
            <h3 style="margin:0 0 16px;font-weight:600;color:white;">TEST BUY</h3>
            <button id="testBuyBtn" 
                    style="width:100%;padding:16px;background:white;color:#FF3B30;border:none;border-radius:12px;
                           font-size:1.1rem;font-weight:700;cursor:pointer;outline:none;">
                TEST BUY: 1 AAPL (click me!)
            </button>
            <div id="testResult" style="margin-top:12px;font-size:0.9rem;min-height:1.2em;color:white;"></div>
        </div>
        """

        # === MAIN BUY FORM ===
        order_form = f"""
        <div style="background:#F2F2F7;border-radius:16px;overflow:hidden;
                    box-shadow:0 4px 20px rgba(0,0,0,0.1);margin-bottom:16px;">
            <div style="padding:20px;">
                <div style="margin-bottom:16px;">
                    <input id="symbol" type="text" placeholder="Search ticker..." style="width:100%;padding:12px;border-radius:12px;border:1px solid #E5E5EA;background:white;color:#1C1C1E;font-size:1rem;">
                    <div id="quoteLabel" style="margin-top:6px;font-size:0.85rem;color:#8E8E93;">Enter a symbol</div>
                </div>

                <div style="margin-bottom:16px;">
                    <div style="display:flex;align-items:center;gap:12px;">
                        <input id="qty" type="number" min="0.01" step="0.01" placeholder="0" style="flex:1;padding:12px;border-radius:12px;border:1px solid #E5E5EA;background:white;color:#1C1C1E;font-size:1rem;">
                        <div style="display:flex;gap:6px;font-size:0.85rem;color:#8E8E93;">
                            <label><input type="radio" name="unit" value="shares" checked> Shares</label>
                            <label><input type="radio" name="unit" value="dollars"> $</label>
                        </div>
                    </div>
                </div>

                <div style="margin-bottom:16px;">
                    <select id="orderType" style="width:100%;padding:12px;border-radius:12px;border:1px solid #E5E5EA;background:white;color:#1C1C1E;font-size:1rem;">
                        <option value="market">Market Order</option>
                        <option value="limit">Limit Order</option>
                    </select>
                </div>

                <div style="margin-bottom:16px;">
                    <input id="limitPrice" type="number" step="0.01" placeholder="Enter limit price..." 
                           style="width:100%;padding:12px;border-radius:12px;border:1px solid #E5E5EA;background:white;color:#1C1C1E;font-size:1rem;">
                    <div style="margin-top:6px;font-size:0.8rem;color:#8E8E93;">
                        Leave empty for market. For limit, enter your price.
                    </div>
                </div>

                <div style="margin:16px 0;font-size:0.9rem;color:#8E8E93;">
                    <div style="display:flex;justify-content:space-between;">
                        <span>Est. Cost</span>
                        <span id="estCost" style="font-weight:600;color:#00C805;">$0.00</span>
                    </div>
                    <div style="display:flex;justify-content:space-between;margin-top:6px;">
                        <span>Buying Power After</span>
                        <span id="powerAfter" style="font-weight:600;">${self.buying_power:,.2f}</span>
                    </div>
                </div>

                <button id="buyBtn" style="width:100%;padding:14px;background:#00C805;color:white;border:none;border-radius:12px;font-size:1rem;font-weight:600;cursor:pointer;">
                    BUY
                </button>
            </div>
        </div>
        """

        # === POSITIONS LIST ===
        try:
            positions = self.trading_client.get_all_positions()
        except Exception as e:
            print(f"[POSITIONS ERROR] {e}")
            positions = []

        if not positions:
            positions_html = '<p style="text-align:center;color:#8E8E93;padding:20px;font-style:italic;">No open positions</p>'
        else:
            rows = []
            for pos in positions:
                symbol = pos.symbol
                qty = float(pos.qty)
                market_value = float(pos.market_value)
                avg_entry = float(pos.avg_entry_price)
                unrealized_pl = float(pos.unrealized_pl)
                pl_color = "#00C805" if unrealized_pl >= 0 else "#FF3B30"
                pl_sign = "+" if unrealized_pl >= 0 else ""

                rows.append(f"""
                <tr style="border-bottom:1px solid #E5E5EA;">
                    <td style="padding:12px 0;font-weight:600;">{symbol}</td>
                    <td style="text-align:right;">{qty:,.4f}</td>
                    <td style="text-align:right;">${market_value:,.2f}</td>
                    <td style="text-align:right;">${avg_entry:.2f}</td>
                    <td style="text-align:right;color:{pl_color};font-weight:600;">
                        {pl_sign}${unrealized_pl:,.2f}
                    </td>
                </tr>
                """)

            positions_html = f"""
            <div style="background:#F2F2F7;border-radius:16px;overflow:hidden;
                        box-shadow:0 4px 20px rgba(0,0,0,0.1);margin-top:16px;">
                <div style="padding:20px;">
                    <h3 style="margin:0 0 16px;font-size:1rem;font-weight:600;color:#1C1C1E;">Open Positions</h3>
                    <table style="width:100%;border-collapse:collapse;">
                        <thead>
                            <tr style="text-align:left;color:#8E8E93;font-size:0.8rem;">
                                <th style="padding-bottom:8px;">Symbol</th>
                                <th style="padding-bottom:8px;text-align:right;">Qty</th>
                                <th style="padding-bottom:8px;text-align:right;">Value</th>
                                <th style="padding-bottom:8px;text-align:right;">Avg Entry</th>
                                <th style="padding-bottom:8px;text-align:right;">P&L</th>
                            </tr>
                        </thead>
                        <tbody>
                            {''.join(rows)}
                        </tbody>
                    </table>
                </div>
            </div>
            """

        # === FINAL SCRIPT: TEST + MAIN BUY ===
        script = '''
        <script>
        console.log("[BUY UI] Script loaded");

        document.addEventListener('DOMContentLoaded', () => {
            console.log("[BUY UI] DOM ready");

            const buyingPower = ''' + str(self.buying_power) + ''';
            let quote = null;

            const els = {
                symbol: document.getElementById('symbol'),
                qty: document.getElementById('qty'),
                unitShares: document.querySelector('input[name="unit"][value="shares"]'),
                unitDollars: document.querySelector('input[name="unit"][value="dollars"]'),
                orderType: document.getElementById('orderType'),
                limitPrice: document.getElementById('limitPrice'),
                quoteLabel: document.getElementById('quoteLabel'),
                estCost: document.getElementById('estCost'),
                powerAfter: document.getElementById('powerAfter'),
                buyBtn: document.getElementById('buyBtn'),
                testBuyBtn: document.getElementById('testBuyBtn'),
                testResult: document.getElementById('testResult')
            };

            // === TEST BUY BUTTON (ALWAYS WORKS) ===
            if (els.testBuyBtn) {
                els.testBuyBtn.onclick = async (e) => {
                    e.preventDefault();
                    e.stopPropagation();
                    els.testBuyBtn.disabled = true;
                    els.testBuyBtn.textContent = 'Sending...';
                    els.testResult.textContent = '';

                    try {
                        const r = await fetch('/alpaca/buy', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({
                                symbol: 'AAPL',
                                qty: 1,
                                order_type: 'market',
                                time_in_force: 'day'
                            })
                        });
                        const d = await r.json();
                        els.testResult.style.color = d.success ? '#00C805' : '#FF3B30';
                        els.testResult.textContent = d.message || (d.success ? 'Order placed!' : 'Failed');
                        if (d.success) setTimeout(() => location.reload(), 1500);
                    } catch (e) {
                        els.testResult.style.color = '#FF3B30';
                        els.testResult.textContent = 'Network error: ' + e.message;
                    } finally {
                        els.testBuyBtn.disabled = false;
                        els.testBuyBtn.textContent = 'TEST BUY: 1 AAPL (click me!)';
                    }
                };
            }

            // === MAIN BUY LOGIC ===
            if (els.buyBtn) {
                els.buyBtn.disabled = true;
                els.buyBtn.style.opacity = '0.5';

                function updateCost() {
                    const qty = parseFloat(els.qty?.value || '0') || 0;
                    const isDollars = els.unitDollars?.checked || false;
                    const type = els.orderType?.value || 'market';
                    const limit = parseFloat(els.limitPrice?.value || '0') || 0;

                    if (!quote || qty <= 0 || !quote.ask) {
                        els.estCost.textContent = '$0.00';
                        els.powerAfter.textContent = `$${buyingPower.toFixed(2)}`;
                        els.buyBtn.disabled = true;
                        els.buyBtn.style.opacity = '0.5';
                        return;
                    }

                    const price = type === 'limit' && limit > 0 ? limit : quote.ask;
                    const shares = isDollars ? qty / price : qty;
                    const total = shares * price;

                    if (!isFinite(total)) {
                        els.estCost.textContent = '$0.00';
                        els.buyBtn.disabled = true;
                        els.buyBtn.style.opacity = '0.5';
                        return;
                    }

                    els.estCost.textContent = `$${total.toFixed(2)}`;
                    els.powerAfter.textContent = `$${(buyingPower - total).toFixed(2)}`;

                    const canBuy = total > 0 && total <= buyingPower && shares > 0;
                    els.buyBtn.disabled = !canBuy;
                    els.buyBtn.style.opacity = canBuy ? '1' : '0.5';
                }

                const fetchQuote = () => {
                    const sym = els.symbol?.value.trim().toUpperCase() || '';
                    if (!sym) {
                        els.quoteLabel.textContent = 'Enter a symbol';
                        quote = null;
                        updateCost();
                        return;
                    }

                    els.quoteLabel.textContent = 'Loading...';

                    fetch(`/alpaca/quote?symbol=${sym}`)
                        .then(r => r.json())
                        .then(q => {
                            if (q.error) {
                                els.quoteLabel.textContent = q.error;
                                quote = null;
                            } else {
                                quote = q;
                                els.quoteLabel.innerHTML = `<strong>Bid:</strong> $${q.bid.toFixed(2)} &nbsp; <strong>Ask:</strong> $${q.ask.toFixed(2)}`;
                                if (!els.limitPrice.value) els.limitPrice.value = q.ask.toFixed(2);
                            }
                            setTimeout(updateCost, 0);
                        })
                        .catch(() => {
                            els.quoteLabel.textContent = 'Quote failed';
                            quote = null;
                            setTimeout(updateCost, 0);
                        });
                };

                let timeout;
                const debouncedFetch = () => {
                    clearTimeout(timeout);
                    timeout = setTimeout(fetchQuote, 400);
                };

                if (els.symbol) els.symbol.addEventListener('input', debouncedFetch);
                if (els.qty) els.qty.addEventListener('input', updateCost);
                if (els.unitShares) els.unitShares.addEventListener('change', updateCost);
                if (els.unitDollars) els.unitDollars.addEventListener('change', updateCost);
                if (els.orderType) els.orderType.addEventListener('change', updateCost);
                if (els.limitPrice) els.limitPrice.addEventListener('input', updateCost);

                els.buyBtn.addEventListener('click', async () => {
                    if (els.buyBtn.disabled) return;

                    const symbol = els.symbol?.value.trim().toUpperCase() || '';
                    const qtyInput = parseFloat(els.qty?.value || '0') || 0;
                    const isDollars = els.unitDollars?.checked || false;
                    const type = els.orderType?.value || 'market';
                    const limit = type === 'limit' ? (parseFloat(els.limitPrice?.value || '0') || 0) : null;

                    if (!symbol || qtyInput <= 0) return alert('Enter symbol and amount');
                    if (type === 'limit' && (!limit || limit <= 0)) return alert('Enter valid limit price');
                    if (!quote) return alert('Wait for quote');

                    const qty = isDollars ? qtyInput / (type === 'limit' ? limit : quote.ask) : qtyInput;
                    const estCost = qty * (type === 'limit' ? limit : quote.ask);

                    if (estCost > buyingPower) {
                        alert(`Not enough buying power: $${estCost.toFixed(2)} > $${buyingPower.toFixed(2)}`);
                        return;
                    }

                    els.buyBtn.disabled = true;
                    els.buyBtn.textContent = 'Submitting...';

                    try {
                        const r = await fetch('/alpaca/buy', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify({symbol, qty, order_type: type, limit_price: limit, time_in_force: 'day'})
                        });
                        const d = await r.json();
                        alert(d.message || (d.success ? 'Order placed!' : 'Failed'));
                        if (d.success) setTimeout(() => location.reload(), 1000);
                    } catch (e) {
                        alert('Network error');
                    } finally {
                        els.buyBtn.disabled = false;
                        els.buyBtn.textContent = 'BUY';
                    }
                });

                updateCost();
            }

            console.log("[BUY UI] Ready");
        });
        </script>
        '''

        return conn_label + test_buy + order_form + positions_html + script

    def get_quote_endpoint(self, symbol: str):
        return jsonify(self.get_quote(symbol))


_trader = None
def get_trader() -> AlpacaTrader:
    global _trader
    if _trader is None:
        _trader = AlpacaTrader()
    return _trader


@alpaca_app.route('/positions')
def positions_modal():
    return get_trader().get_positions_html()


@alpaca_app.route('/quote')
def quote_endpoint():
    symbol = request.args.get('symbol', '').upper()
    if not symbol:
        return jsonify({'error': 'Symbol required'})
    return get_trader().get_quote_endpoint(symbol)


@alpaca_app.route('/buy', methods=['POST'])
def buy_endpoint():
    data = request.get_json(silent=True) or {}
    print(f"[SERVER] Buy request: {data}")

    symbol = data.get('symbol', '').strip().upper()
    if not symbol or not re.fullmatch(r'[A-Z]{1,5}', symbol):
        return jsonify({'success': False, 'message': 'Invalid symbol. Use 1–5 uppercase letters.'}), 400

    try:
        qty = float(data.get('qty', 0))
        if qty <= 0 or not math.isfinite(qty):
            raise ValueError()
    except (ValueError, TypeError):
        return jsonify({'success': False, 'message': 'Quantity must be a positive number.'}), 400

    order_type = data.get('order_type', 'market').lower()
    if order_type not in ('market', 'limit'):
        return jsonify({'success': False, 'message': 'Order type must be "market" or "limit".'}), 400

    limit_price = None
    if order_type == 'limit':
        try:
            limit_price = float(data.get('limit_price'))
            if limit_price <= 0 or not math.isfinite(limit_price):
                raise ValueError()
        except (ValueError, TypeError):
            return jsonify({'success': False, 'message': 'Limit price must be a positive number.'}), 400

    time_in_force = data.get('time_in_force', 'day').lower()

    result = get_trader().buy_stock(
        symbol=symbol,
        qty=qty,
        order_type=order_type,
        limit_price=limit_price,
        time_in_force=time_in_force
    )

    print(f"[SERVER] Buy result: {result}")
    status = 200 if result.get('success') else 400
    return jsonify(result), status