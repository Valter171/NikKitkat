import requests
import json
import threading
import time
import sqlite3
from datetime import datetime
import telebot
from telebot import types
import logging
import sys
import os

try:
    BOT_TOKEN = "ТОКЕН"
    ADMIN_IDS = [АЙДИ]
    API_URL = "https://giftsbattle.com/api/v1"

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    logger = logging.getLogger(__name__)

    bot = telebot.TeleBot(BOT_TOKEN)

    class AccountManager:
        def __init__(self):
            self.conn = sqlite3.connect('accounts.db', check_same_thread=False)
            self.create_tables()
        
        def create_tables(self):
            cursor = self.conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token TEXT UNIQUE,
                    username TEXT,
                    balance INTEGER DEFAULT 0,
                    is_active BOOLEAN DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS activations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER,
                    promo_code TEXT,
                    success BOOLEAN,
                    stars_received INTEGER DEFAULT 0,
                    activated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (account_id) REFERENCES accounts (id)
                )
            ''')
            self.conn.commit()
        
        def add_account(self, token, username=None):
            cursor = self.conn.cursor()
            try:
                cursor.execute(
                    'INSERT OR REPLACE INTO accounts (token, username) VALUES (?, ?)',
                    (token, username)
                )
                self.conn.commit()
                return True
            except Exception as e:
                logger.error(f"Error adding account: {e}")
                return False
        
        def get_active_accounts(self):
            cursor = self.conn.cursor()
            cursor.execute('SELECT * FROM accounts WHERE is_active = 1')
            return cursor.fetchall()
        
        def update_balance(self, account_id, balance):
            cursor = self.conn.cursor()
            cursor.execute(
                'UPDATE accounts SET balance = ? WHERE id = ?',
                (balance, account_id)
            )
            self.conn.commit()
        
        def record_activation(self, account_id, promo_code, success, stars=0):
            cursor = self.conn.cursor()
            cursor.execute(
                'INSERT INTO activations (account_id, promo_code, success, stars_received) VALUES (?, ?, ?, ?)',
                (account_id, promo_code, success, stars)
            )
            self.conn.commit()

    account_manager = AccountManager()

    class GiftBattleAPI:
        def __init__(self):
            self.base_headers = {
                'Accept': '*/*',
                'Content-Type': 'application/json',
                'Origin': 'https://giftsbattle.app',
                'Referer': 'https://giftsbattle.app/',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
        
        def get_user_info(self, token):
            try:
                headers = self.base_headers.copy()
                headers['Authorization'] = f'Bearer {token}'
                
                response = requests.get(
                    f'{API_URL}/user',
                    headers=headers,
                    timeout=10
                )
                
                if response.status_code == 200:
                    return response.json()
                else:
                    logger.warning(f"API error: {response.status_code}")
                    return None
            except Exception as e:
                logger.error(f"Error getting user info: {e}")
                return None
        
        def activate_promo(self, token, promo_code):
            try:
                headers = self.base_headers.copy()
                headers['Authorization'] = f'Bearer {token}'
                
                data = {
                    'code_data': promo_code
                }
                
                response = requests.post(
                    f'{API_URL}/promo/activate/',
                    headers=headers,
                    json=data,
                    timeout=10
                )
                
                result = {
                    'success': response.status_code == 200,
                    'status_code': response.status_code,
                    'data': response.json() if response.status_code == 200 else None
                }
                
                return result
            except Exception as e:
                logger.error(f"Error activating promo: {e}")
                return {'success': False, 'error': str(e)}

    giftbattle_api = GiftBattleAPI()

    @bot.message_handler(commands=['start'])
    def start_command(message):
        if message.from_user.id not in ADMIN_IDS:
            bot.reply_to(message, "Access denied")
            return
        
        keyboard = types.ReplyKeyboardMarkup(resize_keyboard=True)
        keyboard.add('Stats', 'Accounts')
        keyboard.add('Activate promo', 'Update balances')
        
        bot.send_message(
            message.chat.id,
            "Bot for mass promo activation",
            reply_markup=keyboard,
            parse_mode='HTML'
        )

    @bot.message_handler(func=lambda message: message.text == 'Stats')
    def show_stats(message):
        if message.from_user.id not in ADMIN_IDS:
            return
        
        accounts = account_manager.get_active_accounts()
        total_accounts = len(accounts)
        active_accounts = 0
        total_balance = 0
        
        for account in accounts:
            user_info = giftbattle_api.get_user_info(account[1])
            if user_info:
                active_accounts += 1
                balance = user_info.get('sum', 0)
                total_balance += balance
                account_manager.update_balance(account[0], balance)
        
        cursor = account_manager.conn.cursor()
        cursor.execute('SELECT COUNT(*) FROM activations WHERE success = 1')
        total_activations = cursor.fetchone()[0]
        
        cursor.execute('SELECT SUM(stars_received) FROM activations')
        total_stars = cursor.fetchone()[0] or 0
        
        stats_text = (
            f"Stats\n\n"
            f"Total accounts: {total_accounts}\n"
            f"Active: {active_accounts}\n"
            f"Total balance: {total_balance} stars\n"
            f"Activations: {total_activations}\n"
            f"Total stars: {total_stars}"
        )
        
        bot.send_message(message.chat.id, stats_text, parse_mode='HTML')

    @bot.message_handler(func=lambda message: message.text == 'Accounts')
    def show_accounts(message):
        if message.from_user.id not in ADMIN_IDS:
            return
        
        accounts = account_manager.get_active_accounts()
        if not accounts:
            bot.send_message(message.chat.id, "No accounts")
            return
        
        accounts_text = "Accounts:\n\n"
        
        for i, account in enumerate(accounts[:20], 1):
            user_info = giftbattle_api.get_user_info(account[1])
            username = user_info.get('telegram_username', 'N/A') if user_info else 'N/A'
            balance = user_info.get('sum', 0) if user_info else 0
            
            accounts_text += f"{i}. @{username} - {balance} stars\n"
        
        if len(accounts) > 20:
            accounts_text += f"\n... and {len(accounts) - 20} more"
        
        bot.send_message(message.chat.id, accounts_text, parse_mode='HTML')

    @bot.message_handler(func=lambda message: message.text == 'Activate promo')
    def ask_promo_code(message):
        if message.from_user.id not in ADMIN_IDS:
            return
        
        msg = bot.send_message(
            message.chat.id,
            "Enter promo code:"
        )
        bot.register_next_step_handler(msg, process_promo_activation)

    def process_promo_activation(message):
        promo_code = message.text.strip()
        
        if not promo_code:
            bot.send_message(message.chat.id, "Empty promo code")
            return
        
        bot.send_message(message.chat.id, f"Activating: {promo_code}...")
        
        results = mass_activate_promo(promo_code)
        
        success_count = sum(1 for r in results if r['success'])
        total_count = len(results)
        total_stars = sum(r.get('stars_received', 0) for r in results)
        
        report_text = (
            f"Activation report: {promo_code}\n\n"
            f"Success: {success_count}\n"
            f"Failed: {total_count - success_count}\n"
            f"Stars received: {total_stars}\n"
            f"Total accounts: {total_count}"
        )
        
        bot.send_message(message.chat.id, report_text, parse_mode='HTML')

    def mass_activate_promo(promo_code):
        accounts = account_manager.get_active_accounts()
        results = []
        threads = []
        
        def activate_single(account):
            result = giftbattle_api.activate_promo(account[1], promo_code)
            result['account_id'] = account[0]
            
            stars_received = 0
            if result['success'] and result['data']:
                stars_received = result['data'].get('sum', 0)
                result['stars_received'] = stars_received
            
            account_manager.record_activation(
                account[0], promo_code, result['success'], stars_received
            )
            
            results.append(result)
        
        for account in accounts:
            thread = threading.Thread(target=activate_single, args=(account,))
            threads.append(thread)
            thread.start()
        
        for thread in threads:
            thread.join()
        
        return results

    @bot.message_handler(func=lambda message: message.text == 'Update balances')
    def update_balances(message):
        if message.from_user.id not in ADMIN_IDS:
            return
        
        bot.send_message(message.chat.id, "Updating balances...")
        
        accounts = account_manager.get_active_accounts()
        updated = 0
        
        for account in accounts:
            user_info = giftbattle_api.get_user_info(account[1])
            if user_info:
                balance = user_info.get('sum', 0)
                account_manager.update_balance(account[0], balance)
                updated += 1
        
        bot.send_message(
            message.chat.id,
            f"Updated balances for {updated} accounts"
        )

    @bot.message_handler(commands=['add_account'])
    def add_account_command(message):
        if message.from_user.id not in ADMIN_IDS:
            return
        
        msg = bot.send_message(
            message.chat.id,
            "Send account token:"
        )
        bot.register_next_step_handler(msg, process_account_token)

    def process_account_token(message):
        token = message.text.strip()
        
        if account_manager.add_account(token):
            user_info = giftbattle_api.get_user_info(token)
            if user_info:
                username = user_info.get('telegram_username', 'N/A')
                bot.send_message(
                    message.chat.id,
                    f"Account added: @{username}"
                )
            else:
                bot.send_message(
                    message.chat.id,
                    "Account added but token check failed"
                )
        else:
            bot.send_message(message.chat.id, "Error adding account")

    if __name__ == "__main__":
        logger.info("Starting bot...")
        print("Bot started!")
        print("Press Ctrl+C to stop")
        bot.infinity_polling()

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
    input("Press Enter to exit...")

import threading
import logging
import time

def keep_alive_log():
    while True:
        logging.info("Bot is alive ✅")
        time.sleep(300)  # каждые 5 минут

def run_bot_forever():
    while True:
        try:
            logging.info("Starting bot polling...")
            bot.polling(non_stop=True, interval=0, timeout=20)
        except Exception as e:
            logging.error(f"Bot crashed with error: {e}. Restarting in 5 seconds...")
            time.sleep(5)

# Запускаем поток keep-alive логов
threading.Thread(target=keep_alive_log, daemon=True).start()

# Запускаем бота с авто-перезапуском
run_bot_forever()
