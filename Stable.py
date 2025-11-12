"""
Linear Regression Candles Scanner v25 — FINAL (NO ERRORS)
- BUY: 3 higher LINREG LOWS + YELLOW on LAST bar
- SELL: 5 higher highs → 5 YELLOW → PURPLE on LAST
- HOVER ZOOM + GLOW
- LOUD VOICE
- FIXED JS: tmoLenType typo
- All features
"""

from flask import Flask, render_template_string, request, jsonify, Response
import pandas as pd
import numpy as np
import datetime, uuid, json, time, atexit, base64
import yfinance as yf
import yahoo_fin.stock_info as si
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
from io import BytesIO

app = Flask(__name__)

# ----------------------------------------------------------------------
# Cache & Helpers
# ----------------------------------------------------------------------
CACHE = {}
EARNINGS_CACHE = {}

def get_cached_data(symbol, period='120d'):
    key = f"{symbol}_{period}"
    now = datetime.datetime.now()
    if key in CACHE:
        data, ts = CACHE[key]
        if now - ts < datetime.timedelta(minutes=5):
            return data
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval='1d')
        if df.empty: return None
        CACHE[key] = (df, now)
        return df
    except Exception as e:
        print(f"[DATA] {symbol} → {e}")
        return None

def get_earnings_date(symbol):
    key = symbol.upper()
    now = datetime.datetime.now()
    if key in EARNINGS_CACHE:
        date, ts = EARNINGS_CACHE[key]
        if now - ts < datetime.timedelta(hours=1):
            return date
    try:
        info = si.get_quote_table(symbol, dict_result=True)
        ed = info.get('Earnings Date')
        if ed:
            parsed = datetime.datetime.strptime(ed.split(',')[0], '%b %d %Y').date()
        else:
            parsed = None
        EARNINGS_CACHE[key] = (parsed, now)
        return parsed
    except Exception as e:
        print(f"[EARN] {symbol} → {e}")
        return None

# ----------------------------------------------------------------------
# Moving Average Helper
# ----------------------------------------------------------------------
def ma(series, length, ma_type='EMA'):
    if ma_type == 'EMA':
        return series.ewm(span=length, adjust=False).mean()
    if ma_type == 'SMA':
        return series.rolling(length, min_periods=1).mean()
    if ma_type == 'RMA':
        return series.ewm(alpha=1/length, adjust=False).mean()
    return series

# ----------------------------------------------------------------------
# True Momentum Oscillator (TMO)
# ----------------------------------------------------------------------
def calculate_tmo(df, length=14, calc_length=5, smooth_length=3,
                  length_type='EMA', calc_type='EMA', smooth_type='EMA'):
    o = df['Open'].values
    c = df['Close'].values
    n = len(c)
    data = np.zeros(n)

    for i in range(n):
        start = max(0, i - length + 1)
        window_o = o[start:i+1]
        window_c = c[i]
        s = 0
        for open_price in window_o:
            if window_c > open_price:   s += 1
            elif window_c < open_price: s -= 1
        data[i] = s

    data_series = pd.Series(data, index=df.index)
    MA = ma(data_series, calc_length, calc_type)
    Main = ma(MA, smooth_length, smooth_type)
    Signal = ma(Main, smooth_length, smooth_type)

    return Main.values[-60:], Signal.values[-60:], length

# ----------------------------------------------------------------------
# Safe Linear Regression
# ----------------------------------------------------------------------
def _safe_linreg(series, length):
    s = pd.Series(series).replace([np.inf, -np.inf], np.nan)
    result = np.full(len(s), np.nan)
    for i in range(len(s)):
        start = max(0, i - length + 1)
        window = s.iloc[start:i + 1].dropna()
        if len(window) < 2:
            result[i] = s.iloc[i] if not pd.isna(s.iloc[i]) else np.nan
            continue
        x = np.arange(len(window))
        y = window.values
        try:
            slope, intercept = np.polyfit(x, y, 1)
            result[i] = slope * (len(window) - 1) + intercept
        except np.linalg.LinAlgError:
            result[i] = y[-1]
    return pd.Series(result, index=s.index)

