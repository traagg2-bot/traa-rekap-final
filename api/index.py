from flask import Flask, request, jsonify
import os
import sys
from datetime import datetime
import requests
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from bot import bot_instance, db_query

app = Flask(__name__)

# Webhook dari Telegram
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        update = request.get_json()
        if update:
            bot_instance.process_update(update)
        return jsonify({"status": "ok"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# Webhook dari Pakasir (untuk notifikasi pembayaran)
@app.route('/pakasir-webhook', methods=['POST'])
def pakasir_webhook():
    try:
        data = request.get_json()
        print(f"Pakasir Webhook: {data}")
        
        # Cek status pembayaran
        if data and data.get('status') == 'paid':
            order_id = data.get('order_id')
            
            # Update status payment di database
            db_query("UPDATE payments SET status='paid' WHERE id=?", (order_id,))
            
            # Ambil data payment
            payment = db_query("SELECT * FROM payments WHERE id=?", (order_id,), fetchone=True)
            if payment:
                chat_id = payment[2]  # chat_id
                days = payment[3]      # days
                user_id = payment[1]   # user_id
                
                # Aktivasi premium
                expires = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
                db_query("INSERT OR REPLACE INTO premium_groups (chat_id, expires_at, added_by) VALUES (?, ?, ?)",
                        (chat_id, expires, user_id))
                
                # Kirim notifikasi ke user
                try:
                    bot_instance.app.bot.send_message(
                        chat_id=user_id,
                        text=f"✅ *PEMBAYARAN BERHASIL!*\n\n"
                             f"Grup dengan ID `{chat_id}` sekarang PREMIUM selama {days} hari!\n\n"
                             f"Tambahkan bot ke grup dan jadikan admin.",
                        parse_mode='Markdown'
                    )
                except:
                    pass
        
        return jsonify({"status": "ok"})
    except Exception as e:
        print(f"Pakasir webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({"status": "running", "time": str(datetime.now())})

@app.route('/setwebhook', methods=['GET'])
def set_webhook():
    token = os.environ.get("BOT_TOKEN")
    webhook_url = os.environ.get("WEBHOOK_URL")
    url = f"https://api.telegram.org/bot{token}/setWebhook?url={webhook_url}"
    response = requests.get(url)
    return jsonify(response.json())
