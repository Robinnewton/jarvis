import subprocess
import json

def send_to_whatsapp(message):
    """Send message via OpenClaw to WhatsApp"""
    try:
        subprocess.run([
            'openclaw', 'message', 'send',
            '--channel', 'whatsapp',
            '--target', '+254790089704',
            '--message', message
        ], check=True, capture_output=True, timeout=30)
        print(f"    WhatsApp sent: {message[:50]}...")
        return True
    except Exception as e:
        print(f"    WhatsApp error: {e}")
        return False

def format_signal(sig):
    """Format a JARVIS signal into a readable WhatsApp message"""
    pair = sig['symbol'].replace('=X', '')
    
    msg = f"🤖 *JARVIS SIGNAL*\n\n"
    msg += f"*{sig['action']}* {pair}\n"
    msg += f"Score: *{sig['score']}%*\n"
    
    if sig.get('trend_label'):
        if 'WITH' in sig['trend_label']:
            msg += f"Direction: ✅ {sig['trend_label']}\n"
        else:
            msg += f"Direction: ⚠️ {sig['trend_label']}\n"
    
    msg += f"\n📊 *Levels:*\n"
    
    if sig.get('entry'):
        msg += f"Entry: {sig['entry']:.5f}\n"
    if sig.get('stop_loss'):
        msg += f"Stop Loss: {sig['stop_loss']:.5f}\n"
    if sig.get('take_profit'):
        msg += f"Take Profit: {sig['take_profit']:.5f}\n"
    if sig.get('position_size'):
        msg += f"Position: {sig['position_size']} lots\n"
    if sig.get('risk_amount'):
        msg += f"Risk: ${sig['risk_amount']:.0f}\n"
    
    if sig.get('reasons'):
        msg += f"\n🔍 *Reasons:*\n"
        for r in sig['reasons']:
            msg += f"• {r}\n"
    
    msg += f"\n⏰ {sig.get('timestamp', 'N/A')}"
    
    return msg

def notify_signal(sig):
    """Format and send a signal to WhatsApp"""
    message = format_signal(sig)
    return send_to_whatsapp(message)

def notify_scan_complete(total, actionable_count):
    """Send scan summary"""
    if actionable_count > 0:
        msg = f"🤖 JARVIS: Scan complete. {actionable_count} signal(s) from {total} pairs."
    else:
        msg = f"🤖 JARVIS: Scan complete. No signals from {total} pairs."
    return send_to_whatsapp(msg)
