import yfinance as yf
import talib
import numpy as np
import pandas as pd
import time
import os
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

def compute_indicators(df):
    if df is None or len(df) < 30:
        return None
    
    close = df['Close'].values.astype(float)
    high = df['High'].values.astype(float)
    low = df['Low'].values.astype(float)
    
    result = {}
    
    result['ema_8'] = talib.EMA(close, timeperiod=8)[-1]
    result['ema_21'] = talib.EMA(close, timeperiod=21)[-1]
    result['ema_55'] = talib.EMA(close, timeperiod=55)[-1]
    
    result['rsi'] = talib.RSI(close, timeperiod=14)[-1]
    
    macd, macdsig, macdhist = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
    result['macd'] = macd[-1]
    result['macd_signal'] = macdsig[-1]
    result['macd_hist'] = macdhist[-1]
    
    upper, middle, lower = talib.BBANDS(close, timeperiod=20, nbdevup=2, nbdevdn=2)
    result['bb_upper'] = upper[-1]
    result['bb_middle'] = middle[-1]
    result['bb_lower'] = lower[-1]
    result['bb_position'] = (close[-1] - lower[-1]) / (upper[-1] - lower[-1]) if upper[-1] != lower[-1] else 0.5
    
    result['atr'] = talib.ATR(high, low, close, timeperiod=14)[-1]
    result['adx'] = talib.ADX(high, low, close, timeperiod=14)[-1]
    
    result['close'] = close[-1]
    result['prev_close'] = close[-2] if len(close) > 1 else close[-1]
    
    return result

def analyze_timeframe(indicators):
    if indicators is None:
        return {'bias': 'neutral', 'strength': 0, 'signals': []}
    
    signals = []
    bullish = 0
    bearish = 0
    
    if indicators['ema_8'] > indicators['ema_21'] > indicators['ema_55']:
        bullish += 2
        signals.append("EMA bullish stack")
    elif indicators['ema_8'] < indicators['ema_21'] < indicators['ema_55']:
        bearish += 2
        signals.append("EMA bearish stack")
    
    if indicators['rsi'] < 30:
        bullish += 1
        signals.append("RSI oversold")
    elif indicators['rsi'] > 70:
        bearish += 1
        signals.append("RSI overbought")
    
    if indicators['macd'] > indicators['macd_signal'] and indicators['macd_hist'] > 0:
        bullish += 1
        signals.append("MACD bullish")
    elif indicators['macd'] < indicators['macd_signal'] and indicators['macd_hist'] < 0:
        bearish += 1
        signals.append("MACD bearish")
    
    if indicators['bb_position'] < 0.2:
        bullish += 1
        signals.append("BB oversold")
    elif indicators['bb_position'] > 0.8:
        bearish += 1
        signals.append("BB overbought")
    
    if indicators['adx'] > 25:
        signals.append(f"Strong trend ADX={indicators['adx']:.1f}")
    
    total = bullish + bearish
    if total == 0:
        return {'bias': 'neutral', 'strength': 0, 'signals': signals}
    
    if bullish > bearish:
        return {'bias': 'bullish', 'strength': (bullish / total) * 100, 'signals': signals}
    elif bearish > bullish:
        return {'bias': 'bearish', 'strength': (bearish / total) * 100, 'signals': signals}
    else:
        return {'bias': 'neutral', 'strength': 50, 'signals': signals}

def analyze_pair(symbol, config):
    result = {
        'symbol': symbol,
        'timestamp': datetime.now().isoformat(),
        'timeframes': {},
        'overall_bias': 'neutral',
        'overall_score': 0,
        'action': 'WAIT',
        'entry': None,
        'stop_loss': None,
        'take_profit': None
    }
    
    tf_configs = [
        ('D1', '60d', '1d', 3),
        ('H4', '30d', '1h', 2),
        ('H1', '7d', '1h', 1)
    ]
    
    d1_indicators = None
    
    for tf_name, period, interval, weight in tf_configs:
        print(f"    Fetching {tf_name}...")
        df = fetch_data(symbol, period, interval)
        
        if tf_name == 'H4' and df is not None:
            df = df.resample('4H').agg({
                'Open': 'first',
                'High': 'max',
                'Low': 'min',
                'Close': 'last',
                'Volume': 'sum'
            }).dropna()
        
        indicators = compute_indicators(df)
        
        if tf_name == 'D1':
            d1_indicators = indicators
        
        analysis = analyze_timeframe(indicators)
        analysis['weight'] = weight
        result['timeframes'][tf_name] = analysis
        
        del df
    
    bullish_weight = 0
    bearish_weight = 0
    total_weight = 0
    
    for tf_name, tf_data in result['timeframes'].items():
        w = tf_data['weight']
        total_weight += w
        if tf_data['bias'] == 'bullish':
            bullish_weight += w * tf_data['strength']
        elif tf_data['bias'] == 'bearish':
            bearish_weight += w * tf_data['strength']
    
    if total_weight > 0:
        bull_score = bullish_weight / total_weight
        bear_score = bearish_weight / total_weight
        
        if bull_score > bear_score and bull_score > 50:
            result['overall_bias'] = 'bullish'
            result['overall_score'] = bull_score
        elif bear_score > bull_score and bear_score > 50:
            result['overall_bias'] = 'bearish'
            result['overall_score'] = bear_score
        else:
            result['overall_bias'] = 'neutral'
            result['overall_score'] = max(bull_score, bear_score)
    
    if result['overall_score'] >= 75:
        if result['overall_bias'] == 'bullish':
            result['action'] = 'BUY'
        elif result['overall_bias'] == 'bearish':
            result['action'] = 'SELL'
    
    if d1_indicators and result['action'] != 'WAIT':
        atr = d1_indicators['atr']
        close = d1_indicators['close']
        
        result['entry'] = close
        if result['action'] == 'BUY':
            result['stop_loss'] = close - (atr * 1.5)
            result['take_profit'] = close + (atr * 2.5)
        else:
            result['stop_loss'] = close + (atr * 1.5)
            result['take_profit'] = close - (atr * 2.5)
    
    return result
