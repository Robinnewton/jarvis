import json
import time
import subprocess
import gc
import os
from datetime import datetime, date

SIGNALS_FILE = "signals.json"
TRADE_LOG = "trade_log.json"
COOLDOWN_MINUTES = 60

signal_memory = {}

def load_config():
    with open('config.json', 'r') as f:
        return json.load(f)

def speak(text, config):
    if config.get('voice_enabled', True):
        voice = config.get('voice_name', 'Daniel')
        try:
            subprocess.Popen(['say', '-v', voice, text])
        except Exception as e:
            print(f"Voice error: {e}")

def notify(title, message):
    try:
        script = f'display notification "{message}" with title "{title}" sound name "Glass"'
        subprocess.run(['osascript', '-e', script], check=True)
    except:
        pass

def load_trade_log():
    if os.path.exists(TRADE_LOG):
        with open(TRADE_LOG, 'r') as f:
            data = json.load(f)
            if data.get('date') == str(date.today()):
                return data
    return {'date': str(date.today()), 'trades': 0, 'daily_loss': 0}

def save_trade_log(log):
    with open(TRADE_LOG, 'w') as f:
        json.dump(log, f, indent=2)

def check_risk_limits(config, log):
    max_trades = config.get('risk', {}).get('max_trades_per_day', 2)
    max_loss = config.get('risk', {}).get('daily_loss_limit', 250)
    if log['trades'] >= max_trades:
        return False, f"Max trades reached ({max_trades}/day)"
    if log['daily_loss'] >= max_loss:
        return False, f"Daily loss limit reached (${max_loss})"
    return True, "OK"

def calculate_position_size(account_size, risk_percent, entry, stop_loss):
    risk_amount = account_size * (risk_percent / 100)
    pip_risk = abs(entry - stop_loss)
    if pip_risk == 0:
        return 0

    # Gold (XAU/USD) — price > 500
    if entry > 500:
        position_size = risk_amount / (pip_risk * 100)
        return round(position_size, 2)

    # Forex pairs
    if entry > 10:
        pip_value = 0.01
    else:
        pip_value = 0.0001
    pips = pip_risk / pip_value
    if pips == 0:
        return 0
    position_size = risk_amount / (pips * 10)
    return round(position_size, 2)

def is_in_cooldown(symbol, new_action):
    if symbol not in signal_memory:
        return False
    last = signal_memory[symbol]
    elapsed = (datetime.now() - last['time']).total_seconds() / 60
    if last['action'] != new_action and elapsed < COOLDOWN_MINUTES:
        print(f"    [COOLDOWN] {symbol} fired {last['action']} {elapsed:.0f} min ago — blocking {new_action}")
        return True
    if last['action'] == new_action and elapsed < COOLDOWN_MINUTES / 2:
        print(f"    [COOLDOWN] {symbol} same direction repeat — waiting {COOLDOWN_MINUTES/2:.0f} min")
        return True
    return False

def is_trading_session():
    """Only trade during London and New York sessions (UTC times), weekdays only"""
    now_utc = datetime.utcnow()
    hour = now_utc.hour
    weekday = now_utc.weekday()  # 0=Monday, 6=Sunday
    # Block weekends — Saturday and Sunday
    if weekday >= 5:
        return False
    # London: 07:00 - 16:00 UTC
    # New York: 12:00 - 21:00 UTC
    # Combined window: 07:00 - 21:00 UTC
    return 7 <= hour < 21

def save_signals(signals):
    with open(SIGNALS_FILE, 'w') as f:
        json.dump(signals, f, indent=2, default=str)

