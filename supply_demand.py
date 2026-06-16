import talib
import numpy as np
import pandas as pd
import gc
from datetime import datetime
from fetch_data import fetch_all_timeframes

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

def detect_zones(df, avg_body_lookback=20):
    if df is None or len(df) < 20:
        return []
    zones = []
    opens  = df['Open'].values
    highs  = df['High'].values
    lows   = df['Low'].values
    closes = df['Close'].values
    def _is_bearish_candle(idx):
        return closes[idx] < opens[idx]

    def _is_bullish_candle(idx):
        return closes[idx] > opens[idx]

    def _is_small_body(idx, avg_body_val):
        return abs(closes[idx] - opens[idx]) < avg_body_val * 0.75

    def _is_large_body(idx, avg_body_val):
        return abs(closes[idx] - opens[idx]) > avg_body_val * 1.2

    for i in range(max(2, avg_body_lookback), len(df) - 1):
        # Calculate average body size over a fixed lookback window
        avg_body_current_window = np.mean(np.abs(closes[i - avg_body_lookback : i] - opens[i - avg_body_lookback : i]))

        if avg_body_current_window == 0:
            continue

        # Conditions for Demand Zone (Bearish -> Small Body Base -> Bullish)
        prev_prev_is_bearish = _is_bearish_candle(i-2)
        prev_is_small_body   = _is_small_body(i-1, avg_body_current_window)
        curr_is_bullish      = _is_bullish_candle(i) and _is_large_body(i, avg_body_current_window)

        if prev_prev_is_bearish and prev_is_small_body and curr_is_bullish:
            zones.append({
                'type': 'demand',
                'high': max(highs[i-1], highs[i-2]),
                'low': min(lows[i-1], lows[i-2]),
                'strength': 'strong',
                'index': i
            })

        # Conditions for Supply Zone (Bullish -> Small Body Base -> Bearish)
        prev_prev_is_bullish = _is_bullish_candle(i-2)
        curr_is_bearish      = _is_bearish_candle(i) and _is_large_body(i, avg_body_current_window)

        if prev_prev_is_bullish and prev_is_small_body and curr_is_bearish:
            zones.append({
                'type': 'supply',
                'high': max(highs[i-1], highs[i-2]),
                'low': min(lows[i-1], lows[i-2]),
                'strength': 'strong',
                'index': i
            })
    return zones[-10:] if len(zones) > 10 else zones

def detect_liquidity_sweep(df, zone):
    if df is None or len(df) < 5:
        return False, None
    highs  = df['High'].values
    lows   = df['Low'].values
    closes = df['Close'].values
    opens  = df['Open'].values
    for i in range(-5, -1):
        next_i = i + 1
        if zone['type'] == 'demand':
            # Sweep candle: wicks below zone and closes back inside
            sweep = lows[i] < zone['low'] and closes[i] > zone['low'] and closes[i] > opens[i]
            # Confirmation candle: next candle is bullish
            confirm = closes[next_i] > opens[next_i]
            if sweep and confirm:
                return True, {'type':'demand_sweep','swept_to':lows[i],'closed_at':closes[i],'confirmed_at':closes[next_i],'label':'Liquidity sweep below demand — confirmed'}
        elif zone['type'] == 'supply':
            # Sweep candle: wicks above zone and closes back inside
            sweep = highs[i] > zone['high'] and closes[i] < zone['high'] and closes[i] < opens[i]
            # Confirmation candle: next candle is bearish
            confirm = closes[next_i] < opens[next_i]
            if sweep and confirm:
                return True, {'type':'supply_sweep','swept_to':highs[i],'closed_at':closes[i],'confirmed_at':closes[next_i],'label':'Liquidity sweep above supply — confirmed'}
    return False, None

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
    result = {'zones':[],'fibs':None,'trend':'neutral','price_in_zone':False,'price_at_fib':False,'zone_type':None,'score':0,'sweep_detected':False,'sweep_info':None}
    zones = detect_zones(df)
    result['zones'] = zones
    swing_highs, swing_lows = find_swing_points(df)
    if swing_highs and swing_lows:
        recent_high = swing_highs[-1][1]
        recent_low  = swing_lows[-1][1]
        close       = df['Close'].values[-1]
        mid         = (recent_high + recent_low) / 2
        direction   = 'bullish' if close > mid else 'bearish'
        result['fibs']  = calculate_fibonacci(recent_high, recent_low, direction)
        result['trend'] = direction
    close  = df['Close'].values.astype(float)
    ema_8  = talib.EMA(close, timeperiod=8)[-1]
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
            result['zone_type']     = zone['type']
            result['active_zone']   = zone
            swept, sweep_info = detect_liquidity_sweep(df, zone)
            if swept:
                result['sweep_detected'] = True
                result['sweep_info']     = sweep_info
            break
    if result['fibs']:
        if price_near_fib(current_price, result['fibs']['fib_618']):
            result['price_at_fib'] = True
            result['fib_level']    = '61.8%'
        elif price_near_fib(current_price, result['fibs']['fib_786']):
            result['price_at_fib'] = True
            result['fib_level']    = '78.6%'
    return result

