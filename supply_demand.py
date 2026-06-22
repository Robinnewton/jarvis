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
    """
    Detect supply and demand zones based on institutional logic:
    - Impulse: 3 consecutive candles in one direction OR 1 large single candle
    - Base: 1-3 candles before the impulse
    - Zone: drawn from wick high to wick low of base candles
    """
    if df is None or len(df) < 10:
        return []
    zones = []
    opens  = df['Open'].values
    highs  = df['High'].values
    lows   = df['Low'].values
    closes = df['Close'].values
    n = len(df)

    # Average body size for reference
    avg_body = np.mean(np.abs(closes - opens))
    if avg_body == 0:
        return []

    def is_bullish(i): return closes[i] > opens[i]
    def is_bearish(i): return closes[i] < opens[i]
    def body_size(i): return abs(closes[i] - opens[i])
    def is_large(i): return body_size(i) > avg_body * 1.5

    for i in range(4, n - 1):
        # ── DEMAND ZONE DETECTION ──
        # Pattern 1: Single large bullish candle impulse
        single_bull_impulse = is_bullish(i) and is_large(i)
        # Pattern 2: Three consecutive bullish candles
        three_bull_impulse = (i >= 3 and
                              is_bullish(i) and is_bullish(i-1) and is_bullish(i-2))

        if single_bull_impulse or three_bull_impulse:
            # Find base candles — look back 1-3 candles before impulse start
            if three_bull_impulse:
                base_start = i - 3  # candle before the 3-candle run
            else:
                base_start = i - 1  # candle before single impulse

            # Base can be 1-3 candles
            for base_len in [1, 2, 3]:
                b_start = base_start - base_len + 1
                b_end   = base_start
                if b_start < 0:
                    continue
                # Zone: wick high to wick low of base candles
                zone_high = max(highs[b_start:b_end+1])
                zone_low  = min(lows[b_start:b_end+1])
                if zone_high <= zone_low:
                    continue
                # Avoid duplicate zones at same level
                duplicate = any(
                    abs(z['high'] - zone_high) < avg_body * 0.5 and z['type'] == 'demand'
                    for z in zones
                )
                if not duplicate:
                    zones.append({
                        'type': 'demand',
                        'high': zone_high,
                        'low': zone_low,
                        'strength': 'strong',
                        'index': i,
                        'base_candles': base_len
                    })
                break  # use smallest valid base

        # ── SUPPLY ZONE DETECTION ──
        # Pattern 1: Single large bearish candle impulse
        single_bear_impulse = is_bearish(i) and is_large(i)
        # Pattern 2: Three consecutive bearish candles
        three_bear_impulse = (i >= 3 and
                              is_bearish(i) and is_bearish(i-1) and is_bearish(i-2))

        if single_bear_impulse or three_bear_impulse:
            # Find base candles before impulse
            if three_bear_impulse:
                base_start = i - 3
            else:
                base_start = i - 1

            for base_len in [1, 2, 3]:
                b_start = base_start - base_len + 1
                b_end   = base_start
                if b_start < 0:
                    continue
                zone_high = max(highs[b_start:b_end+1])
                zone_low  = min(lows[b_start:b_end+1])
                if zone_high <= zone_low:
                    continue
                duplicate = any(
                    abs(z['high'] - zone_high) < avg_body * 0.5 and z['type'] == 'supply'
                    for z in zones
                )
                if not duplicate:
                    zones.append({
                        'type': 'supply',
                        'high': zone_high,
                        'low': zone_low,
                        'strength': 'strong',
                        'index': i,
                        'base_candles': base_len
                    })
                break

    # Remove zones where price has already closed fully through them
    valid_zones = []
    for zone in zones:
        broken = False
        for j in range(zone['index'] + 1, n):
            if zone['type'] == 'demand' and closes[j] < zone['low']:
                broken = True
                break
            if zone['type'] == 'supply' and closes[j] > zone['high']:
                broken = True
                break
        if not broken:
            valid_zones.append(zone)

    return valid_zones[-10:] if len(valid_zones) > 10 else valid_zones

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

