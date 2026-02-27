from flask import Flask, request, jsonify
import requests
import json
import re
import os
from datetime import datetime

app = Flask(__name__)
TOKEN = "8708452430:AAENurTtTwMSZLPAz9rOLrR6GtnNxvg2GaI"
OWNER_ID = 6882937271

# Database sederhana
players = {}
games = {}

def send_message(chat_id, text):
    """Kirim pesan ke Telegram"""
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=payload)

def send_button(chat_id, text, buttons):
    """Kirim pesan dengan button"""
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "reply_markup": {
            "inline_keyboard": buttons
        }
    }
    requests.post(url, json=payload)

def answer_callback(callback_id, text):
    """Jawab callback query"""
    url = f"https://api.telegram.org/bot{TOKEN}/answerCallbackQuery"
    payload = {
        "callback_query_id": callback_id,
        "text": text
    }
    requests.post(url, json=payload)

def edit_message(chat_id, message_id, text):
    """Edit pesan"""
    url = f"https://api.telegram.org/bot{TOKEN}/editMessageText"
    payload = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    requests.post(url, json=payload)

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.get_json()
    print(data)
    
    # Handle message
    if 'message' in data:
        chat_id = data['message']['chat']['id']
        text = data['message'].get('text', '')
        user_id = data['message']['from']['id']
        username = data['message']['from'].get('username', 'user')
        
        # ===== COMMAND HANDLER =====
        if text == '/start':
            msg = (
                "🤖 *REKAPWIN BOT*\n\n"
                "Commands:\n"
                "/rekap - Cek nominal\n"
                "/rekapwin - Hitung kemenangan\n"
                "/cek - Cek saldo\n"
                "/tambah [nama] [jumlah] - Tambah saldo\n"
                "/reset - Reset data"
            )
            send_message(chat_id, msg)
        
        elif text.startswith('/rekap'):
            if not data['message'].get('reply_to_message'):
                send_message(chat_id, "❌ Balas ke pesan data duel!")
            else:
                reply_text = data['message']['reply_to_message']['text']
                # Parse sederhana
                k_vals = re.findall(r'K.*?(\d+)', reply_text, re.IGNORECASE)
                b_vals = re.findall(r'B.*?(\d+)', reply_text, re.IGNORECASE)
                k_total = sum([int(x) for x in k_vals])
                b_total = sum([int(x) for x in b_vals])
                msg = f"🔵 KECIL: {k_total}\n🔴 BESAR: {b_total}"
                if k_total == b_total:
                    msg += "\n✅ SAMA!"
                else:
                    msg += f"\n⚠️ SELISIH {abs(k_total-b_total)}"
                send_message(chat_id, msg)
        
        elif text == '/rekapwin':
            if not data['message'].get('reply_to_message'):
                send_message(chat_id, "❌ Balas ke pesan data duel!")
            else:
                # Simpan data duel
                games[str(chat_id)] = {
                    "reply_text": data['message']['reply_to_message']['text'],
                    "step": "choose_winner"
                }
                # Kirim button
                buttons = [[
                    {"text": "🔵 KECIL", "callback_data": "winner_KECIL"},
                    {"text": "🔴 BESAR", "callback_data": "winner_BESAR"}
                ]]
                send_button(chat_id, "🏆 Pilih pemenang:", buttons)
        
        elif text.startswith('/tambah'):
            parts = text.split()
            if len(parts) == 3:
                name = parts[1].upper()
                try:
                    amount = int(parts[2])
                    if name in players:
                        players[name] += amount
                    else:
                        players[name] = amount
                    send_message(chat_id, f"✅ {name} +{amount}")
                except:
                    send_message(chat_id, "❌ Jumlah harus angka")
            else:
                send_message(chat_id, "❌ Format: /tambah NAMA JUMLAH")
        
        elif text == '/cek':
            if not players:
                send_message(chat_id, "📭 Belum ada data")
            else:
                msg = "💰 *SALDO:*\n"
                for n, b in players.items():
                    msg += f"{n}: {b}\n"
                send_message(chat_id, msg)
        
        elif text == '/reset' and user_id == OWNER_ID:
            players.clear()
            games.clear()
            send_message(chat_id, "✅ Data direset!")
    
    # Handle callback query (button)
    elif 'callback_query' in data:
        cb = data['callback_query']
        callback_id = cb['id']
        chat_id = cb['message']['chat']['id']
        message_id = cb['message']['message_id']
        data_cb = cb['data']
        
        answer_callback(callback_id, "OK")
        
        if data_cb.startswith('winner_'):
            winner = data_cb.replace('winner_', '')
            games[str(chat_id)]['winner'] = winner
            games[str(chat_id)]['step'] = 'choose_score'
            
            buttons = [[
                {"text": "2-0", "callback_data": "score_2-0"},
                {"text": "2-1", "callback_data": "score_2-1"}
            ]]
            edit_message(chat_id, message_id, f"🎯 Pilih skor untuk {winner}:")
            url = f"https://api.telegram.org/bot{TOKEN}/editMessageReplyMarkup"
            payload = {
                "chat_id": chat_id,
                "message_id": message_id,
                "reply_markup": {"inline_keyboard": buttons}
            }
            requests.post(url, json=payload)
        
        elif data_cb.startswith('score_'):
            score = data_cb.replace('score_', '')
            game = games.get(str(chat_id), {})
            winner = game.get('winner', 'KECIL')
            
            edit_message(chat_id, message_id, f"✅ Game selesai!\n{winner} menang {score}")
            
            # Hapus session
            if str(chat_id) in games:
                del games[str(chat_id)]
    
    return {"ok": True}

@app.route('/health')
def health():
    return {"status": "ok", "time": str(datetime.now())}

@app.route('/setwebhook')
def set_webhook():
    url = f"https://api.telegram.org/bot{TOKEN}/setWebhook?url=https://traa-rekap-final.vercel.app/webhook"
    r = requests.get(url)
    return r.json()