def calculate_confluence_score(d1, h4, h1):
    score   = 0
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
    for tf, name in [(d1,'D1'),(h4,'H4'),(h1,'H1')]:
        if tf and tf.get('price_at_fib'):
            score += 15
            reasons.append(f"{name} at {tf.get('fib_level','fib')}")
    trends = [tf['trend'] for tf in [d1,h4,h1] if tf and tf.get('trend') != 'neutral']
    if len(trends) >= 2 and len(set(trends)) == 1:
        score += 10
        reasons.append(f"Trend: {trends[0]}")
    for tf, name, bonus in [(h1,'H1',15),(h4,'H4',10),(d1,'D1',5)]:
        if tf and tf.get('sweep_detected'):
            score += bonus
            reasons.append(f"{name} liquidity sweep ✓")
    return min(score, 100), reasons

def determine_action(score, d1, h4, h1, config):
    if score < 70:
        return 'WAIT', None
    zone_types = [tf['zone_type'] for tf in [d1,h4,h1] if tf and tf.get('zone_type')]
    if not zone_types:
        return 'WAIT', None
    from collections import Counter
    zone_type = Counter(zone_types).most_common(1)[0][0]
    trend_filter = config.get('filters', {}).get('trend_filter', 'both')
    trends = [tf['trend'] for tf in [d1,h4,h1] if tf and tf.get('trend') != 'neutral']
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

def calculate_levels(action, current_price, atr, df_h4=None, df_d1=None):
    if atr is None or atr == 0:
        atr = current_price * 0.005
    sl = None
    tp = None
    if action == 'BUY':
        sl = current_price - (atr * 1.5)
        # Target nearest swing high above current price
        tp = None
        for df in [df_h4, df_d1]:
            if df is not None:
                swing_highs, _ = find_swing_points(df)
                # Find nearest swing high above current price
                targets = [h for _, h in swing_highs if h > current_price * 1.001]
                if targets:
                    tp = min(targets)  # nearest swing high
                    break
        # Fallback to ATR if no swing high found
        if tp is None:
            tp = current_price + (atr * 2.5)
    elif action == 'SELL':
        sl = current_price + (atr * 1.5)
        # Target nearest swing low below current price
        tp = None
        for df in [df_h4, df_d1]:
            if df is not None:
                _, swing_lows = find_swing_points(df)
                # Find nearest swing low below current price
                targets = [l for _, l in swing_lows if l < current_price * 0.999]
                if targets:
                    tp = max(targets)  # nearest swing low
                    break
        # Fallback to ATR if no swing low found
        if tp is None:
            tp = current_price - (atr * 2.5)
    # Validate minimum RR of 1:2
    if sl and tp:
        risk = abs(current_price - sl)
        reward = abs(tp - current_price)
        if risk > 0 and reward / risk < 2.0:
            # Extend to next swing point or ATR fallback
            if action == 'BUY':
                tp = current_price + (atr * 2.5)
            elif action == 'SELL':
                tp = current_price - (atr * 2.5)
    return current_price, sl, tp

def analyze_pair(symbol, config):
    result = {'symbol':symbol,'timestamp':datetime.now().isoformat(),'action':'WAIT','score':0,'zone_type':None,'reasons':[],'entry':None,'stop_loss':None,'take_profit':None,'sweep':False,'timeframes':{}}

    print(f"    Fetching D1...")
    print(f"    Fetching H4...")
    print(f"    Fetching H1...")
    df_d1, df_h4, df_h1 = fetch_all_timeframes(symbol, config)

    if df_h1 is None or len(df_h1) < 10:
        print(f"    Insufficient data for {symbol}")
        return result

    current_price = float(df_h1['Close'].values[-1])
    result['current_price'] = current_price

    print(f"    Detecting zones & sweeps...")
    d1_analysis = analyze_timeframe(df_d1, current_price)
    h4_analysis = analyze_timeframe(df_h4, current_price)
    h1_analysis = analyze_timeframe(df_h1, current_price)
    result['timeframes'] = {'D1':d1_analysis,'H4':h4_analysis,'H1':h1_analysis}
    result['sweep'] = any(tf and tf.get('sweep_detected') for tf in [d1_analysis,h4_analysis,h1_analysis])

    print(f"    Calculating confluence...")
    score, reasons = calculate_confluence_score(d1_analysis, h4_analysis, h1_analysis)
    result['score']   = score
    result['reasons'] = reasons

    action, zone_type = determine_action(score, d1_analysis, h4_analysis, h1_analysis, config)
    result['action']    = action
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
        entry, sl, tp = calculate_levels(action, current_price, atr, df_h4, df_d1)
        result['entry']       = entry
        result['stop_loss']   = sl
        result['take_profit'] = tp

    try:
        del df_d1, df_h4, df_h1
    except:
        pass
    gc.collect()
    return result
