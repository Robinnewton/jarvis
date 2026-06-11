from flask import Flask, request, jsonify
import json
import subprocess
import os
from datetime import datetime

app = Flask(__name__)
SIGNALS_FILE = "signals.json"
LOG_FILE = "eden_alerts.log"

def speak(text):
    try:
        subprocess.Popen(['say', '-v', 'Daniel', text])
    except Exception as e:
        print(f"Voice error: {e}")

def notify(title, message):
    try:
        script = f'display notification "{message}" with title "{title}" sound name "Glass"'
        subprocess.run(['osascript', '-e', script], check=True)
    except:
        pass

def log_alert(data):
    with open(LOG_FILE, 'a') as f:
        f.write(f"\n{'='*50}\n")
        f.write(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Alert: {json.dumps(data, indent=2)}\n")

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        # Accept both JSON and plain text from TradingView
        if request.is_json:
            data = request.get_json()
            message = data.get('message', str(data))
        else:
            message = request.data.decode('utf-8')
            data = {'message': message}

        print(f"\n{'='*50}")
        print(f"EDEN ALERT RECEIVED")
        print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"Message: {message}")
        print(f"{'='*50}")

        # Log the alert
        log_alert(data)

        # Parse signal type from message
        message_upper = message.upper()

        if 'BUY' in message_upper:
            speak("Eden. Buy signal detected.")
            notify("EDEN BUY SIGNAL", message)
        elif 'SELL' in message_upper:
            speak("Eden. Sell signal detected.")
            notify("EDEN SELL SIGNAL", message)
        elif 'CHOCH' in message_upper:
            speak("Eden. Change of character detected. Structure shifting.")
            notify("EDEN CHOCH", message)
        elif 'BOS' in message_upper:
            speak("Eden. Break of structure confirmed.")
            notify("EDEN BOS", message)
        else:
            speak("Eden alert received.")
            notify("EDEN ALERT", message)

        return jsonify({'status': 'ok', 'received': message}), 200

    except Exception as e:
        print(f"Webhook error: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'online',
        'time': datetime.now().isoformat(),
        'name': 'Eden Webhook Receiver'
    }), 200

if __name__ == '__main__':
    print("\n" + "="*50)
    print("  EDEN WEBHOOK RECEIVER")
    print("  Listening for TradingView alerts...")
    print("  Webhook URL: /webhook")
    print("  Health check: /health")
    print("="*50 + "\n")
    app.run(host='0.0.0.0', port=5001, debug=False)