def run_scan(config):
    from supply_demand import analyze_pair

    pairs = config.get('pairs', [])
    min_score = config.get('filters', {}).get('min_score', 70)
    account_size = config.get('risk', {}).get('account_size', 5000)
    risk_percent = config.get('risk', {}).get('risk_per_trade', 1)

    log = load_trade_log()
    can_trade, reason = check_risk_limits(config, log)

    print(f"\n{'='*60}")
    print(f"JARVIS SUPPLY & DEMAND SCANNER")
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Account: ${account_size} | Risk: {risk_percent}% = ${account_size * risk_percent / 100}")
    print(f"Today: {log['trades']} trades | ${log['daily_loss']} loss")
    print(f"Status: {'ACTIVE' if can_trade else 'PAUSED - ' + reason}")
    print(f"{'='*60}")

    if not can_trade:
        speak(f"Scanning paused. {reason}", config)
        return []

    speak("Scanning markets.", config)

    all_signals = []
    actionable = []

    # Session filter
    if not is_trading_session():
        from datetime import datetime as dt
        hour = dt.utcnow().hour
        from datetime import datetime as dt
        weekday = dt.utcnow().weekday()
        if weekday >= 5:
            print(f"\n  Markets closed — weekend. Trading resumes Monday 07:00 UTC.")
        else:
            print(f"\n  Outside trading sessions (UTC hour: {hour}). London opens at 07:00 UTC.")
        speak("Markets are outside active sessions.", config)
        return []

    for i, pair in enumerate(pairs):
        print(f"\n[{i+1}/{len(pairs)}] Analyzing {pair}...")
        try:
            result = analyze_pair(pair, config)
            all_signals.append(result)

            if result['action'] != 'WAIT' and result['score'] >= min_score:
                if is_in_cooldown(pair, result['action']):
                    print(f"    Score: {result['score']}% - Signal blocked by cooldown")
                    result['action'] = 'WAIT'
                    continue

                signal_memory[pair] = {
                    'action': result['action'],
                    'time': datetime.now()
                }

                if result['entry'] and result['stop_loss']:
                    result['position_size'] = calculate_position_size(
                        account_size, risk_percent,
                        result['entry'], result['stop_loss']
                    )
                    result['risk_amount'] = account_size * risk_percent / 100

                actionable.append(result)
                print(f"    >>> {result['action']} SIGNAL - Score: {result['score']}%")
                print(f"    >>> Entry: {result['entry']:.5f}")
                print(f"    >>> SL: {result['stop_loss']:.5f}")
                print(f"    >>> TP: {result['take_profit']:.5f}")
                print(f"    >>> Position: {result.get('position_size', 'N/A')} lots")
            else:
                print(f"    Score: {result['score']}% - No signal")

        except Exception as e:
            print(f"    Error: {e}")
            import traceback
            traceback.print_exc()

        gc.collect()

    save_signals({
        'timestamp': datetime.now().isoformat(),
        'account_size': account_size,
        'risk_percent': risk_percent,
        'total_pairs': len(pairs),
        'actionable_count': len(actionable),
        'signals': all_signals,
        'actionable': actionable
    })

    print(f"\n{'='*60}")
    print(f"SCAN COMPLETE | Pairs: {len(pairs)} | Signals: {len(actionable)}")
    print(f"{'='*60}")

    if actionable:
        speak(f"{len(actionable)} trading signal detected.", config)
        for sig in actionable:
            pair_name = sig['symbol'].replace('=X', '').replace('=F', '')
            speak(f"{sig['action']} signal on {pair_name}. Score {sig['score']} percent.", config)
            notify(f"JARVIS: {sig['action']} {pair_name}",
                   f"Score: {sig['score']}% | Entry: {sig['entry']:.5f}")
    else:
        speak("Scan complete. No signals.", config)

    gc.collect()
    return actionable

def main():
    print("\n" + "="*60)
    print("     J.A.R.V.I.S. SUPPLY & DEMAND SCANNER")
    print("     Version 2.1 | Cooldown Protection Active")
    print("="*60 + "\n")

    config = load_config()
    speak("JARVIS online. Signal cooldown protection active.", config)

    interval = config.get('scan_interval_minutes', 15)

    while True:
        try:
            run_scan(config)
            print(f"\nNext scan in {interval} minutes...")
            print("Press Ctrl+C to stop")
            time.sleep(interval * 60)
        except KeyboardInterrupt:
            print("\n\nShutting down...")
            speak("JARVIS shutting down.", config)
            break
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
            time.sleep(60)

if __name__ == "__main__":
    main()