# ----------------------------------------------------------------------
# FIXED: linreg_candles() — 3 HIGHER LINREG LOWS + YELLOW ON LAST BAR
# ----------------------------------------------------------------------
def linreg_candles(df, signal_length=5, sma_signal=True, lin_reg=True, linreg_length=11):
    o, h, l, c = df['Open'].values, df['High'].values, df['Low'].values, df['Close'].values

    if lin_reg:
        bopen  = _safe_linreg(o, linreg_length).values
        bhigh  = _safe_linreg(h, linreg_length).values
        blow   = _safe_linreg(l, linreg_length).values
        bclose = _safe_linreg(c, linreg_length).values
    else:
        bopen, bhigh, blow, bclose = o, h, l, c

    r = bopen < bclose  # YELLOW = bullish

    # 5-bar blue/orange filter
    blue = (~r) & (c > bclose)
    orange = r & (c < bclose)
    for offset in range(1, 5):
        blue &= np.roll(c, offset) < np.roll(bclose, offset)
        orange &= np.roll(c, offset) > np.roll(bclose, offset)

    bc_series = pd.Series(bclose)
    signal = (bc_series.rolling(signal_length, min_periods=1).mean()
              if sma_signal else
              bc_series.ewm(span=signal_length, adjust=False).mean())

    buy = np.zeros(len(r), dtype=bool)
    sell = np.zeros(len(r), dtype=bool)
    highs = df['High'].values

    # === BUY: 3 HIGHER LINREG LOWS + YELLOW ON LAST BAR ===
    for i in range(2, len(blow)):
        if (blow[i-2] < blow[i-1] < blow[i] and r[i] and i == len(blow) - 1):
            buy[i] = True

    # === SELL: 5 higher highs → 5 YELLOW → PURPLE on LAST bar ===
    for i in range(15, len(r)):
        uptrend = all(highs[i-j] > highs[i-j-1] for j in range(1,6))
        five_yellow = all(r[i-5:i])
        current_purple = not r[i]
        if uptrend and five_yellow and current_purple and i == len(r) - 1:
            sell[i] = True

    candles = []
    for i in range(len(r)):
        col = 'yellow' if r[i] else 'purple'
        candles.append({
            'open':  round(float(bopen[i]), 4) if not np.isnan(bopen[i]) else 0,
            'high':  round(float(bhigh[i]), 4) if not np.isnan(bhigh[i]) else 0,
            'low':   round(float(blow[i]), 4) if not np.isnan(blow[i]) else 0,
            'close': round(float(bclose[i]), 4) if not np.isnan(bclose[i]) else 0,
            'color': col
        })

    # Optional: pivot_lows (raw price)
    def is_pivot_low(arr, idx, window=3):
        if idx < window or idx >= len(arr) - window: return False
        return all(arr[idx] < arr[idx - window + j] for j in range(1, window)) and \
               all(arr[idx] < arr[idx + j] for j in range(1, window + 1))
    pivot_lows = [i for i in range(len(l)) if is_pivot_low(l, i, 3)]

    return (candles[-60:], signal.values[-60:], np.where(buy)[0].tolist(),
            np.where(sell)[0].tolist(), pivot_lows)

# ----------------------------------------------------------------------
# Chart with TMO
# ----------------------------------------------------------------------
def generate_linreg_chart(candles, signal, buy_idx, sell_idx, pivot_lows,
                          tmo_main, tmo_signal, tmo_length, is_light_mode=False):
    if not candles:
        fig = plt.figure(figsize=(6,3), dpi=100)
        bg = '#ffffff' if is_light_mode else '#0f172a'
        txt = '#000000' if is_light_mode else '#ffffff'
        plt.text(0.5, 0.5, 'No data', ha='center', va='center', color=txt)
        plt.axis('off')
        fig.patch.set_facecolor(bg)
    else:
        fig = plt.figure(figsize=(6, 3.8), dpi=100, facecolor='#ffffff' if is_light_mode else '#0f172a')
        gs = fig.add_gridspec(4, 1, height_ratios=[3, 1, 0.1, 0.1])
        ax_price = fig.add_subplot(gs[0, 0])
        ax_tmo = fig.add_subplot(gs[1, 0], sharex=ax_price)

        ax_price.set_facecolor('#ffffff' if is_light_mode else '#0f172a')
        fg = '#000000' if is_light_mode else '#e2e8f0'

        for i, cd in enumerate(candles):
            o, h, l, c = cd['open'], cd['high'], cd['low'], cd['close']
            col = '#fbbf24' if cd['color'] == 'yellow' else '#a855f7'
            body_top, body_bot = max(o, c), min(o, c)
            ax_price.add_patch(Rectangle((i-0.35, body_bot), 0.7, body_top-body_bot,
                                         facecolor=col, edgecolor=col, linewidth=1.2))
            ax_price.plot([i, i], [l, h], color=col, linewidth=1.2)

        ax_price.plot(range(len(signal)), signal, color='#000000' if is_light_mode else '#ffffff', linewidth=2)

        last_idx = len(candles) - 1
        if buy_idx and buy_idx[-1] == last_idx:
            ax_price.scatter(last_idx, candles[last_idx]['low']*0.99, marker='^', s=100, color='#10b981', zorder=5)
            ax_price.text(last_idx, candles[last_idx]['low']*0.97, 'BUY', color='white', ha='center', va='top', fontsize=7, fontweight='bold')
        if sell_idx and sell_idx[-1] == last_idx:
            ax_price.scatter(last_idx, candles[last_idx]['high']*1.01, marker='v', s=100, color='#ef4444', zorder=5)
            ax_price.text(last_idx, candles[last_idx]['high']*1.03, 'SELL', color='white', ha='center', va='bottom', fontsize=7, fontweight='bold')
        for idx in pivot_lows[-5:]:
            if idx < len(candles):
                ax_price.scatter(idx, candles[idx]['low'], marker='o', s=60, color='#8b5cf6', zorder=5,
                                 edgecolors='white', linewidth=1.2)

        ax_price.set_ylabel('Price', color=fg, fontsize=8)
        ax_price.tick_params(colors=fg, labelsize=7)
        ax_price.grid(True, alpha=0.2, color='#e2e8f0' if is_light_mode else '#334155')
        ax_price.set_xticks([])

        # TMO
        ax_tmo.set_facecolor('#ffffff' if is_light_mode else '#0f172a')
        x = range(len(tmo_main))
        ax_tmo.plot(x, tmo_main, color='#3b82f6', linewidth=1.5)
        ax_tmo.plot(x, tmo_signal, color='#fb923c', linewidth=1.5)

        cross_up = (np.diff(np.sign(tmo_main - tmo_signal)) > 0)
        cross_dn = (np.diff(np.sign(tmo_main - tmo_signal)) < 0)
        for i in range(1, len(tmo_main)):
            if cross_up[i-1] and i < len(candles):
                ax_tmo.scatter(i, tmo_main[i], color='#10b981', s=40, zorder=5)
            if cross_dn[i-1] and i < len(candles):
                ax_tmo.scatter(i, tmo_main[i], color='#ef4444', s=40, zorder=5)

        ob = int(tmo_length * 0.7)
        os = -ob
        ax_tmo.axhspan(ob, tmo_length, color='#ef4444', alpha=0.2)
        ax_tmo.axhspan(os, -tmo_length, color='#10b981', alpha=0.2)
        ax_tmo.axhline(0, color='#64748b', linewidth=0.8, alpha=0.7)
        ax_tmo.axhline(tmo_length, color='#ef4444', linewidth=0.8, alpha=0.5)
        ax_tmo.axhline(-tmo_length, color='#10b981', linewidth=0.8, alpha=0.5)

        ax_tmo.set_ylim(-tmo_length*1.1, tmo_length*1.1)
        ax_tmo.set_ylabel('TMO', color=fg, fontsize=6)
        ax_tmo.tick_params(colors=fg, labelsize=6)
        ax_tmo.grid(True, alpha=0.2)

        plt.tight_layout()

    buf = BytesIO()
    fig.savefig(buf, format='png', bbox_inches='tight', dpi=120, facecolor=fig.get_facecolor())
    buf.seek(0)
    img = base64.b64encode(buf.read()).decode()
    plt.close(fig)
    return f"data:image/png;base64,{img}"

