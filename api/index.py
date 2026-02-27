from flask import Flask, request, jsonify
import os
import sys
from datetime import datetime
import requests

# Tambah path biar bisa import bot
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import bot (kalo ada error, comment dulu)
try:
    from bot import bot_instance
except:
    bot_instance = None
    print("Bot instance not loaded")

app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        print(f"Webhook received: {data}")
        
        # Test response
        if data and 'message' in data:
            chat_id = data['message']['chat']['id']
            text = data['message'].get('text', '')
            
            return jsonify({
                "method": "sendMessage",
                "chat_id": chat_id,
                "text": f"Bot Railway aktif! Pesan: {text}"
            })
        
        return jsonify({"status": "ok"})
    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"status": "error"}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        "status": "running", 
        "time": str(datetime.now()),
        "bot_loaded": bot_instance is not None
    })

@app.route('/', methods=['GET'])
def home():
    return jsonify({"status": "Bot Rekap Railway aktif!"})

# Untuk local testing
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
