import logging
import sqlite3
import re
import requests
import os
from datetime import datetime, timedelta
import json
import math
import uuid
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, ContextTypes, CallbackQueryHandler, MessageHandler, filters

# === CONFIG ===
TOKEN = os.environ.get("BOT_TOKEN", "YOUR_TOKEN_HERE")
OWNER_ID = int(os.environ.get("OWNER_ID", "6882937271"))
PAKASIR_API_KEY = "85t2Q8XQTti5aUG4TbgBOzFOTlGSLt5U"
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "https://bot-rekap-final.vercel.app/webhook")
ADMIN_USERNAME = "your_telegram_username"  # Ganti dengan username lu

# === DATABASE ===
def db_query(query, params=(), fetchone=False, fetchall=False):
    conn = sqlite3.connect('rekapwin.db')
    c = conn.cursor()
    c.execute(query, params)
    if fetchone: 
        res = c.fetchone()
    elif fetchall: 
        res = c.fetchall()
    else: 
        res = None
    conn.commit()
    conn.close()
    return res

def init_db():
    db_query('''CREATE TABLE IF NOT EXISTS players (
        username TEXT PRIMARY KEY, 
        balance INTEGER DEFAULT 0
    )''')
    db_query('''CREATE TABLE IF NOT EXISTS game_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        chat_id INTEGER, 
        game_text TEXT
    )''')
    db_query('''CREATE TABLE IF NOT EXISTS settings (
        chat_id INTEGER PRIMARY KEY, 
        game_num INTEGER DEFAULT 1
    )''')
    db_query('''CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id INTEGER,
        username TEXT,
        amount INTEGER,
        type TEXT,
        admin TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    db_query('''CREATE TABLE IF NOT EXISTS premium_groups (
        chat_id INTEGER PRIMARY KEY,
        expires_at DATETIME,
        added_by INTEGER
    )''')
    db_query('''CREATE TABLE IF NOT EXISTS payments (
        id TEXT PRIMARY KEY,
        user_id INTEGER,
        chat_id INTEGER,
        days INTEGER,
        amount INTEGER,
        status TEXT DEFAULT 'pending',
        payment_url TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    db_query('''CREATE TABLE IF NOT EXISTS group_admins (
        chat_id INTEGER,
        admin_id INTEGER,
        PRIMARY KEY (chat_id, admin_id)
    )''')
    db_query('''CREATE TABLE IF NOT EXISTS temp_chat (
        user_id INTEGER PRIMARY KEY,
        chat_id INTEGER
    )''')

init_db()

# === PAKASIR API ===
def create_pakasir_qris(amount, order_id):
    """Buat QRIS via pakasir.com"""
    url = "https://api.pakasir.com/v1/create-qris"
    headers = {
        "api-key": PAKASIR_API_KEY,
        "Content-Type": "application/json"
    }
    data = {
        "order_id": order_id,
        "amount": amount,
        "customer_name": "Rekapwin User",
        "customer_email": "user@example.com",
        "expiry_minutes": 60
    }
    
    try:
        response = requests.post(url, json=data, headers=headers)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"PAKASIR ERROR: {response.text}")
            return None
    except Exception as e:
        print(f"PAKASIR EXCEPTION: {e}")
        return None

def check_payment_status(order_id):
    """Cek status pembayaran"""
    url = f"https://api.pakasir.com/v1/check-status/{order_id}"
    headers = {"api-key": PAKASIR_API_KEY}
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 200:
            return response.json()
        return None
    except:
        return None

# === HELPER FUNCTIONS ===
async def get_info_from_pin(update, context):
    dev, rol = "REDMI 14C", "CHROME"
    try:
        chat = await context.bot.get_chat(update.effective_chat.id)
        if chat.pinned_message and chat.pinned_message.text:
            text = chat.pinned_message.text.upper()
            match_dev = re.search(r"DEV\s*:\s*(.*)", text)
            if match_dev: 
                dev = match_dev.group(1).strip()
            match_rol = re.search(r"ROL\s*:\s*(.*)", text)
            if match_rol: 
                rol = match_rol.group(1).strip()
    except: 
        pass
    return dev, rol

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

async def update_pinned_message(update, context, chat_id):
    dev, rol = await get_info_from_pin(update, context)
    history = db_query("SELECT game_text FROM game_history WHERE chat_id=? ORDER BY id DESC LIMIT 10", (chat_id,), fetchall=True)
    history.reverse()
    hist_text = "\n".join([h[0] for h in history]) if history else "Belum ada game"
    players = db_query("SELECT username, balance FROM players WHERE balance != 0 ORDER BY balance DESC", fetchall=True)
    saldo_lines = []
    total_saldo = 0
    for p in players:
        name, bal = p
        total_saldo += bal
        saldo_lines.append(f"{name} {bal}")
    last_admin = db_query("SELECT admin FROM transactions WHERE chat_id=? ORDER BY id DESC LIMIT 1", (chat_id,), fetchone=True)
    admin = f"(@{last_admin[0]})" if last_admin else "(System)"
    output = f"DEV: {dev}\nROL: {rol}\n\nLAST WIN : {admin}\n{hist_text}\n\nSALDO PEMAIN : ({total_saldo})\n" + "\n".join(saldo_lines)
    try:
        chat = await context.bot.get_chat(chat_id)
        if chat.pinned_message:
            await context.bot.unpin_chat_message(chat_id, chat.pinned_message.message_id)
        msg = await context.bot.send_message(chat_id, output)
        await context.bot.pin_chat_message(chat_id, msg.message_id)
    except:
        pass

def is_group_premium(chat_id):
    cek = db_query("SELECT expires_at FROM premium_groups WHERE chat_id=? AND expires_at > datetime('now')", (chat_id,), fetchone=True)
    return cek is not None

def is_group_admin(chat_id, user_id):
    cek = db_query("SELECT admin_id FROM group_admins WHERE chat_id=? AND admin_id=?", (chat_id, user_id), fetchone=True)
    return cek is not None or user_id == OWNER_ID

# ===== HANDLERS =====
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 REKAPWIN BOT\n\n"
        "Untuk menggunakan bot, tambahkan ke grup dan jadikan admin.\n\n"
        "Commands:\n"
        "/rekap - Cek nominal\n"
        "/rekapwin [fee] - Hitung kemenangan\n"
        "/bulatkan - Bulatkan semua saldo"
    )

