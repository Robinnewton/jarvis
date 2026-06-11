import pandas as pd
import os
import time
import gc
from datetime import datetime, timedelta
from twelvedata import TDClient

CACHE_DIR = "cache"
CACHE_MINUTES = 14

def ensure_cache_dir():
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)

def get_cache_path(symbol, interval):
    safe = symbol.replace("/", "_").replace("=", "_")
    return os.path.join(CACHE_DIR, f"{safe}_{interval}.csv")

def is_cache_valid(path):
    if not os.path.exists(path):
        return False
    mtime = datetime.fromtimestamp(os.path.getmtime(path))
    return datetime.now() - mtime < timedelta(minutes=CACHE_MINUTES)

def fetch_data(symbol, interval, outputsize, apikey):
    ensure_cache_dir()
    cache_path = get_cache_path(symbol, interval)

    if is_cache_valid(cache_path):
        try:
            df = pd.read_csv(cache_path, index_col=0, parse_dates=True)
            if len(df) > 10:
                return df
        except:
            pass

    time.sleep(10)
    try:
        td = TDClient(apikey=apikey)
        ts = td.time_series(
            symbol=symbol,
            interval=interval,
            outputsize=outputsize
        ).as_pandas()

        if ts is None or len(ts) < 10:
            return None

        ts.columns = [c.title() for c in ts.columns]
        ts = ts.sort_index()
        ts.to_csv(cache_path)
        gc.collect()
        return ts

    except Exception as e:
        print(f"    Fetch error {symbol} {interval}: {e}")
        return None

def fetch_all_timeframes(symbol, config):
    apikey = config.get('twelvedata_api_key', '')
    tfs    = config.get('timeframes', {})

    df_d1 = fetch_data(symbol, tfs['D1']['interval'], tfs['D1']['outputsize'], apikey)
    df_h4 = fetch_data(symbol, tfs['H4']['interval'], tfs['H4']['outputsize'], apikey)
    df_h1 = fetch_data(symbol, tfs['H1']['interval'], tfs['H1']['outputsize'], apikey)

    return df_d1, df_h4, df_h1
