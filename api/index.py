from flask import Flask, request, jsonify
import os
import sys
from datetime import datetime
import requests
import logging
import sqlite3
import re
import json
import math
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters

# === CONFIG ===
TOKEN = os.environ.get("BOT_TOKEN", "")
OWNER_ID = int(os.environ.get("OWNER_ID", "6882937271"))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "https://traa-rekap-final.vercel.app/webhook")

# === LOGGING ===
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# === DATABASE (In-memory untuk Vercel) ===
players_db = {}
history_db = {}
settings_db = {}
transactions_db = []

def db_query(query, params=(), fetchone=False, fetchall=False):
    """Simulasi database dengan dictionary"""
    logger.info(f"DB Query: {query} - {params}")
    
    # Untuk SELECT
    if query.startswith("SELECT") and "players" in query:
        results = []
        for name, bal in players_db.items():
            results.append((name, bal))
        if fetchall:
            return results
        elif fetchone and results:
            return results[0]
        return []
    
    elif query.startswith("SELECT") and "game_history" in query:
        chat_id = params[0] if params else None
        results = []
        for game in history_db.get(chat_id, []):
            results.append((game,))
        if fetchall:
            return results
        return []
    
    elif query.startswith("SELECT") and "settings" in query:
        chat_id = params[0] if params else None
        game_num = settings_db.get(chat_id, 1)
        return (game_num,) if fetchone else None
    
    # Untuk INSERT/UPDATE
    elif "INSERT INTO players" in query:
        name = params[0]
        balance = params[1] if len(params) > 1 else 0
        players_db[name] = balance
        return None
    
    elif "UPDATE players" in query:
        name = params[1] if len(params) > 1 else params[0]
        balance = params[0] if "balance = ?" in query else None
        if name in players_db and balance is not None:
            players_db[name] = balance
        return None
    
    elif "DELETE FROM players" in query:
        name = params[0] if params else None
        if name and name in players_db:
            del players_db[name]
        return None
    
    elif "INSERT INTO game_history" in query:
        chat_id = params[0]
        game_text = params[1]
        if chat_id not in history_db:
            history_db[chat_id] = []
        history_db[chat_id].append(game_text)
        return None
    
    elif "INSERT INTO settings" in query or "UPDATE settings" in query:
        chat_id = params[0]
        game_num = params[1] if len(params) > 1 else 1
        settings_db[chat_id] = game_num
        return None
    
    return []

# === BOT HANDLERS ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 REKAPWIN BOT\n\n"
        "Commands:\n"
        "/rekap - Cek nominal\n"
        "/rekapwin [fee] - Hitung kemenangan\n"
        "/bulatkan - Bulatkan saldo\n"
        "/cek [nama] - Cek saldo"
    )

async def rekap_cek(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Balas ke pesan data duel!")
        return
    
    text = update.message.reply_to_message.text
    lines = text.split('\n')
    k_vals, b_vals = [], []
    current = None
    
    for line in lines:
        line = line.strip().upper()
        if line.startswith("K:") or line.startswith("KECIL:"):
            current = "K"
            continue
        elif line.startswith("B:") or line.startswith("BESAR:"):
            current = "B"
            continue
        elif current and line:
            match = re.search(r"(\d+)", line)
            if match:
                val = int(match.group(1))
                if current == "K":
                    k_vals.append(val)
                else:
                    b_vals.append(val)
    
    sum_k, sum_b = sum(k_vals), sum(b_vals)
    msg = f"🔵 KECIL: {k_vals} = {sum_k}\n🔴 BESAR: {b_vals} = {sum_b}\n\n"
    
    if sum_k == sum_b:
        msg += "✅ SAMA!"
    else:
        diff = abs(sum_k - sum_b)
        kurang = "KECIL" if sum_k < sum_b else "BESAR"
        msg += f"⚠️ {kurang} KURANG {diff}"
    
    await update.message.reply_text(msg)

async def rekapwin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Balas ke pesan data duel!")
        return
    
    fee = 5.5
    if context.args:
        try: fee = float(context.args[0])
        except: pass
    
    await update.message.reply_text(
        f"💰 Fee: {fee}%\n🏆 Pilih pemenang:",
        reply_markup=InlineKeyboardMarkup([[
            InlineKeyboardButton("🔵 KECIL", callback_data=f"win_KECIL_{fee}"),
            InlineKeyboardButton("🔴 BESAR", callback_data=f"win_BESAR_{fee}")
        ]])
    )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if data.startswith("win_"):
        _, winner, fee = data.split('_')
        fee = float(fee)
        
        keyboard = [
            [InlineKeyboardButton("2-0", callback_data=f"score_{winner}_{fee}_2-0"),
             InlineKeyboardButton("2-1", callback_data=f"score_{winner}_{fee}_2-1")]
        ]
        await query.edit_message_text("🎯 Pilih skor:", reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif data.startswith("score_"):
        _, winner, fee, score = data.split('_')
        fee = float(fee)
        
        await query.edit_message_text(f"✅ Game selesai! {winner} menang {score}")
        # Di sini nanti proses saldo

# === FLASK APP ===
app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        logger.info(f"Webhook received: {data}")
        
        # Process update with bot
        # This is simplified - in production you'd use Application.process_update()
        
        return jsonify({"status": "ok"})
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"status": "error"}), 200

@app.route('/health')
def health():
    return jsonify({
        "status": "running",
        "time": str(datetime.now()),
        "players": len(players_db)
    })

@app.route('/')
def home():
    return jsonify({"status": "Bot Rekapwin Vercel", "version": "1.0"})

@app.route('/setwebhook')
def set_webhook():
    url = f"https://api.telegram.org/bot{TOKEN}/setWebhook?url={WEBHOOK_URL}"
    response = requests.get(url)
    return jsonify(response.json())

# For local testing
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
