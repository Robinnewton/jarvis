import yfinance as yf
import talib
import numpy as np
import pandas as pd
import time
import os
import gc
from datetime import datetime, timedelta

CACHE_DIR = "cache"
CACHE_MINUTES = 14

def ensure_cache_dir():
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)

def get_cache_path(symbol, timeframe):
    safe_symbol = symbol.replace("=", "_").replace("/", "_")
    return os.path.join(CACHE_DIR, f"{safe_symbol}_{timeframe}.csv")

def is_cache_valid(path):
    if not os.path.exists(path):
        return False
    mtime = datetime.fromtimestamp(os.path.getmtime(path))
    return datetime.now() - mtime < timedelta(minutes=CACHE_MINUTES)

def fetch_data(symbol, period, interval):
    ensure_cache_dir()
    cache_path = get_cache_path(symbol, interval)
    if is_cache_valid(cache_path):
        try:
            df = pd.read_csv(cache_path, index_col=0, parse_dates=True)
            if len(df) > 10:
                return df
        except:
            pass
    time.sleep(0.3)
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period, interval=interval)
        if df is not None and len(df) > 10:
            df.to_csv(cache_path)
            return df
    except Exception as e:
        print(f"    Fetch error {symbol} {interval}: {e}")
    return None

def find_swing_points(df, lookback=5):
    highs = df['High'].values
    lows = df['Low'].values
    swing_highs = []
    swing_lows = []
    for i in range(lookback, len(highs) - lookback):
        if highs[i] == max(highs[i-lookback:i+lookback+1]):
            swing_highs.append((i, highs[i]))
        if lows[i] == min(lows[i-lookback:i+lookback+1]):
            swing_lows.append((i, lows[i]))
    return swing_highs, swing_lows

def calculate_fibonacci(swing_high, swing_low, direction):
    diff = swing_high - swing_low
    if direction == 'bullish':
        fib_618 = swing_high - (diff * 0.618)
        fib_786 = swing_high - (diff * 0.786)
    else:
        fib_618 = swing_low + (diff * 0.618)
        fib_786 = swing_low + (diff * 0.786)
    return {'fib_618': fib_618, 'fib_786': fib_786}

def detect_zones(df):
    if df is None or len(df) < 20:
        return []
    zones = []
    opens = df['Open'].values
    highs = df['High'].values
    lows = df['Low'].values
    closes = df['Close'].values
    for i in range(2, len(df) - 1):
        body_base = abs(closes[i-1] - opens[i-1])
        body_curr = abs(closes[i] - opens[i])
        avg_body = np.mean(np.abs(closes[:i] - opens[:i]))
        if avg_body == 0:
            continue
        is_down = closes[i-2] < opens[i-2]
        is_base = body_base < avg_body * 0.75
        is_up = closes[i] > opens[i] and body_curr > avg_body * 1.2
        if is_down and is_base and is_up:
            zones.append({
                'type': 'demand',
                'high': max(highs[i-1], highs[i-2]),
                'low': min(lows[i-1], lows[i-2]),
                'strength': 'strong',
                'index': i
            })
        is_up_prev = closes[i-2] > opens[i-2]
        is_down_curr = closes[i] < opens[i] and body_curr > avg_body * 1.2
        if is_up_prev and is_base and is_down_curr:
            zones.append({
                'type': 'supply',
                'high': max(highs[i-1], highs[i-2]),
                'low': min(lows[i-1], lows[i-2]),
                'strength': 'strong',
                'index': i
            })
    return zones[-10:] if len(zones) > 10 else zones

def price_in_zone(price, zone, buffer_pct=0.002):
    zone_range = zone['high'] - zone['low']
    buffer = zone_range * buffer_pct * 10
    return (zone['low'] - buffer) <= price <= (zone['high'] + buffer)

def price_near_fib(price, fib_level, tolerance_pct=0.004):
    tolerance = abs(fib_level) * tolerance_pct
    return abs(price - fib_level) <= tolerance

def analyze_timeframe(df, current_price):
    if df is None or len(df) < 20:
        return None
    result = {
        'zones': [],
        'fibs': None,
        'trend': 'neutral',
        'price_in_zone': False,
        'price_at_fib': False,
        'zone_type': None,
        'score': 0
    }
    zones = detect_zones(df)
    result['zones'] = zones
    swing_highs, swing_lows = find_swing_points(df)
    if swing_highs and swing_lows:
        recent_high = swing_highs[-1][1]
        recent_low = swing_lows[-1][1]
        close = df['Close'].values[-1]
        mid = (recent_high + recent_low) / 2
        direction = 'bullish' if close > mid else 'bearish'
        result['fibs'] = calculate_fibonacci(recent_high, recent_low, direction)
        result['trend'] = direction
    close = df['Close'].values.astype(float)
    ema_8 = talib.EMA(close, timeperiod=8)[-1]
    ema_21 = talib.EMA(close, timeperiod=21)[-1]
    if len(close) >= 55:
        ema_55 = talib.EMA(close, timeperiod=55)[-1]
        if ema_8 > ema_21 > ema_55:
            result['trend'] = 'bullish'
        elif ema_8 < ema_21 < ema_55:
            result['trend'] = 'bearish'
    else:
        if ema_8 > ema_21:
            result['trend'] = 'bullish'
        elif ema_8 < ema_21:
            result['trend'] = 'bearish'
    for zone in zones:
        if price_in_zone(current_price, zone):
            result['price_in_zone'] = True
            result['zone_type'] = zone['type']
            result['active_zone'] = zone
            break
    if result['fibs']:
        if price_near_fib(current_price, result['fibs']['fib_618']):
            result['price_at_fib'] = True
            result['fib_level'] = '61.8%'
        elif price_near_fib(current_price, result['fibs']['fib_786']):
            result['price_at_fib'] = True
            result['fib_level'] = '78.6%'
    return result