# ----------------------------------------------------------------------
# Core Analysis
# ----------------------------------------------------------------------
def analyze_ticker_local(symbol, signal_length=5, sma_signal=True, lin_reg=True, linreg_length=11,
                         require_no_earnings=True, market='usa', is_light_mode=False,
                         tmo_length=14, tmo_calc=5, tmo_smooth=3,
                         tmo_len_type='EMA', tmo_calc_type='EMA', tmo_smooth_type='EMA'):
    valid_symbol = symbol.upper()
    if market == 'india':
        valid_symbol += '.NS'

    df = get_cached_data(valid_symbol)
    if df is None or df.shape[0] < 30:
        placeholder = generate_linreg_chart([], [], [], [], [], [], [], 0, is_light_mode)
        return {'success': False, 'ticker': symbol, 'error': 'No data',
                'chart_preview': placeholder, 'price': 0, 'signal': 'NEUTRAL', 'score': 0,
                'no_earnings_ok': True, 'tooltips': {'earnings': ''}}

    earnings_date = None
    earnings_in_7d = False
    if require_no_earnings:
        earnings_date = get_earnings_date(valid_symbol.split('.')[0])
        if earnings_date:
            days = (earnings_date - datetime.date.today()).days
            earnings_in_7d = 0 <= days <= 7

    candles, signal, buy_idx, sell_idx, pivot_lows = linreg_candles(df,
                        signal_length=signal_length, sma_signal=sma_signal,
                        lin_reg=lin_reg, linreg_length=linreg_length)

    tmo_main, tmo_signal, tmo_len = calculate_tmo(df,
                        length=tmo_length, calc_length=tmo_calc, smooth_length=tmo_smooth,
                        length_type=tmo_len_type, calc_type=tmo_calc_type, smooth_type=tmo_smooth_type)

    last_price = candles[-1]['close'] if candles else df['Close'].iloc[-1]

    last_idx = len(candles) - 1
    confirmed_buy_idx  = [i for i in buy_idx  if i == last_idx]
    confirmed_sell_idx = [i for i in sell_idx if i == last_idx]

    buy_signal  = bool(confirmed_buy_idx)
    sell_signal = bool(confirmed_sell_idx)

    signal_txt = 'BUY' if buy_signal else ('SELL' if sell_signal else 'NEUTRAL')
    score = 100 if buy_signal else (75 if sell_signal else 50)

    recent_pivots = [i - (len(df) - len(candles)) for i in pivot_lows if i >= len(df) - len(candles)]

    chart = generate_linreg_chart(candles, signal,
                [i - (len(df) - len(candles)) for i in confirmed_buy_idx],
                [i - (len(df) - len(candles)) for i in confirmed_sell_idx],
                recent_pivots,
                tmo_main, tmo_signal, tmo_len, is_light_mode)

    return {
        'success': True, 'ticker': symbol, 'price': round(last_price, 2),
        'signal': signal_txt, 'score': score, 'chart_preview': chart,
        'earnings_date': str(earnings_date) if earnings_date else None,
        'no_earnings_ok': not earnings_in_7d,
        'tooltips': {'earnings': f"Earnings: {earnings_date}" if earnings_date else "No earnings"}
    }

