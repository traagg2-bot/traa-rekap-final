from flask import Flask, request, jsonify
import os
from datetime import datetime
import json

app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        print(f"Webhook: {data}")
        
        # Balas pesan simple
        if data and 'message' in data:
            chat_id = data['message']['chat']['id']
            text = data['message'].get('text', '')
            
            return jsonify({
                "method": "sendMessage",
                "chat_id": chat_id,
                "text": f"✅ Bot Vercel aktif! Pesan: {text}"
            })
        
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error"}), 200  # Tetap 200 biar gak error

@app.route('/health')
def health():
    return jsonify({
        "status": "running",
        "time": str(datetime.now())
    })

@app.route('/')
def home():
    return jsonify({"status": "Bot Rekap Vercel aktif!"})
