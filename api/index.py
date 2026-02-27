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
import asyncio

# === CONFIG ===
TOKEN = os.environ.get("BOT_TOKEN", "")
OWNER_ID = int(os.environ.get("OWNER_ID", "6882937271"))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "https://traa-rekap-final.vercel.app/webhook")

# === LOGGING ===
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# === IN-MEMORY DATABASE ===
players_db = {}
history_db = {}
settings_db = {}

# === BOT APPLICATION ===
application = Application.builder().token(TOKEN).build()

# ==================== HELPER FUNCTIONS ====================
def parse_duel_data(text):
    teams = {"KECIL": [], "BESAR": []}
    current_team = None
    for line in text.split('\n'):
        line = line.strip()
        if not line: 
            continue
        if line.upper().startswith("KECIL:") or line.upper().startswith("K:"):
            current_team = "KECIL"
            continue
        elif line.upper().startswith("BESAR:") or line.upper().startswith("B:"):
            current_team = "BESAR"
            continue
        elif current_team:
            match = re.search(r"(.+?)\s+(\d+)", line)
            if match:
                name = match.group(1).strip().upper()
                modal = int(match.group(2))
                teams[current_team].append({"name": name, "modal": modal})
    return teams

def hitung_setelah_fee(modal, fee_persen):
    hasil_kotor = modal * 2
    potongan = math.ceil(hasil_kotor * (fee_persen / 100))
    return hasil_kotor - potongan

def bulatkan_ke_bawah(angka):
    if angka >= 0:
        return (angka // 100) * 100
    else:
        return -((abs(angka) + 99) // 100 * 100)

# ==================== COMMAND HANDLERS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *REKAPWIN BOT VERCEL*\n\n"
        "Commands:\n"
        "• `/rekap` - Cek nominal\n"
        "• `/rekapwin [fee]` - Hitung kemenangan\n"
        "• `/bulatkan` - Bulatkan saldo\n"
        "• `/cek [nama]` - Cek saldo\n"
        "• `/reset` - Reset data (admin)",
        parse_mode='Markdown'
    )

async def rekap_cek(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Balas ke pesan data duel!")
        return
    
    data = parse_duel_data(update.message.reply_to_message.text)
    k_vals = [p['modal'] for p in data["KECIL"]]
    b_vals = [p['modal'] for p in data["BESAR"]]
    sum_k, sum_b = sum(k_vals), sum(b_vals)
    
    msg = f"🔵 KECIL: {k_vals} = {sum_k}\n🔴 BESAR: {b_vals} = {sum_b}\n\n"
    
    if sum_k == sum_b:
        msg += "✅ NOMINAL SAMA!"
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
        try: 
            fee = float(context.args[0])
        except: 
            pass
    
    data = parse_duel_data(update.message.reply_to_message.text)
    context.user_data['active_duel'] = {'data': data, 'fee': fee}
    
    keyboard = [
        [InlineKeyboardButton("🔵 KECIL", callback_data="KECIL"),
         InlineKeyboardButton("🔴 BESAR", callback_data="BESAR")]
    ]
    await update.message.reply_text(
        f"💰 Fee: {fee}%\n🏆 Pilih pemenang:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    chat_id = query.message.chat_id
    rekap = context.user_data.get('active_duel')
    
    if not rekap:
        await query.edit_message_text("❌ Session expired! Ulangi /rekapwin")
        return
    
    if query.data in ["KECIL", "BESAR"]:
        winner = query.data
        rekap['winner'] = winner
        keyboard = [
            [InlineKeyboardButton("2-0", callback_data=f"2-0_{winner}"),
             InlineKeyboardButton("2-1", callback_data=f"2-1_{winner}")]
        ]
        await query.edit_message_text(f"🎯 Pilih skor:", reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif query.data.startswith("2-0") or query.data.startswith("2-1"):
        score, winner = query.data.split('_')
        skor_simpan = score.replace("-", "")
        
        # Proses saldo untuk pemenang
        for p in rekap['data'][winner]:
            hasil_win = hitung_setelah_fee(p['modal'], rekap['fee'])
            
            if p['name'] in players_db:
                players_db[p['name']] = players_db[p['name']] + hasil_win
            else:
                players_db[p['name']] = hasil_win
        
        # Game number
        game_num = settings_db.get(chat_id, 1)
        
        # Save history
        total_modal = sum(p['modal'] for p in rekap['data'][winner])
        if chat_id not in history_db:
            history_db[chat_id] = []
        history_db[chat_id].append(f"GAME {game_num} : {winner[0]} {skor_simpan} {total_modal}")
        
        # Update game number
        settings_db[chat_id] = game_num + 1
        
        # Format output
        hist_text = "\n".join(history_db.get(chat_id, [])[-5:])  # 5 game terakhir
        
        saldo_lines = []
        total_saldo = 0
        for name, bal in players_db.items():
            total_saldo += bal
            saldo_lines.append(f"{name} {bal}")
        
        admin = f"(@{query.from_user.username})" if query.from_user.username else "(User)"
        
        output = f"DEV: VERCEL\nROL: BOT\n\nLAST WIN : {admin}\n{hist_text}\n\nSALDO PEMAIN : ({total_saldo})\n" + "\n".join(saldo_lines)
        
        await query.edit_message_text(output)
        del context.user_data['active_duel']

async def cek_saldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if context.args:
        name = context.args[0].upper()
        if name in players_db:
            await update.message.reply_text(f"💰 {name}: {players_db[name]}")
        else:
            await update.message.reply_text(f"❌ {name} tidak ditemukan")
    else:
        if not players_db:
            await update.message.reply_text("📭 Belum ada data saldo")
            return
        
        lines = [f"{name}: {bal}" for name, bal in players_db.items()]
        total = sum(players_db.values())
        msg = f"💰 TOTAL SALDO: {total}\n\n" + "\n".join(lines)
        await update.message.reply_text(msg)

async def bulatkan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not players_db:
        await update.message.reply_text("❌ Belum ada data player!")
        return
    
    for name in list(players_db.keys()):
        bal = players_db[name]
        bal_baru = bulatkan_ke_bawah(bal)
        if bal_baru == 0:
            del players_db[name]
        else:
            players_db[name] = bal_baru
    
    await update.message.reply_text("✅ Saldo dibulatkan ke bawah (kelipatan 100)")

# ==================== SETUP HANDLERS ====================
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("rekap", rekap_cek))
application.add_handler(CommandHandler("rekapwin", rekapwin))
application.add_handler(CommandHandler("cek", cek_saldo))
application.add_handler(CommandHandler("bulatkan", bulatkan))
application.add_handler(CallbackQueryHandler(callback_handler))

# ==================== FLASK APP ====================
app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        logger.info(f"Webhook received: {data}")
        
        # Convert to Update object and process
        update = Update.de_json(data, application.bot)
        
        # Process update (run in sync way for Flask)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(application.process_update(update))
        loop.close()
        
        return jsonify({"status": "ok"})
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 200

@app.route('/health')
def health():
    return jsonify({
        "status": "running",
        "time": str(datetime.now()),
        "players": len(players_db),
        "bot_token_valid": bool(TOKEN)
    })

@app.route('/')
def home():
    return jsonify({
        "status": "Bot Rekapwin Vercel",
        "version": "2.0",
        "players": len(players_db),
        "commands": ["/start", "/rekap", "/rekapwin", "/cek", "/bulatkan"]
    })

@app.route('/setwebhook')
def set_webhook():
    url = f"https://api.telegram.org/bot{TOKEN}/setWebhook?url={WEBHOOK_URL}"
    response = requests.get(url)
    return jsonify(response.json())

# For local testing
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
