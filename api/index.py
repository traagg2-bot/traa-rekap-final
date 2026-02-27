from flask import Flask, request, jsonify
import requests
import os

app = Flask(__name__)
TOKEN = "8708452430:AAENurTtTwMSZLPAz9rOLrR6GtnNxvg2GaI"

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        if data and 'message' in data:
            chat_id = data['message']['chat']['id']
            text = data['message'].get('text', '')
            
            # KIRIM BALASAN
            url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
            payload = {
                "chat_id": chat_id,
                "text": f"TEST: {text}"
            }
            requests.post(url, json=payload)
            
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}

@app.route('/health')
def health():
    return {"status": "ok"}

@app.route('/setwebhook')
def set_webhook():
    url = f"https://api.telegram.org/bot{TOKEN}/setWebhook?url=https://traa-rekap-final.vercel.app/webhook"
    r = requests.get(url)
    return r.json()