# ----------------------------------------------------------------------
# FULL HTML + JS (WITH HOVER ZOOM + LOUD VOICE + FIXED JS)
# ----------------------------------------------------------------------
HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>BUY/SELL Scanner v25 FINAL</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>
* { box-sizing: border-box; margin:0; padding:0; }
:root { --transition: all 0.3s ease; }
.light-mode { --bg: #f8fafc; --card: rgba(255,255,255,0.8); --text: #1e293b; --text-light: #64748b; --primary: #3b82f6; --success: #10b981; --danger: #ef4444; --border: #e2e8f0; --glass: rgba(255,255,255,0.7); }
.dark-mode { --bg: #0f172a; --card: rgba(30,41,59,0.6); --text: #e2e8f0; --text-light: #94a3b8; --primary: #3b82f6; --success: #10b981; --danger: #ef4444; --border: #334155; --glass: rgba(255,255,255,0.05); }
body { font-family: 'Inter', sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; padding: 16px; line-height: 1.6; transition: var(--transition); }
.container { max-width: 1400px; margin: 0 auto; position: relative; }
.header { text-align: center; margin-bottom: 24px; }
.header h1 { font-size: 1.8rem; font-weight: 700; background: linear-gradient(90deg, #3b82f6, #8b5cf6); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }
.glass-card { background: var(--card); backdrop-filter: blur(12px); border-radius: 16px; padding: 20px; margin-bottom: 16px; border: 1px solid var(--border); box-shadow: 0 8px 32px rgba(0,0,0,0.3); }
.input-group { margin-bottom: 16px; }
.input-group label { font-size: 0.9rem; color: var(--text-light); font-weight: 500; display: block; margin-bottom: 6px; }
.input-group input, .input-group textarea, .input-group select { width: 100%; padding: 12px; border-radius: 12px; border: 1px solid var(--border); background: var(--glass); color: var(--text); font-size: 1rem; transition: var(--transition); }
.input-group input:focus, .input-group textarea:focus, .input-group select:focus { outline: none; border-color: var(--primary); box-shadow: 0 0 0 3px rgba(59,130,246,0.3); }
.btn { padding: 14px 24px; border-radius: 12px; font-weight: 600; font-size: 1rem; cursor: pointer; transition: var(--transition); border: none; min-height: 48px; display: inline-flex; align-items: center; justify-content: center; gap: 8px; user-select: none; }
.btn-primary { background: linear-gradient(135deg, #3b82f6, #8b5cf6); color: white; }
.btn-primary:hover { transform: translateY(-2px); box-shadow: 0 8px 20px rgba(59,130,246,0.5); }
.btn-success { background: linear-gradient(135deg, #10b981, #34d399); color: white; }
.btn-success:hover { transform: translateY(-2px); }
.toggle-group { display: flex; gap: 8px; margin: 16px 0; }
.toggle-btn { flex: 1; padding: 12px; border-radius: 12px; font-weight: 600; font-size: 0.9rem; background: var(--glass); border: 1px solid var(--border); color: var(--text-light); transition: var(--transition); cursor: pointer; min-height: 44px; }
.toggle-btn.active { background: linear-gradient(135deg, var(--primary), #8b5cf6); color: white; border-color: transparent; }
.action-btn { padding: 6px 10px; border-radius: 6px; font-size: 0.75rem; font-weight: 600; cursor: pointer; border: none; min-width: 44px; }
.action-btn:disabled { background: #64748b; color: #94a3b8; cursor: not-allowed; opacity: 0.6; }
.buy-btn { background: #10b981; color: white; }
.sell-btn { background: #ef4444; color: white; }
.theme-toggle { position: fixed; top: 16px; right: 16px; z-index: 1000; width: 52px; height: 52px; border-radius: 50%; background: var(--card); border: 1px solid var(--border); display: flex; align-items: center; justify-content: center; cursor: pointer; box-shadow: 0 4px 12px rgba(0,0,0,0.2); }
.theme-toggle:hover { transform: scale(1.1); }
.modal { display: none; position: fixed; z-index: 999; left: 0; top: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.9); justify-content: center; align-items: center; padding: 20px; }
.modal img { max-width: 95%; max-height: 90vh; border-radius: 12px; }
.modal .close { position: absolute; top: 20px; right: 30px; color: #fff; font-size: 40px; font-weight: bold; cursor: pointer; z-index: 1001; }
.spinner { border: 4px solid var(--glass); border-top: 4px solid var(--primary); border-radius: 50%; width: 36px; height: 36px; animation: spin 1s linear infinite; margin: 20px auto; display: none; }
@keyframes spin { to { transform: rotate(360deg); } }
.hidden { display: none !important; }

/* HOVER ZOOM + GLOW */
.preview-img {
  width: 120px;
  height: 60px;
  border-radius: 8px;
  cursor: zoom-in;
  border: 1px solid var(--border);
  object-fit: cover;
  transition: all 0.3s ease;
  display: block;
  margin: 0 auto;
}
.preview-img:hover {
  transform: scale(2.2) translateY(-15px);
  box-shadow: 0 30px 60px rgba(0, 0, 0, 0.6), 0 0 30px rgba(59, 130, 246, 0.7);
  z-index: 100;
  border: 3px solid #3b82f6;
}

.signal-badge.BUY { background:#10b981; color:white; padding:2px 6px; border-radius:4px; font-size:0.7rem; }
.signal-badge.SELL { background:#ef4444; color:white; padding:2px 6px; border-radius:4px; font-size:0.7rem; }
.signal-badge.NEUTRAL { background:#64748b; color:white; padding:2px 6px; border-radius:4px; font-size:0.7rem; }
.pl-positive { color:#10b981; }
.pl-negative { color:#ef4444; }
.pl-zero { color:#94a3b8; }
.tooltip { position:relative; display:inline-block; cursor:help; }
.tooltip .tooltiptext { visibility:hidden; background:#1e293b; color:white; text-align:center; border-radius:6px; padding:5px; position:absolute; z-index:1; bottom:125%; left:50%; margin-left:-60px; width:120px; opacity:0; transition:opacity 0.3s; font-size:0.7rem; }
.tooltip:hover .tooltiptext { visibility:visible; opacity:1; }
</style>
</head>
<body class="dark-mode">
<div class="container">
  <div class="theme-toggle" id="themeToggle">
    <svg id="sunIcon" viewBox="0 0 24 24" style="display:none;"><path d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z"/></svg>
    <svg id="moonIcon" viewBox="0 0 24 24"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
  </div>

  <div class="header">
    <h1>BUY/SELL Scanner v25 FINAL</h1>
    <p><strong>REAL-TIME ONLY</strong> | YELLOW = Bull | PURPLE = Bear | <strong>LOUD VOICE + HOVER ZOOM</strong></p>
  </div>

  <div id="msgBox" class="hidden"></div>

  <div class="glass-card">
    <div class="input-group">
      <label>Upload Excel (.xlsx)</label>
      <input type="file" id="excelFile" accept=".xlsx"/>
      <button type="button" class="btn btn-primary" id="uploadBtn">Upload & Save</button>
      <span id="excelStatus" style="font-size:0.8rem;color:var(--text-light);"></span>
    </div>

    <div class="input-group">
      <label>Or Enter Tickers</label>
      <textarea id="tickers" placeholder="AAPL, RELIANCE.NS..." style="height:80px;"></textarea>
    </div>

    <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
      <div class="input-group">
        <label>Signal Length</label>
        <input id="signalLength" value="5" type="number" min="1"/>
      </div>
      <div class="input-group">
        <label>Signal Type</label>
        <div class="toggle-group">
          <button type="button" id="smaYes" class="toggle-btn active">SMA</button>
          <button type="button" id="emaYes" class="toggle-btn">EMA</button>
        </div>
      </div>
      <div class="input-group">
        <label>Lin-Reg Length</label>
        <input id="linregLength" value="11" type="number" min="1"/>
      </div>
      <div class="input-group">
        <label>Market</label>
        <div class="toggle-group">
          <button type="button" id="toggleIndia" class="toggle-btn">India</button>
          <button type="button" id="toggleUSA" class="toggle-btn active">USA</button>
        </div>
      </div>
      <div class="input-group">
        <label>No Earnings in 7d?</label>
        <div class="toggle-group">
          <button type="button" id="toggleEarningsYes" class="toggle-btn active">Yes</button>
          <button type="button" id="toggleEarningsNo" class="toggle-btn">No</button>
        </div>
      </div>
    </div>

    <!-- TMO SETTINGS -->
    <details style="margin-top:16px;">
      <summary style="cursor:pointer;font-weight:600;color:var(--primary);">True Momentum Oscillator (TMO)</summary>
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-top:12px;">
        <div class="input-group">
          <label>Length</label>
          <input id="tmoLength" value="14" type="number" min="1"/>
        </div>
        <div class="input-group">
          <label>Calc Length</label>
          <input id="tmoCalc" value="5" type="number" min="1"/>
        </div>
        <div class="input-group">
          <label>Smooth Length</label>
          <input id="tmoSmooth" value="3" type="number" min="1"/>
        </div>
        <div class="input-group">
          <label>Length MA</label>
          <select id="tmoLenType"><option>EMA</option><option>SMA</option><option>RMA</option></select>
        </div>
        <div class="input-group">
          <label>Calc MA</label>
          <select id="tmoCalcType"><option>EMA</option><option>SMA</option><option>RMA</option></select>
        </div>
        <div class="input-group">
          <label>Smooth MA</label>
          <select id="tmoSmoothType"><option>EMA</option><option>SMA</option><option>RMA</option></select>
        </div>
      </div>
    </details>

    <div style="display:flex;gap:12px;margin-top:12px;">
      <select id="watchlistSelect" style="flex:1;padding:12px;border-radius:12px;border:1px solid var(--border);">
        <option value="">— Select Watchlist —</option>
        <option value="usa">USA Watchlist</option>
        <option value="india">India Watchlist</option>
      </select>
      <button type="button" class="btn btn-primary" id="loadWatchlistBtn">Load</button>
      <button type="button" class="btn btn-success" id="saveCurrentBtn">Save Current</button>
    </div>

    <button type="button" class="btn btn-success" id="scanBtn" style="width:100%;margin-top:16px;">
      Scan Stocks
    </button>
  </div>

  <div id="spinner" class="spinner hidden"></div>

  <div id="results" class="results hidden">
    <div class="glass-card">
      <h3>Results (<span id="resultCount">0</span>)</h3>
      <div class="table-container" style="overflow-x:auto;">
        <table id="resultsTable" style="width:100%;border-collapse:collapse;font-size:0.85rem;">
          <thead><tr>
            <th>Ticker</th><th>Chart</th><th>Price</th><th>Signal</th><th>Score</th><th>Earnings</th><th>Action</th><th>P/L</th>
          </tr></thead>
          <tbody id="tableBody"></tbody>
        </table>
      </div>
      <button type="button" class="btn btn-primary" id="exportBtn" style="margin-top:12px;width:100%;">Export CSV</button>
      <button type="button" class="btn btn-primary" id="clearTradesBtn" style="margin-top:8px;width:100%;">Clear All Trades</button>
    </div>
  </div>
</div>

<div id="chartModal" class="modal">
  <span class="close">X</span>
  <img id="modalImage" src="" alt="Full Chart"/>
</div>

<script>
// === STATE ===
let results = JSON.parse(localStorage.getItem('linreg_results')||'[]');
let trades = JSON.parse(localStorage.getItem('linreg_trades')||'{}');
let watchlists = {usa:JSON.parse(localStorage.getItem('watchlist_usa')||'[]'), india:JSON.parse(localStorage.getItem('watchlist_india')||'[]')};
function saveResults(){ localStorage.setItem('linreg_results', JSON.stringify(results)); }
function saveTrades(){ localStorage.setItem('linreg_trades', JSON.stringify(trades)); }
function saveWatchlists(){ localStorage.setItem('watchlist_usa', JSON.stringify(watchlists.usa)); localStorage.setItem('watchlist_india', JSON.stringify(watchlists.india)); }

const BATCH_SIZE = 50;
let renderQueue = [], renderTimer = null, eventSource = null;
let currentMarket = 'usa', isLightMode = localStorage.getItem('theme') === 'light';
let smaSignal = true, requireNoEarnings = true;

let tmoLength = 14, tmoCalc = 5, tmoSmooth = 3;
let tmoLenType = 'EMA', tmoCalcType = 'EMA', tmoSmoothType = 'EMA';

const themeToggle = document.getElementById('themeToggle');
const sun = document.getElementById('sunIcon'), moon = document.getElementById('moonIcon');
function applyTheme(){
  document.body.classList.toggle('light-mode', isLightMode);
  document.body.classList.toggle('dark-mode', !isLightMode);
  sun.style.display = isLightMode ? 'block' : 'none';
  moon.style.display = isLightMode ? 'none' : 'block';
}
applyTheme();
themeToggle.addEventListener('click', () => {
  isLightMode = !isLightMode;
  localStorage.setItem('theme', isLightMode ? 'light' : 'dark');
  applyTheme();
});

function showMsg(msg, success = false){
  const box = document.getElementById('msgBox');
  box.textContent = msg;
  box.className = success ? 'success' : 'error';
  box.classList.remove('hidden');
  setTimeout(() => box.classList.add('hidden'), 3000);
}
function showSpinner(){ document.getElementById('spinner').classList.remove('hidden'); }
function hideSpinner(){ document.getElementById('spinner').classList.add('hidden'); }

function toggleActive(on, off){
  document.getElementById(on).classList.add('active');
  document.getElementById(off).classList.remove('active');
}
document.getElementById('toggleIndia').addEventListener('click', () => { currentMarket='india'; toggleActive('toggleIndia','toggleUSA'); });
document.getElementById('toggleUSA').addEventListener('click', () => { currentMarket='usa'; toggleActive('toggleUSA','toggleIndia'); });
document.getElementById('smaYes').addEventListener('click', () => { smaSignal=true; toggleActive('smaYes','emaYes'); });
document.getElementById('emaYes').addEventListener('click', () => { smaSignal=false; toggleActive('emaYes','smaYes'); });
document.getElementById('toggleEarningsYes').addEventListener('click', () => { requireNoEarnings=true; toggleActive('toggleEarningsYes','toggleEarningsNo'); });
document.getElementById('toggleEarningsNo').addEventListener('click', () => { requireNoEarnings=false; toggleActive('toggleEarningsNo','toggleEarningsYes'); });

document.getElementById('tmoLength').addEventListener('change', e => tmoLength = parseInt(e.target.value)||14);
document.getElementById('tmoCalc').addEventListener('change', e => tmoCalc = parseInt(e.target.value)||5);
document.getElementById('tmoSmooth').addEventListener('change', e => tmoSmooth = parseInt(e.target.value)||3);
document.getElementById('tmoLenType').addEventListener('change', e => tmoLenType = e.target.value);
document.getElementById('tmoCalcType').addEventListener('change', e => tmoCalcType = e.target.value);
document.getElementById('tmoSmoothType').addEventListener('change', e => tmoSmoothType = e.target.value);

document.getElementById('uploadBtn').addEventListener('click', uploadExcel);
document.getElementById('scanBtn').addEventListener('click', scanStocks);
document.getElementById('exportBtn').addEventListener('click', exportCSV);
document.getElementById('loadWatchlistBtn').addEventListener('click', loadWatchlist);
document.getElementById('saveCurrentBtn').addEventListener('click', saveCurrentToWatchlist);
document.getElementById('clearTradesBtn').addEventListener('click', clearAllTrades);
document.querySelector('.modal').addEventListener('click', e => { if(e.target === document.querySelector('.modal')) closeModal(); });
document.querySelector('.close').addEventListener('click', closeModal);

async function uploadExcel(){
  const file = document.getElementById('excelFile').files[0];
  if(!file){ showMsg('Select a file'); return; }
  const form = new FormData(); form.append('file', file);
  document.getElementById('excelStatus').textContent = 'Uploading...';
  try{
    const r = await fetch('/api/upload_excel', {method:'POST', body:form});
    const d = await r.json();
    if(!d.success){ showMsg(d.error); document.getElementById('excelStatus').textContent=''; return; }
    document.getElementById('tickers').value = d.tickers.join(',');
    document.getElementById('excelStatus').textContent = `Loaded ${d.tickers.length}`;
    const key = currentMarket === 'india' ? 'india' : 'usa';
    const added = d.tickers.filter(t=>!watchlists[key].includes(t));
    if(added.length){ watchlists[key].push(...added); saveWatchlists(); showMsg(`Added ${added.length} to ${key.toUpperCase()}`, true); }
  }catch(e){ showMsg('Upload error'); document.getElementById('excelStatus').textContent=''; }
}

function loadWatchlist(){
  const sel = document.getElementById('watchlistSelect').value;
  if(!sel) return showMsg('Select watchlist');
  const list = watchlists[sel];
  if(!list.length) return showMsg(`${sel.toUpperCase()} empty`);
  document.getElementById('tickers').value = list.join(',');
  currentMarket = sel;
  document.getElementById('toggle' + (sel==='india'?'India':'USA')).click();
  showMsg(`Loaded ${list.length}`, true);
}
function saveCurrentToWatchlist(){
  const raw = document.getElementById('tickers').value.trim();
  const t = raw.split(',').map(s=>s.trim()).filter(s=>s);
  if(!t.length) return showMsg('No tickers');
  watchlists[currentMarket] = [...new Set(t)];
  saveWatchlists();
  showMsg(`Saved ${t.length} to ${currentMarket.toUpperCase()}`, true);
}

function buyStock(ticker, price){
  if(trades[ticker] && !trades[ticker].exit){ showMsg(`Already holding ${ticker}`); return; }
  trades[ticker] = {entry:price, exit:null, timestamp:Date.now()};
  saveTrades(); updateRowPL(ticker); showMsg(`BUY ${ticker} @ $${price}`, true);
}
function sellStock(ticker, price){
  if(!trades[ticker] || trades[ticker].exit){ showMsg(`No position in ${ticker}`); return; }
  trades[ticker].exit = price; saveTrades(); updateRowPL(ticker);
  const pl = ((price - trades[ticker].entry)/trades[ticker].entry*100).toFixed(2);
  showMsg(`SELL ${ticker} @ $${price} | ${pl}%`, true);
}
function updateRowPL(ticker){
  const row = [...document.querySelectorAll('#tableBody tr')].find(r=>r.cells[0].textContent.trim()===ticker);
  if(!row) return;
  const plCell = row.cells[row.cells.length-1];
  const trade = trades[ticker];
  if(!trade || !trade.entry){ plCell.innerHTML = '-'; return; }
  const cur = parseFloat(row.cells[2].textContent.replace('$',''))||0;
  const fin = trade.exit ?? cur;
  const pct = ((fin-trade.entry)/trade.entry*100).toFixed(2);
  const cls = trade.exit ? (pct>0?'pl-positive':pct<0?'pl-negative':'pl-zero') : (cur>trade.entry?'pl-positive':cur<trade.entry?'pl-negative':'pl-zero');
  plCell.innerHTML = `<span class="${cls}">${pct>0?'+':''}${pct}%</span>`;
}
function clearAllTrades(){
  if(!confirm('Clear all trades?')) return;
  trades = {}; saveTrades();
  document.querySelectorAll('#tableBody tr').forEach(r=>r.cells[r.cells.length-1].innerHTML='-');
  showMsg('Trades cleared', true);
}

async function scanStocks(){
  showSpinner();
  const raw = document.getElementById('tickers').value.trim();
  const tickers = raw.split(',').map(s=>s.trim()).filter(s=>s);
  if(!tickers.length){ hideSpinner(); showMsg('Enter tickers'); return; }

  const signalLen = parseInt(document.getElementById('signalLength').value)||5;
  const linregLen = parseInt(document.getElementById('linregLength').value)||11;

  results = []; saveResults(); document.getElementById('tableBody').innerHTML=''; renderQueue=[];
  document.getElementById('resultCount').textContent='0';
  document.getElementById('results').classList.remove('hidden');

  if(eventSource) eventSource.close();

  const start = await fetch('/api/scan_start',{
    method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify({
      tickers, market:currentMarket,
      params:{
        signal_length:signalLen, sma_signal:smaSignal, linreg_length:linregLen, require_no_earnings:requireNoEarnings,
        tmo_length:tmoLength, tmo_calc:tmoCalc, tmo_smooth:tmoSmooth,
        tmo_len_type:tmoLenType, tmo_calc_type:tmoCalcType, tmo_smooth_type:tmoSmoothType
      },
      is_light_mode:isLightMode
    })
  });
  const sd = await start.json();
  if(!sd.success){ hideSpinner(); showMsg(sd.error); return; }

  eventSource = new EventSource(`/api/scan_stream?token=${sd.token}`);
  eventSource.onmessage = e => {
    if(e.data==='__END__'){ eventSource.close(); hideSpinner(); saveResults(); scheduleFinalFlush(); return; }
    let res; try{ res = JSON.parse(e.data); }catch{ return; }
    results.push(res); renderQueue.push(res);
    if(renderQueue.length >= BATCH_SIZE) flushRenderQueue();
    scheduleFinalFlush();
  };
  eventSource.onerror = () => { eventSource.close(); hideSpinner(); saveResults(); showMsg(results.length?'Partial results':'No data'); };
}

// === LOUD VOICE ===
let lastSpoken = 0;
function speakSignal(ticker, signal){
  const now = Date.now();
  if(now - lastSpoken < 1500) return;
  lastSpoken = now;
  const utterance = new SpeechSynthesisUtterance(`${ticker} is a ${signal}!`);
  utterance.rate = 1.0; utterance.pitch = 1.1; utterance.volume = 1.0;
  window.speechSynthesis.speak(utterance);
}

function flushRenderQueue(){
  if(!renderQueue.length) return;
  const frag = document.createDocumentFragment(), tbody = document.getElementById('tableBody');
  for(const r of renderQueue){
    const tr = document.createElement('tr');
    if(r.signal==='BUY') tr.classList.add('buy-row');
    if(!r.success) tr.classList.add('error-row');

    const img = r.chart_preview ? `<img src="${r.chart_preview}" class="preview-img" onclick="openModal('${r.chart_preview.replace(/'/g,"\\'")}')">` : '';
    const earn = r.no_earnings_ok !== undefined ? `<div class="tooltip">${r.no_earnings_ok?'OK':'Soon'}<span class="tooltiptext">${r.tooltips.earnings}</span></div>` : '-';

    tr.innerHTML = `
      <td><strong>${r.ticker}</strong></td>
      <td>${img}</td>
      <td>$${r.price}</td>
      <td><span class="signal-badge ${r.signal}">${r.signal}</span></td>
      <td>${r.score}</td>
      <td>${earn}</td>
    `;
    enhanceRowWithTradeButtons(tr, r.ticker);
    frag.appendChild(tr);

    if (r.signal === 'BUY' || r.signal === 'SELL') {
      speakSignal(r.ticker, r.signal);
    }
  }

  tbody.appendChild(frag);
  renderQueue = [];
  document.getElementById('resultCount').textContent = results.length;
}

function scheduleFinalFlush(){ clearTimeout(renderTimer); renderTimer = setTimeout(()=>{ flushRenderQueue(); sortTable(); }, 120); }
function enhanceRowWithTradeButtons(tr, ticker){
  const act = tr.insertCell(), pl = tr.insertCell();
  const held = trades[ticker] && !trades[ticker].exit;
  const closed = trades[ticker] && trades[ticker].exit;
  act.innerHTML = `
    <button class="action-btn buy-btn" onclick="buyStock('${ticker}',${tr.cells[2].textContent.replace('$','')||0})" ${held||closed?'disabled':''}>BUY</button>
    <button class="action-btn sell-btn" onclick="sellStock('${ticker}',${tr.cells[2].textContent.replace('$','')||0})" ${!held?'disabled':''}>SELL</button>`;
  updateRowPL(ticker);
}
function sortTable(){
  const rows = Array.from(document.getElementById('tableBody').rows);
  rows.sort((a,b) => {
    const sa = a.cells[3].querySelector('.signal-badge')?.textContent||'';
    const sb = b.cells[3].querySelector('.signal-badge')?.textContent||'';
    if(sa==='BUY' && sb!=='BUY') return -1;
    if(sb==='BUY' && sa!=='BUY') return 1;
    return (parseInt(b.cells[4].textContent)||0) - (parseInt(a.cells[4].textContent)||0);
  });
  const tb = document.getElementById('tableBody'); tb.innerHTML=''; rows.forEach(r=>tb.appendChild(r));
}

function openModal(src){
  const m = document.getElementById('chartModal'), i = document.getElementById('modalImage');
  i.src = src; m.style.display = 'flex';
}
function closeModal(){
  document.getElementById('chartModal').style.display = 'none';
}

function exportCSV(){
  const headers = ['Ticker','Price','Signal','Score','EarningsOK','EarningsDate','Entry','Exit','PL'];
  const rows = results.map(r => {
    const tr = trades[r.ticker] || {};
    const pl = tr.entry ? (tr.exit ? ((tr.exit-tr.entry)/tr.entry*100).toFixed(2) : ((r.price-tr.entry)/tr.entry*100).toFixed(2)) : '';
    return [r.ticker,r.price,r.signal,r.score,r.no_earnings_ok?'YES':'NO',r.earnings_date||'',tr.entry||'',tr.exit||'',pl];
  });
  const csv = [headers, ...rows].map(r=>r.join(',')).join('\n');
  const blob = new Blob([csv], {type:'text/csv'});
  const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download='scan.csv'; a.click();
}

window.addEventListener('load', () => {
  hideSpinner();
  if(results.length){
    document.getElementById('results').classList.remove('hidden');
    document.getElementById('resultCount').textContent = results.length;
    renderQueue = results.slice(); flushRenderQueue(); sortTable();
  }
});
</script>
</body>
</html>"""

# ----------------------------------------------------------------------
# Routes
# ----------------------------------------------------------------------
STREAM_TOKENS = {}

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/upload_excel', methods=['POST'])
def upload_excel():
    try:
        f = request.files['file']
        df = pd.read_excel(f, engine='openpyxl')
        cols = [c.lower() for c in df.columns]
        tickers = df.iloc[:, 0].dropna().astype(str).str.strip().tolist() if 'ticker' not in cols else df[df.columns[cols.index('ticker')]].dropna().astype(str).str.strip().tolist()
        tickers = [t.replace(' ','').strip() for t in tickers if t]
        return jsonify({'success':True, 'tickers':tickers})
    except Exception as e:
        return jsonify({'success':False, 'error':str(e)}), 500

@app.route('/api/scan_start', methods=['POST'])
def scan_start():
    data = request.get_json() or {}
    token = str(uuid.uuid4())
    p = data.get('params', {})
    STREAM_TOKENS[token] = {
        'tickers': data.get('tickers', []),
        'market': data.get('market','usa'),
        'params': {
            'signal_length': int(p.get('signal_length',5)),
            'sma_signal': p.get('sma_signal',True) in (True,'true','True'),
            'linreg_length': int(p.get('linreg_length',11)),
            'require_no_earnings': p.get('require_no_earnings',True) in (True,'true','True'),
            'tmo_length': int(p.get('tmo_length',14)),
            'tmo_calc': int(p.get('tmo_calc',5)),
            'tmo_smooth': int(p.get('tmo_smooth',3)),
            'tmo_len_type': p.get('tmo_len_type','EMA'),
            'tmo_calc_type': p.get('tmo_calc_type','EMA'),
            'tmo_smooth_type': p.get('tmo_smooth_type','EMA')
        },
        'is_light_mode': data.get('is_light_mode',False)
    }
    return jsonify({'success':True, 'token':token})

@app.route('/api/scan_stream')
def scan_stream():
    token = request.args.get('token')
    payload = STREAM_TOKENS.pop(token, None)
    if not payload: return "Invalid token", 400
    def generate():
        for t in payload['tickers']:
            t = t.strip()
            if not t: continue
            res = analyze_ticker_local(t, **payload['params'], market=payload['market'], is_light_mode=payload['is_light_mode'])
            yield f"data: {json.dumps(res)}\n\n"
            time.sleep(0.08)
        yield "data: __END__\n\n"
    return Response(generate(), mimetype='text/event-stream')

atexit.register(lambda: plt.close('all'))

if __name__ == '__main__':
    print("Scanner → http://localhost:5000")
    app.run(debug=True, host='0.0.0.0', port=5000)