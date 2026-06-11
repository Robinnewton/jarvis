from flask import Flask, render_template_string, jsonify
import json
import os
from datetime import datetime

app = Flask(__name__)
SIGNALS_FILE = "signals.json"

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <title>JARVIS Supply & Demand Scanner</title>
    <meta http-equiv="refresh" content="30">
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #eee;
            font-family: -apple-system, BlinkMacSystemFont, sans-serif;
            min-height: 100vh;
            padding: 20px;
        }
        .header { text-align: center; padding: 20px; border-bottom: 1px solid #333; margin-bottom: 20px; }
        .header h1 {
            font-size: 2.5em;
            background: linear-gradient(90deg, #00d4ff, #00ff88);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-bottom: 10px;
        }
        .stale-banner {
            background: #ff4444; color: white; text-align: center;
            padding: 12px; font-size: 1.1em; font-weight: bold;
            border-radius: 8px; margin-bottom: 20px;
            animation: blink 1.5s infinite;
        }
        .fresh-banner {
            background: #00aa44; color: white; text-align: center;
            padding: 12px; font-size: 1em; border-radius: 8px; margin-bottom: 20px;
        }
        @keyframes blink { 0%,100%{opacity:1} 50%{opacity:0.6} }
        .status { display: flex; justify-content: center; gap: 30px; flex-wrap: wrap; margin-bottom: 20px; }
        .status-box { background: rgba(255,255,255,0.05); padding: 15px 25px; border-radius: 10px; text-align: center; }
        .status-box .label { color: #888; font-size: 0.9em; }
        .status-box .value { font-size: 1.5em; font-weight: bold; color: #00d4ff; }
        .signals-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(350px, 1fr)); gap: 20px; margin-top: 20px; }
        .signal-card { background: rgba(255,255,255,0.05); border-radius: 15px; padding: 20px; border: 1px solid #333; }
        .signal-card.buy  { border-left: 4px solid #00ff88; }
        .signal-card.sell { border-left: 4px solid #ff4444; }
        .signal-card.wait { border-left: 4px solid #666; }
        .pair-name { font-size: 1.4em; font-weight: bold; margin-bottom: 10px; }
        .action { display: inline-block; padding: 5px 15px; border-radius: 5px; font-weight: bold; margin-bottom: 10px; }
        .action.buy  { background: #00ff88; color: #000; }
        .action.sell { background: #ff4444; color: #fff; }
        .action.wait { background: #666; color: #fff; }
        .score { font-size: 2em; font-weight: bold; margin: 10px 0; }
        .score.high   { color: #00ff88; }
        .score.medium { color: #ffaa00; }
        .score.low    { color: #666; }
        .details { margin-top: 15px; }
        .detail-row { display: flex; justify-content: space-between; padding: 5px 0; border-bottom: 1px solid #333; }
        .detail-row:last-child { border-bottom: none; }
        .reasons { margin-top: 10px; padding: 10px; background: rgba(0,0,0,0.3); border-radius: 8px; }
        .reason-tag { display: inline-block; background: rgba(0,212,255,0.2); padding: 3px 8px; border-radius: 4px; margin: 2px; font-size: 0.85em; }
        .sweep-tag { display: inline-block; background: rgba(255,170,0,0.3); color: #ffaa00; padding: 3px 8px; border-radius: 4px; margin: 2px; font-size: 0.85em; font-weight: bold; }
        .no-signals { text-align: center; padding: 50px; color: #666; font-size: 1.2em; }
        .timestamp { text-align: center; color: #666; margin-top: 20px; font-size: 0.9em; }
        .terminal-rule { text-align: center; color: #ff4444; margin-top: 10px; font-size: 0.85em; font-weight: bold; }
    </style>
</head>
<body>
    <div class="header">
        <h1>J.A.R.V.I.S.</h1>
        <p>Supply & Demand Scanner — Twelve Data Feed</p>
    </div>

    {% if stale %}
    <div class="stale-banner">
        ⚠️ DATA IS {{ minutes_old }} MINUTES OLD — VERIFY IN TERMINAL BEFORE TRADING
    </div>
    {% else %}
    <div class="fresh-banner">
        ✅ Data is fresh — scanned {{ minutes_old }} minutes ago
    </div>
    {% endif %}

    <div class="status">
        <div class="status-box"><div class="label">Account</div><div class="value">${{ data.account_size | default(5000) }}</div></div>
        <div class="status-box"><div class="label">Risk/Trade</div><div class="value">{{ data.risk_percent | default(1) }}%</div></div>
        <div class="status-box"><div class="label">Pairs Scanned</div><div class="value">{{ data.total_pairs | default(0) }}</div></div>
        <div class="status-box"><div class="label">Signals Found</div><div class="value">{{ data.actionable_count | default(0) }}</div></div>
    </div>

    {% if data.actionable and data.actionable | length > 0 %}
    <h2 style="text-align:center;margin:20px 0;color:#00ff88;">🎯 ACTIONABLE SIGNALS</h2>
    <div class="signals-grid">
        {% for sig in data.actionable %}
        <div class="signal-card {{ sig.action | lower }}">
            <div class="pair-name">{{ sig.symbol }}</div>
            <span class="action {{ sig.action | lower }}">{{ sig.action }}</span>
            {% if sig.get('sweep') %}<span class="sweep-tag">⚡ LIQUIDITY SWEEP</span>{% endif %}
            <div class="score {{ 'high' if sig.score >= 80 else ('medium' if sig.score >= 70 else 'low') }}">{{ sig.score }}%</div>
            <div class="details">
                <div class="detail-row"><span>Entry</span><span>{{ "%.5f" | format(sig.entry) if sig.entry else "N/A" }}</span></div>
                <div class="detail-row"><span>Stop Loss</span><span>{{ "%.5f" | format(sig.stop_loss) if sig.stop_loss else "N/A" }}</span></div>
                <div class="detail-row"><span>Take Profit</span><span>{{ "%.5f" | format(sig.take_profit) if sig.take_profit else "N/A" }}</span></div>
                <div class="detail-row"><span>Position Size</span><span>{{ sig.position_size | default("N/A") }} lots</span></div>
            </div>
            {% if sig.reasons %}
            <div class="reasons">
                {% for reason in sig.reasons %}<span class="reason-tag">{{ reason }}</span>{% endfor %}
            </div>
            {% endif %}
        </div>
        {% endfor %}
    </div>
    {% else %}
    <div class="no-signals">
        <p>No actionable signals at this time.</p>
        <p>JARVIS is scanning every 15 minutes.</p>
    </div>
    {% endif %}

    <h2 style="text-align:center;margin:30px 0 20px;color:#888;">All Pairs</h2>
    <div class="signals-grid">
        {% for sig in data.signals %}
        <div class="signal-card {{ sig.action | lower }}">
            <div class="pair-name">{{ sig.symbol }}</div>
            <span class="action {{ sig.action | lower }}">{{ sig.action }}</span>
            <div class="score {{ 'high' if sig.score >= 80 else ('medium' if sig.score >= 70 else 'low') }}">{{ sig.score }}%</div>
            {% if sig.reasons %}
            <div class="reasons">
                {% for reason in sig.reasons %}<span class="reason-tag">{{ reason }}</span>{% endfor %}
            </div>
            {% endif %}
        </div>
        {% endfor %}
    </div>

    <div class="timestamp">Last scan: {{ data.timestamp | default("Never") }}</div>
    <div class="terminal-rule">⚠ Always verify signals in Terminal before executing any trade</div>
</body>
</html>
'''

@app.route('/')
def index():
    data = {}
    stale = True
    minutes_old = 999
    if os.path.exists(SIGNALS_FILE):
        try:
            with open(SIGNALS_FILE, 'r') as f:
                data = json.load(f)
            if data.get('timestamp'):
                scan_time = datetime.fromisoformat(data['timestamp'])
                diff = (datetime.now() - scan_time).total_seconds() / 60
                minutes_old = int(diff)
                stale = diff > 16
        except:
            pass
    return render_template_string(HTML_TEMPLATE, data=data, stale=stale, minutes_old=minutes_old)

@app.route('/api/signals')
def api_signals():
    if os.path.exists(SIGNALS_FILE):
        try:
            with open(SIGNALS_FILE, 'r') as f:
                return jsonify(json.load(f))
        except:
            pass
    return jsonify({})

if __name__ == '__main__':
    print("\n" + "="*50)
    print("JARVIS Dashboard — Twelve Data Feed")
    print("Open: http://localhost:5000")
    print("="*50 + "\n")
    app.run(host='0.0.0.0', port=5000, debug=False)
