from flask import Flask, request, jsonify
import os
import sys
from datetime import datetime
import requests
import logging
import re
import json
import math
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters

# === CONFIG ===
TOKEN = "8708452430:AAENurTtTwMSZLPAz9rOLrR6GtnNxvg2GaI"
OWNER_ID = 6882937271
WEBHOOK_URL = "https://traa-rekap-final.vercel.app/webhook"

# === LOGGING ===
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# === DATABASE (In-Memory) ===
players_db = {}        # { "NAMA": balance }
history_db = {}        # { chat_id: [game1, game2, ...] }
settings_db = {}       # { chat_id: game_num }

# === BOT APPLICATION ===
application = Application.builder().token(TOKEN).build()

# ==================== HELPER FUNCTIONS ====================
def parse_duel_data(text):
    """Parse data duel dari pesan"""
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
    """Hitung kemenangan setelah dipotong fee"""
    hasil_kotor = modal * 2
    potongan = math.ceil(hasil_kotor * (fee_persen / 100))
    return hasil_kotor - potongan

def bulatkan_ke_bawah(angka):
    """Bulatkan ke kelipatan 100 ke bawah"""
    if angka >= 0:
        return (angka // 100) * 100
    else:
        return -((abs(angka) + 99) // 100 * 100)

# ==================== COMMAND HANDLERS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /start"""
    await update.message.reply_text(
        "🤖 *REKAPWIN BOT VERCEL*\n\n"
        "📌 *Commands:*\n"
        "• `/rekap` - Cek nominal\n"
        "• `/rekapwin [fee]` - Hitung kemenangan\n"
        "• `/cek [nama]` - Cek saldo\n"
        "• `/tambah [nama] [jumlah]` - Tambah saldo\n"
        "• `/bulatkan` - Bulatkan saldo\n"
        "• `/reset` - Reset data (owner)",
        parse_mode='Markdown'
    )

async def rekap_cek(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /rekap - cek kesamaan nominal"""
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ *Balas ke pesan data duel!*", parse_mode='Markdown')
        return
    
    data = parse_duel_data(update.message.reply_to_message.text)
    k_vals = [p['modal'] for p in data["KECIL"]]
    b_vals = [p['modal'] for p in data["BESAR"]]
    sum_k, sum_b = sum(k_vals), sum(b_vals)
    
    msg = f"🔵 *KECIL:* {k_vals} = {sum_k}\n🔴 *BESAR:* {b_vals} = {sum_b}\n\n"
    
    if sum_k == sum_b:
        msg += "✅ *NOMINAL SAMA!*"
    else:
        diff = abs(sum_k - sum_b)
        kurang = "KECIL" if sum_k < sum_b else "BESAR"
        msg += f"⚠️ *{kurang} KURANG {diff}*"
    
    await update.message.reply_text(msg, parse_mode='Markdown')

async def rekapwin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /rekapwin - hitung kemenangan"""
    if not update.message.reply_to_message:
        await update.message.reply_text("❌ *Balas ke pesan data duel!*", parse_mode='Markdown')
        return
    
    fee = 5.5
    if context.args:
        try: fee = float(context.args[0])
        except: pass
    
    data = parse_duel_data(update.message.reply_to_message.text)
    
    if not data["KECIL"] or not data["BESAR"]:
        await update.message.reply_text("❌ *Format salah!*", parse_mode='Markdown')
        return
    
    context.user_data['active_duel'] = {'data': data, 'fee': fee}
    
    keyboard = [
        [InlineKeyboardButton("🔵 KECIL", callback_data="KECIL"),
         InlineKeyboardButton("🔴 BESAR", callback_data="BESAR")]
    ]
    await update.message.reply_text(
        f"💰 *Fee:* {fee}%\n🏆 *Pilih pemenang:*",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk callback buttons"""
    query = update.callback_query
    await query.answer()
    
    rekap = context.user_data.get('active_duel')
    if not rekap:
        await query.edit_message_text("❌ *Session expired!*", parse_mode='Markdown')
        return
    
    if query.data in ["KECIL", "BESAR"]:
        winner = query.data
        rekap['winner'] = winner
        keyboard = [
            [InlineKeyboardButton("2-0", callback_data=f"2-0_{winner}"),
             InlineKeyboardButton("2-1", callback_data=f"2-1_{winner}")]
        ]
        await query.edit_message_text(f"🎯 *Pilih skor:*", reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif query.data.startswith("2-0") or query.data.startswith("2-1"):
        score, winner = query.data.split('_')
        skor_simpan = score.replace("-", "")
        
        # Proses saldo
        for p in rekap['data'][winner]:
            hasil_win = hitung_setelah_fee(p['modal'], rekap['fee'])
            if p['name'] in players_db:
                players_db[p['name']] += hasil_win
            else:
                players_db[p['name']] = hasil_win
        
        await query.edit_message_text(f"✅ *Game selesai!*\n{winner} menang {score}")
        del context.user_data['active_duel']

async def cek_saldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /cek - cek saldo"""
    if context.args:
        name = context.args[0].upper()
        if name in players_db:
            await update.message.reply_text(f"💰 *{name}:* {players_db[name]}", parse_mode='Markdown')
        else:
            await update.message.reply_text(f"❌ *{name}* tidak ditemukan", parse_mode='Markdown')
    else:
        if not players_db:
            await update.message.reply_text("📭 *Belum ada data*", parse_mode='Markdown')
            return
        msg = "\n".join([f"{n}: {b}" for n, b in players_db.items()])
        await update.message.reply_text(f"💰 *Saldo:*\n{msg}", parse_mode='Markdown')

async def tambah_saldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /tambah"""
    if len(context.args) < 2:
        await update.message.reply_text("❌ *Format:* /tambah [nama] [jumlah]", parse_mode='Markdown')
        return
    name = context.args[0].upper()
    try:
        jumlah = int(context.args[1])
        players_db[name] = players_db.get(name, 0) + jumlah
        await update.message.reply_text(f"✅ *Saldo {name} +{jumlah}*", parse_mode='Markdown')
    except:
        await update.message.reply_text("❌ *Jumlah harus angka!*", parse_mode='Markdown')

async def bulatkan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /bulatkan"""
    for name in list(players_db.keys()):
        players_db[name] = bulatkan_ke_bawah(players_db[name])
        if players_db[name] == 0:
            del players_db[name]
    await update.message.reply_text("✅ *Saldo dibulatkan*", parse_mode='Markdown')

async def reset_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /reset"""
    if update.effective_user.id != OWNER_ID:
        await update.message.reply_text("❌ *Hanya owner!*", parse_mode='Markdown')
        return
    players_db.clear()
    history_db.clear()
    settings_db.clear()
    await update.message.reply_text("✅ *Semua data direset!*", parse_mode='Markdown')

# ==================== SETUP HANDLERS ====================
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("rekap", rekap_cek))
application.add_handler(CommandHandler("rekapwin", rekapwin))
application.add_handler(CommandHandler("cek", cek_saldo))
application.add_handler(CommandHandler("tambah", tambah_saldo))
application.add_handler(CommandHandler("bulatkan", bulatkan))
application.add_handler(CommandHandler("reset", reset_all))
application.add_handler(CallbackQueryHandler(callback_handler))

# ==================== FLASK APP ====================
app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        logger.info(f"Webhook: {data}")
        
        if data:
            update = Update.de_json(data, application.bot)
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(application.process_update(update))
            loop.close()
        
        return jsonify({"ok": True})
    except Exception as e:
        logger.error(f"Error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 200

@app.route('/health')
def health():
    return jsonify({"status": "ok", "players": len(players_db)})

@app.route('/setwebhook')
def set_webhook():
    url = f"https://api.telegram.org/bot{TOKEN}/setWebhook?url={WEBHOOK_URL}"
    r = requests.get(url)
    return jsonify(r.json())