def price_approaching_zone(price, zone, approach_pct=0.003):
    """
    Returns True if price is within approach_pct of a zone but not yet inside it.
    Default 0.3% away from zone boundary.
    """
    zone_range = zone['high'] - zone['low']
    approach_distance = max(zone_range * 2, price * approach_pct)
    if zone['type'] == 'supply':
        # Price approaching from below
        return price < zone['low'] and price >= zone['low'] - approach_distance
    elif zone['type'] == 'demand':
        # Price approaching from above
        return price > zone['high'] and price <= zone['high'] + approach_distance
    return False

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
        elif price_approaching_zone(current_price, zone):
            result['price_approaching'] = True
            result['approaching_zone']  = zone
            result['approaching_type']  = zone['type']
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

def get_d1_bias(d1, current_price):
    """
    Determine D1 bias based on supply/demand zones above and below price.
    More supply above = bearish bias
    More demand below = bullish bias
    """
    if not d1 or not d1.get('zones'):
        return 'neutral'
    zones = d1['zones']
    supply_above = [z for z in zones if z['type'] == 'supply' and z['low'] > current_price]
    demand_below = [z for z in zones if z['type'] == 'demand' and z['high'] < current_price]
    if len(supply_above) > len(demand_below):
        return 'bearish'
    elif len(demand_below) > len(supply_above):
        return 'bullish'
    return 'neutral'

def determine_action(score, d1, h4, h1, config, current_price=None):
    if score < 70:
        return 'WAIT', None
    zone_types = [tf['zone_type'] for tf in [d1,h4,h1] if tf and tf.get('zone_type')]
    if not zone_types:
        return 'WAIT', None
    from collections import Counter
    zone_type = Counter(zone_types).most_common(1)[0][0]

    # D1 bias filter — only block if imbalance is significant (3+ more zones in one direction)
    if current_price and d1:
        d1_bias = get_d1_bias(d1, current_price)
        zones = d1.get('zones', [])
        supply_above = len([z for z in zones if z['type'] == 'supply' and z['low'] > current_price])
        demand_below = len([z for z in zones if z['type'] == 'demand' and z['high'] < current_price])
        imbalance = abs(supply_above - demand_below)
        # Only block if strong imbalance (3+ more zones in opposing direction)
        if d1_bias == 'bearish' and zone_type == 'demand' and imbalance >= 3:
            return 'WAIT', None  # Strong bearish bias — don't BUY
        if d1_bias == 'bullish' and zone_type == 'supply' and imbalance >= 3:
            return 'WAIT', None  # Strong bullish bias — don't SELL

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

def calculate_levels(action, current_price, atr):
    if atr is None or atr == 0:
        atr = current_price * 0.005
    if action == 'BUY':
        return current_price, current_price - (atr * 1.5), current_price + (atr * 4.5)
    elif action == 'SELL':
        return current_price, current_price + (atr * 1.5), current_price - (atr * 4.5)
    return None, None, None

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
    # Pass full zone list to d1_analysis for bias calculation
    if d1_analysis:
        d1_analysis['all_zones'] = d1_analysis.get('zones', [])
    result['sweep'] = any(tf and tf.get('sweep_detected') for tf in [d1_analysis,h4_analysis,h1_analysis])

    print(f"    Calculating confluence...")
    score, reasons = calculate_confluence_score(d1_analysis, h4_analysis, h1_analysis)
    result['score']   = score
    result['reasons'] = reasons

    action, zone_type = determine_action(score, d1_analysis, h4_analysis, h1_analysis, config, current_price)
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
        entry, sl, tp = calculate_levels(action, current_price, atr)
        result['entry']       = entry
        result['stop_loss']   = sl
        result['take_profit'] = tp

    try:
        del df_d1, df_h4, df_h1
    except:
        pass
    gc.collect()
    return result