async def private_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle pesan di private chat"""
    keyboard = [
        [InlineKeyboardButton("📅 Sewa Harian (5k/hari)", callback_data="sewa_harian")],
        [InlineKeyboardButton("📆 Sewa Mingguan (25k/minggu)", callback_data="sewa_mingguan")]
    ]
    await update.message.reply_text(
        "🤖 *MAU SEWA BOT REKAP ON 24/7?*\n\n"
        "Pilih paket:\n"
        "• Harian: Rp 5.000/hari\n"
        "• Mingguan: Rp 25.000/minggu\n\n"
        "✅ Pembayaran otomatis via QRIS",
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "sewa_harian":
        context.user_data['sewa_tipe'] = 'harian'
        context.user_data['harga_per_hari'] = 5000
        await query.edit_message_text(
            "📝 *SEWA HARIAN*\n\n"
            "Ketik jumlah hari (min 1, max 30):",
            parse_mode='Markdown'
        )
        context.user_data['state'] = 'waiting_days'
    
    elif query.data == "sewa_mingguan":
        context.user_data['sewa_tipe'] = 'mingguan'
        context.user_data['harga_per_minggu'] = 25000
        await query.edit_message_text(
            "📝 *SEWA MINGGUAN*\n\n"
            "Ketik jumlah minggu (min 1, max 4):",
            parse_mode='Markdown'
        )
        context.user_data['state'] = 'waiting_weeks'
    
    elif query.data.startswith("cek_payment_"):
        payment_id = query.data.replace("cek_payment_", "")
        payment = db_query("SELECT * FROM payments WHERE id=?", (payment_id,), fetchone=True)
        
        if payment:
            status = check_payment_status(payment_id)
            if status and status.get('status') == 'paid':
                db_query("UPDATE payments SET status='paid' WHERE id=?", (payment_id,))
                
                # Aktivasi premium
                chat_id = payment[2]  # chat_id
                days = payment[3]      # days
                expires = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
                db_query("INSERT OR REPLACE INTO premium_groups (chat_id, expires_at, added_by) VALUES (?, ?, ?)",
                        (chat_id, expires, payment[1]))
                
                await query.edit_message_text(
                    f"✅ *PEMBAYARAN BERHASIL!*\n\n"
                    f"Grup dengan ID {chat_id} sekarang PREMIUM selama {days} hari!\n\n"
                    f"Tambahkan bot ke grup dan jadikan admin.",
                    parse_mode='Markdown'
                )
            else:
                keyboard = [[InlineKeyboardButton("🔄 CEK LAGI", callback_data=f"cek_payment_{payment_id}")]]
                await query.edit_message_text(
                    "⏳ Pembayaran belum diterima.\n\nSilahkan scan QRIS dan lakukan pembayaran.\n\nKlik tombol di bawah setelah transfer.",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )

async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if context.user_data.get('state') == 'waiting_days':
        try:
            days = int(update.message.text)
            if days < 1 or days > 30:
                await update.message.reply_text("❌ Jumlah hari harus 1-30!")
                return
            
            total = days * 5000
            order_id = f"REKAP_{user_id}_{int(datetime.now().timestamp())}"
            
            # Simpan chat_id (nanti user akan input grup ID)
            await update.message.reply_text(
                "📢 *MASUKKAN ID GRUP*\n\n"
                "Kirimkan ID grup yang ingin diaktifkan premium.\n\n"
                "Cara dapat ID grup:\n"
                "1. Tambahkan @getidsbot ke grup\n"
                "2. Ketik /id\n"
                "3. Copy angka ID-nya",
                parse_mode='Markdown'
            )
            context.user_data['state'] = 'waiting_chat_id'
            context.user_data['days'] = days
            context.user_data['total'] = total
            context.user_data['order_id'] = order_id
            
        except ValueError:
            await update.message.reply_text("❌ Masukkan angka yang valid!")
    
    elif context.user_data.get('state') == 'waiting_weeks':
        try:
            weeks = int(update.message.text)
            if weeks < 1 or weeks > 4:
                await update.message.reply_text("❌ Jumlah minggu harus 1-4!")
                return
            
            total = weeks * 25000
            days = weeks * 7
            order_id = f"REKAP_{user_id}_{int(datetime.now().timestamp())}"
            
            await update.message.reply_text(
                "📢 *MASUKKAN ID GRUP*\n\n"
                "Kirimkan ID grup yang ingin diaktifkan premium.",
                parse_mode='Markdown'
            )
            context.user_data['state'] = 'waiting_chat_id'
            context.user_data['days'] = days
            context.user_data['total'] = total
            context.user_data['order_id'] = order_id
            
        except ValueError:
            await update.message.reply_text("❌ Masukkan angka yang valid!")
    
    elif context.user_data.get('state') == 'waiting_chat_id':
        try:
            chat_id = int(update.message.text)
            
            # Buat payment via pakasir
            payment_result = create_pakasir_qris(context.user_data['total'], context.user_data['order_id'])
            
            if payment_result and payment_result.get('qr_url'):
                # Simpan ke database
                db_query("INSERT INTO payments (id, user_id, chat_id, days, amount, payment_url, status) VALUES (?, ?, ?, ?, ?, ?, 'pending')",
                        (context.user_data['order_id'], user_id, chat_id, context.user_data['days'], context.user_data['total'], payment_result['qr_url']))
                
                # Tampilkan QRIS
                keyboard = [[InlineKeyboardButton("✅ CEK PEMBAYARAN", callback_data=f"cek_payment_{context.user_data['order_id']}")]]
                
                await update.message.reply_photo(
                    photo=payment_result['qr_url'],
                    caption=f"💳 *PEMBAYARAN QRIS*\n\n"
                            f"Total: Rp {context.user_data['total']:,}\n"
                            f"Durasi: {context.user_data['days']} hari\n"
                            f"Grup ID: {chat_id}\n\n"
                            f"Scan QRIS untuk membayar.\n"
                            f"Klik tombol di bawah setelah transfer!",
                    parse_mode='Markdown',
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                await update.message.reply_text("❌ Gagal membuat QRIS. Silahkan coba lagi atau hubungi admin.")
            
            context.user_data['state'] = None
            
        except ValueError:
            await update.message.reply_text("❌ ID grup harus berupa angka!")

# ===== GROUP HANDLER =====
async def group_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    if not is_group_premium(chat_id):
        keyboard = [
            [InlineKeyboardButton("📅 Sewa Sekarang", url="https://t.me/botrekapbot")]
        ]
        await update.message.reply_text(
            "❌ *GRUP BELUM PREMIUM*\n\n"
            "Bot hanya bisa digunakan di grup premium.\n"
            "Silahkan sewa bot di private chat @botrekapbot",
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return False
    
    if not is_group_admin(chat_id, user_id):
        await update.message.reply_text("❌ Hanya admin grup yang bisa menggunakan bot!")
        return False
    
    return True

# ===== REKAP COMMANDS =====
async def rekap_cek(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await group_message_handler(update, context):
        return
    
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
    if not await group_message_handler(update, context):
        return
    
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
    
    if not data["KECIL"] or not data["BESAR"]:
        await update.message.reply_text("❌ Format salah!\nGunakan:\nKECIL:\nNAMA MODAL\nBESAR:\nNAMA MODAL")
        return
    
    context.user_data['active_duel'] = {'data': data, 'fee': fee}
    
    keyboard = [
        [InlineKeyboardButton("🔵 KECIL", callback_data="KECIL"),
         InlineKeyboardButton("🔴 BESAR", callback_data="BESAR")]
    ]
    await update.message.reply_text(
        f"💰 Fee: {fee}%\n🏆 Pilih pemenang:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def bulatkan(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await group_message_handler(update, context):
        return
    
    players = db_query("SELECT username, balance FROM players WHERE balance != 0", fetchall=True)
    
    if not players:
        await update.message.reply_text("❌ Belum ada data player!")
        return
    
    for name, bal in players:
        if bal != 0:
            bal_baru = bulatkan_ke_bawah(bal)
            if bal_baru == 0:
                db_query("DELETE FROM players WHERE username=?", (name,))
            else:
                db_query("UPDATE players SET balance = ? WHERE username=?", (bal_baru, name))
    
    await update_pinned_message(update, context, update.effective_chat.id)
    await update.message.reply_text("✅ Saldo telah dibulatkan ke bawah (kelipatan 100)")

# === MAIN APP ===
class RekapwinBot:
    def __init__(self):
        self.app = Application.builder().token(TOKEN).build()
        self.setup_handlers()
    
    def setup_handlers(self):
        self.app.add_handler(CommandHandler("start", start))
        self.app.add_handler(CommandHandler("rekap", rekap_cek))
        self.app.add_handler(CommandHandler("rekapwin", rekapwin))
        self.app.add_handler(CommandHandler("bulatkan", bulatkan))
        self.app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT, private_message_handler))
        self.app.add_handler(MessageHandler(filters.ChatType.PRIVATE & filters.TEXT, handle_input))
        self.app.add_handler(CallbackQueryHandler(callback_handler))
    
    def process_update(self, update_json):
        update = Update.de_json(update_json, self.app.bot)
        self.app.process_update(update)

bot_instance = RekapwinBot()

# Export untuk digunakan di api/index.py
__all__ = ['bot_instance', 'db_query']