def calculate_confluence_score(d1, h4, h1):
    score = 0
    reasons = []
    if d1 and d1.get('price_in_zone'):
        score += 25
        reasons.append(f"D1 {d1['zone_type']} zone")
    if h4 and h4.get('price_in_zone'):
        score += 20
        reasons.append(f"H4 {h4['zone_type']} zone")
        if d1 and d1.get('zone_type') == h4.get('zone_type'):
            score += 10
            reasons.append("D1-H4 alignment")
    if h1 and h1.get('price_in_zone'):
        score += 15
        reasons.append(f"H1 {h1['zone_type']} zone")
        if h4 and h4.get('zone_type') == h1.get('zone_type'):
            score += 5
            reasons.append("H4-H1 alignment")
    for tf, name in [(d1, 'D1'), (h4, 'H4'), (h1, 'H1')]:
        if tf and tf.get('price_at_fib'):
            score += 15
            reasons.append(f"{name} at {tf.get('fib_level', 'fib')}")
    trends = [tf['trend'] for tf in [d1, h4, h1] if tf and tf.get('trend') != 'neutral']
    if len(trends) >= 2 and len(set(trends)) == 1:
        score += 10
        reasons.append(f"Trend: {trends[0]}")
    return min(score, 100), reasons

def determine_action(score, d1, h4, h1, config):
    if score < 70:
        return 'WAIT', None
    zone_types = [tf['zone_type'] for tf in [d1, h4, h1] if tf and tf.get('zone_type')]
    if not zone_types:
        return 'WAIT', None
    from collections import Counter
    zone_type = Counter(zone_types).most_common(1)[0][0]
    trend_filter = config.get('filters', {}).get('trend_filter', 'both')
    trends = [tf['trend'] for tf in [d1, h4, h1] if tf and tf.get('trend') != 'neutral']
    dominant_trend = Counter(trends).most_common(1)[0][0] if trends else 'neutral'
    if trend_filter == 'with_trend':
        if zone_type == 'demand' and dominant_trend != 'bullish':
            return 'WAIT', None
        if zone_type == 'supply' and dominant_trend != 'bearish':
            return 'WAIT', None
    if zone_type == 'demand':
        return 'BUY', 'demand'
    elif zone_type == 'supply':
        return 'SELL', 'supply'
    return 'WAIT', None

def calculate_levels(action, current_price, atr):
    if atr is None or atr == 0:
        atr = current_price * 0.005
    if action == 'BUY':
        entry = current_price
        stop_loss = current_price - (atr * 1.5)
        take_profit = current_price + (atr * 4.5)
        return entry, stop_loss, take_profit
    elif action == 'SELL':
        entry = current_price
        stop_loss = current_price + (atr * 1.5)
        take_profit = current_price - (atr * 4.5)
        return entry, stop_loss, take_profit
    return None, None, None

def analyze_pair(symbol, config):
    result = {
        'symbol': symbol,
        'timestamp': datetime.now().isoformat(),
        'action': 'WAIT',
        'score': 0,
        'zone_type': None,
        'reasons': [],
        'entry': None,
        'stop_loss': None,
        'take_profit': None,
        'timeframes': {}
    }
    print(f"    Fetching D1...")
    df_d1 = fetch_data(symbol, '60d', '1d')
    print(f"    Fetching H4...")
    df_h4_raw = fetch_data(symbol, '30d', '1h')
    df_h4 = df_h4_raw.iloc[::4].copy() if df_h4_raw is not None and len(df_h4_raw) > 0 else None
    print(f"    Fetching H1...")
    df_h1 = fetch_data(symbol, '7d', '1h')
    if df_h1 is None or len(df_h1) < 10:
        print(f"    Insufficient data for {symbol}")
        return result
    current_price = float(df_h1['Close'].values[-1])
    result['current_price'] = current_price
    print(f"    Detecting zones...")
    d1_analysis = analyze_timeframe(df_d1, current_price)
    h4_analysis = analyze_timeframe(df_h4, current_price)
    h1_analysis = analyze_timeframe(df_h1, current_price)
    result['timeframes'] = {'D1': d1_analysis, 'H4': h4_analysis, 'H1': h1_analysis}
    print(f"    Calculating confluence...")
    score, reasons = calculate_confluence_score(d1_analysis, h4_analysis, h1_analysis)
    result['score'] = score
    result['reasons'] = reasons
    action, zone_type = determine_action(score, d1_analysis, h4_analysis, h1_analysis, config)
    result['action'] = action
    result['zone_type'] = zone_type
    if action != 'WAIT':
        atr = None
        if df_h4 is not None and len(df_h4) > 14:
            atr = talib.ATR(
                df_h4['High'].values.astype(float),
                df_h4['Low'].values.astype(float),
                df_h4['Close'].values.astype(float),
                timeperiod=14
            )[-1]
        entry, sl, tp = calculate_levels(action, current_price, atr)
        result['entry'] = entry
        result['stop_loss'] = sl
        result['take_profit'] = tp
    try:
        del df_d1, df_h4, df_h1, df_h4_raw
    except:
        pass
    gc.collect()
    return result
