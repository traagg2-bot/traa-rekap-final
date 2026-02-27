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
TOKEN = os.environ.get("BOT_TOKEN", "8708452430:AAENurTtTwMSZLPAz9rOLrR6GtnNxvg2GaI")
OWNER_ID = int(os.environ.get("OWNER_ID", "6882937271"))
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "https://traa-rekap-final.vercel.app/webhook")

# === LOGGING ===
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# === DATABASE (In-Memory) ===
players_db = {}        # { "NAMA": balance }
history_db = {}        # { chat_id: [game1, game2, ...] }
settings_db = {}       # { chat_id: game_num }
transactions_db = []   # List of transactions

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

def format_rupiah(angka):
    """Format angka ke Rupiah"""
    return f"Rp {angka:,}".replace(",", ".")

# ==================== COMMAND HANDLERS ====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /start"""
    await update.message.reply_text(
        "🤖 *REKAPWIN BOT VERCEL*\n\n"
        "📌 *Commands Utama:*\n"
        "• `/rekap` - Cek kesamaan nominal\n"
        "• `/rekapwin [fee]` - Hitung kemenangan\n"
        "• `/bulatkan` - Bulatkan semua saldo\n\n"
        
        "💰 *Manajemen Saldo:*\n"
        "• `/tambah [nama] [jumlah]` - Tambah saldo\n"
        "• `/kurang [nama] [jumlah]` - Kurangi saldo\n"
        "• `/cek [nama]` - Cek saldo pemain\n"
        "• `/lunas [nama]` - Lunasi hutang\n\n"
        
        "📝 *Edit History:*\n"
        "• `/resetlw` - Reset history game\n"
        "• `/m1only [skor]` - Edit skor game terakhir\n\n"
        
        "⚙️ *Lainnya:*\n"
        "• `/reset` - Reset semua data (admin only)",
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
    
    # Parse fee
    fee = 5.5
    if context.args:
        try: 
            fee = float(context.args[0])
        except: 
            pass
    
    data = parse_duel_data(update.message.reply_to_message.text)
    
    if not data["KECIL"] or not data["BESAR"]:
        await update.message.reply_text(
            "❌ *Format salah!*\n\n"
            "Gunakan:\n"
            "`KECIL:`\n"
            "`NAMA MODAL`\n"
            "`BESAR:`\n"
            "`NAMA MODAL`",
            parse_mode='Markdown'
        )
        return
    
    context.user_data['active_duel'] = {'data': data, 'fee': fee, 'chat_id': update.effective_chat.id}
    
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
    
    chat_id = query.message.chat_id
    rekap = context.user_data.get('active_duel')
    
    if not rekap:
        await query.edit_message_text("❌ *Session expired!* Ulangi /rekapwin", parse_mode='Markdown')
        return
    
    # ===== HANDLE PILIHAN WINNER =====
    if query.data in ["KECIL", "BESAR"]:
        winner = query.data
        rekap['winner'] = winner
        
        keyboard = [
            [InlineKeyboardButton("2-0", callback_data=f"2-0_{winner}"),
             InlineKeyboardButton("2-1", callback_data=f"2-1_{winner}")]
        ]
        await query.edit_message_text(
            f"🎯 *Pilih skor untuk {winner}:*",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    # ===== HANDLE PILIHAN SKOR =====
    elif query.data.startswith("2-0") or query.data.startswith("2-1"):
        try:
            score, winner = query.data.split('_')
            skor_simpan = score.replace("-", "")
            loser = "BESAR" if winner == "KECIL" else "KECIL"
            
            # ===== PROSES SALDO UNTUK PEMENANG =====
            for p in rekap['data'][winner]:
                hasil_win = hitung_setelah_fee(p['modal'], rekap['fee'])
                
                if p['name'] in players_db:
                    players_db[p['name']] += hasil_win
                else:
                    players_db[p['name']] = hasil_win
                
                # Catat transaksi
                transactions_db.append({
                    'chat_id': chat_id,
                    'username': p['name'],
                    'amount': hasil_win,
                    'type': 'win',
                    'admin': query.from_user.username or query.from_user.first_name,
                    'time': str(datetime.now())
                })
            
            # ===== YANG KALAH DIHAPUS (GAK USAH DICATAT) =====
            # Kalah ya udah, gak usah masuk DB
            
            # ===== GAME NUMBER =====
            game_num = settings_db.get(chat_id, 1)
            
            # ===== SAVE HISTORY =====
            total_modal = sum(p['modal'] for p in rekap['data'][winner])
            game_text = f"GAME {game_num} : {winner[0]} {skor_simpan} {total_modal}"
            
            if chat_id not in history_db:
                history_db[chat_id] = []
            history_db[chat_id].append(game_text)
            
            # ===== UPDATE GAME NUMBER =====
            settings_db[chat_id] = game_num + 1
            
            # ===== FORMAT OUTPUT =====
            # History (5 game terakhir)
            hist_list = history_db.get(chat_id, [])[-5:]
            hist_text = "\n".join(hist_list) if hist_list else "Belum ada game"
            
            # Saldo pemain
            saldo_lines = []
            total_saldo = 0
            for name, bal in sorted(players_db.items(), key=lambda x: x[1], reverse=True):
                if bal != 0:
                    total_saldo += bal
                    if bal > 0:
                        saldo_lines.append(f"{name} {bal}")
                    else:
                        saldo_lines.append(f"{name} - {abs(bal)}")
            
            # Admin
            admin = f"(@{query.from_user.username})" if query.from_user.username else f"({query.from_user.first_name})"
            
            # Output final
            output = (
                f"DEV: VERCEL\n"
                f"ROL: BOT\n\n"
                f"LAST WIN : {admin}\n"
                f"{hist_text}\n\n"
                f"SALDO PEMAIN : ({total_saldo})\n"
                f"{chr(10).join(saldo_lines)}"
            )
            
            await query.edit_message_text(output)
            
            # Hapus session
            del context.user_data['active_duel']
            
        except Exception as e:
            logger.error(f"Error in callback: {e}")
            await query.edit_message_text(f"❌ *Error:* {str(e)}", parse_mode='Markdown')

async def cek_saldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /cek - cek saldo pemain"""
    if context.args:
        name = context.args[0].upper()
        if name in players_db:
            bal = players_db[name]
            if bal >= 0:
                await update.message.reply_text(f"💰 *{name}:* {bal}", parse_mode='Markdown')
            else:
                await update.message.reply_text(f"💸 *{name}:* HUTANG {abs(bal)}", parse_mode='Markdown')
        else:
            await update.message.reply_text(f"❌ *{name}* tidak ditemukan", parse_mode='Markdown')
    else:
        if not players_db:
            await update.message.reply_text("📭 *Belum ada data saldo*", parse_mode='Markdown')
            return
        
        lines = []
        total = 0
        for name, bal in sorted(players_db.items(), key=lambda x: x[1], reverse=True):
            total += bal
            if bal >= 0:
                lines.append(f"{name}: {bal}")
            else:
                lines.append(f"{name}: HUTANG {abs(bal)}")
        
        msg = f"💰 *TOTAL SALDO:* {total}\n\n" + "\n".join(lines)
        await update.message.reply_text(msg, parse_mode='Markdown')

async def tambah_saldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /tambah - tambah saldo pemain"""
    if len(context.args) < 2:
        await update.message.reply_text("❌ *Format:* /tambah [nama] [jumlah]", parse_mode='Markdown')
        return
    
    name = context.args[0].upper()
    try:
        jumlah = int(context.args[1])
    except:
        await update.message.reply_text("❌ *Jumlah harus angka!*", parse_mode='Markdown')
        return
    
    if name in players_db:
        players_db[name] += jumlah
    else:
        players_db[name] = jumlah
    
    # Catat transaksi
    transactions_db.append({
        'chat_id': update.effective_chat.id,
        'username': name,
        'amount': jumlah,
        'type': 'tambah',
        'admin': update.effective_user.username or update.effective_user.first_name,
        'time': str(datetime.now())
    })
    
    await update.message.reply_text(f"✅ *Saldo {name} bertambah {jumlah}*", parse_mode='Markdown')

async def kurang_saldo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /kurang - kurangi saldo pemain"""
    if len(context.args) < 2:
        await update.message.reply_text("❌ *Format:* /kurang [nama] [jumlah]", parse_mode='Markdown')
        return
    
    name = context.args[0].upper()
    try:
        jumlah = int(context.args[1])
    except:
        await update.message.reply_text("❌ *Jumlah harus angka!*", parse_mode='Markdown')
        return
    
    if name not in players_db:
        await update.message.reply_text(f"❌ *{name}* tidak ditemukan", parse_mode='Markdown')
        return
    
    players_db[name] -= jumlah
    
    # Hapus kalo saldo 0
    if players_db[name] == 0:
        del players_db[name]
    
    # Catat transaksi
    transactions_db.append({
        'chat_id': update.effective_chat.id,
        'username': name,
        'amount': jumlah,
        'type': 'kurang',
        'admin': update.effective_user.username or update.effective_user.first_name,
        'time': str(datetime.now())
    })
    
    await update.message.reply_text(f"✅ *Saldo {name} berkurang {jumlah}*", parse_mode='Markdown')

async def lunas(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /lunas - lunasi hutang"""
    if not context.args:
        await update.message.reply_text("❌ *Format:* /lunas [nama]", parse_mode='Markdown')
        return
    
    name = context.args[0].upper()
    
    if name not in players_db:
        await update.message.reply_text(f"❌ *{name}* tidak ditemukan", parse_mode='Markdown')
        return
    
    if players_db[name] >= 0:
        await update.message.reply_text(f"❌ *{name}* tidak punya hutang (saldo: {players_db[name]})", parse_mode='Markdown')
        return
    
    hutang = abs(players_db[name])
    del players_db[name]
    
    await update.message.reply_text(f"✅ *Hutang {name} sebesar {hutang} telah dilunasi*", parse_mode='Markdown')

async def bulatkan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /bulatkan - bulatkan semua saldo"""
    if not players_db:
        await update.message.reply_text("❌ *Belum ada data player!*", parse_mode='Markdown')
        return
    
    total_bulat = 0
    for name in list(players_db.keys()):
        bal = players_db[name]
        bal_baru = bulatkan_ke_bawah(bal)
        
        if bal_baru == 0:
            del players_db[name]
        else:
            players_db[name] = bal_baru
        total_bulat += 1
    
    await update.message.reply_text(f"✅ *{total_bulat} player dibulatkan ke bawah (kelipatan 100)*", parse_mode='Markdown')

async def resetlw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /resetlw - reset history game"""
    chat_id = update.effective_chat.id
    
    if chat_id in history_db:
        history_db[chat_id] = []
    
    settings_db[chat_id] = 1
    
    await update.message.reply_text("✅ *History game direset! Game dimulai dari 1*", parse_mode='Markdown')

async def m1only(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /m1only - edit skor game terakhir"""
    if not context.args:
        await update.message.reply_text("❌ *Format:* /m1only [skor] (contoh: /m1only 2737)", parse_mode='Markdown')
        return
    
    skor_baru = context.args[0]
    chat_id = update.effective_chat.id
    
    if chat_id not in history_db or not history_db[chat_id]:
        await update.message.reply_text("❌ *Belum ada history game*", parse_mode='Markdown')
        return
    
    # Ambil game terakhir
    last_game = history_db[chat_id][-1]
    
    # Parse dan ganti skor
    match = re.search(r'(GAME \d+ : [A-Z]+ )\d+', last_game)
    if match:
        prefix = match.group(1)
        new_game = f"{prefix}{skor_baru}"
        history_db[chat_id][-1] = new_game
        await update.message.reply_text(f"✅ *Skor game terakhir diubah ke {skor_baru}*", parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ *Format game text tidak valid*", parse_mode='Markdown')

async def reset_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handler untuk /reset - reset semua data (admin only)"""
    user_id = update.effective_user.id
    
    if user_id != OWNER_ID:
        await update.message.reply_text("❌ *Hanya owner yang bisa reset!*", parse_mode='Markdown')
        return
    
    players_db.clear()
    history_db.clear()
    settings_db.clear()
    transactions_db.clear()
    
    await update.message.reply_text("✅ *Semua data direset!*", parse_mode='Markdown')

# ==================== SETUP HANDLERS ====================
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("rekap", rekap_cek))
application.add_handler(CommandHandler("rekapwin", rekapwin))
application.add_handler(CommandHandler("cek", cek_saldo))
application.add_handler(CommandHandler("tambah", tambah_saldo))
application.add_handler(CommandHandler("kurang", kurang_saldo))
application.add_handler(CommandHandler("lunas", lunas))
application.add_handler(CommandHandler("bulatkan", bulatkan))
application.add_handler(CommandHandler("resetlw", resetlw))
application.add_handler(CommandHandler("m1only", m1only))
application.add_handler(CommandHandler("reset", reset_all))
application.add_handler(CallbackQueryHandler(callback_handler))

# ==================== FLASK APP ====================
app = Flask(__name__)

@app.route('/webhook', methods=['POST'])
def webhook():
    """Handle webhook dari Telegram"""
    try:
        data = request.get_json()
        logger.info(f"Webhook received: {data}")
        
        if data:
            # Convert ke Update object
            update = Update.de_json(data, application.bot)
            
            # Process update
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(application.process_update(update))
            loop.close()
        
        return jsonify({"status": "ok"})
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 200

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "running",
        "time": str(datetime.now()),
        "players": len(players_db),
        "games": sum(len(v) for v in history_db.values()),
        "bot_token_valid": bool(TOKEN)
    })

@app.route('/', methods=['GET'])
def home():
    """Home endpoint"""
    return jsonify({
        "status": "Bot Rekapwin Vercel",
        "version": "3.0 - FULL",
        "players": len(players_db),
        "commands": [
            "/start", "/rekap", "/rekapwin", "/cek", 
            "/tambah", "/kurang", "/lunas", "/bulatkan",
            "/resetlw", "/m1only", "/reset"
        ]
    })

@app.route('/setwebhook', methods=['GET'])
def set_webhook():
    """Set webhook untuk bot"""
    url = f"https://api.telegram.org/bot{TOKEN}/setWebhook?url={WEBHOOK_URL}"
    response = requests.get(url)
    return jsonify(response.json())

@app.route('/debug', methods=['GET'])
def debug():
    """Debug endpoint - lihat data"""
    return jsonify({
        "players": players_db,
        "history": {str(k): v for k, v in history_db.items()},
        "settings": settings_db,
        "transactions": transactions_db[-10:]  # 10 transaksi terakhir
    })

# For local testing
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))
