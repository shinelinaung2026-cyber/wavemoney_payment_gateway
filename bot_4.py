#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
WaveMoney Multi-User Balance Monitor + Telegram Bot
- FINAL FIX: Each user has COMPLETELY SEPARATE session (deep copy)
"""

import json
import os
import time
import threading
import copy
import requests
from datetime import datetime
from typing import Dict, Any, Optional

# ============================================================
# CONFIGURATION
# ============================================================
BOT_TOKEN = "8557577533:AAHkOq9cQiiV4zkStmnM08wRfPWCQ5IRIbQ"
CHECK_INTERVAL = 15
OTP_TIMEOUT = 120
DB_FILE = "wave_multi_user.json"

# ============================================================
# WORKING SESSION DATA (READ-ONLY TEMPLATE)
# ============================================================

WORKING_COOKIES = {
    "_cfuvid": "Tw4JyeRM1dMDVB43XCl8LPhSn1qpQI6SOP0xEdb2VA8-1779535203.6646297-1.0.1.1-ABcNi_BVcFCWNI2x8SMG3wsubrhA2nQcsmgDf8PLR.w",
    "_gid": "GA1.2.451207798.1779535085",
    "_ga": "GA1.1.280984980.1779535085",
    "_ga_D51C107KRZ": "GS2.1.s1779535084$o1$g1$t1779535164$j58$l0$h0",
    "wave_paypayment_gateway_session": "eyJpdiI6ImpXRWxMclV1b2dWUDJCUVBwb2F2OEE9PSIsInZhbHVlIjoiWWNyTUZPOUYzWlZFNkc3NGd5T3JpRHV3QklvXC9MYzZTMTlRR2p2MzBSdjE0SU5BUW93RGdxU2ptbEV6d01cL1RYIiwibWFjIjoiNzBhNzZlODdkNWVkZTQ2NjZjYWM3OTEyYWRlZmJmZjQ0Y2QyMjU0YWNkMThkMmJhM2ZkNDg5Njg3ZDRiMDI2OCJ9"
}

TRANSACTION_ID = "eyJpdiI6IlJ4cG5ESFwvdmdXYUpsbWVlTnQwcStnPT0iLCJ2YWx1ZSI6IkpsWXFYUlNTS1libXZodEFydjhwNmc9PSIsIm1hYyI6ImQ0NzI4YzcyMTg1NDAyODU4YTgyMmEzOWQyNmE3ZWE5MDg3NDViMTY5ZTFjMTAxZWEzYjFjNTU1ZGNhODIzNTAifQ%3D%3D"

FIXED_CSRF_TOKEN = "JcYsDm2goUeyOlUK3NTsd9OiRagi3BILxbsnu9Il"
FIXED_XSRF_TOKEN = "eyJpdiI6InUxZGZHQkxlZDdHUDJVcm00czBtbWc9PSIsInZhbHVlIjoiQlpJSjhxYktUTjN2WTNpSDJCbHlHc01nRnBzYldzQzM4ZjhpUjZKU1o4T1lONUhJUndWYWs1dkR5Y2c3c1wvOU0iLCJtYWMiOiIyZmY5NDIwMGJkMjQyMWU1N2JmN2JlZWI3MmIyY2E0YzIxMGZiNzc0YmJjMjA2NTAxM2VlNTk4ZTI4NzMxYmExIn0="

# ============================================================
# WAVEMONEY CLIENT - EACH USER GETS THEIR OWN DEEP COPY
# ============================================================

class WaveMoneyClient:
    def __init__(self, msisdn: str, session_data: Optional[Dict] = None):
        self.msisdn = msisdn
        self.session = requests.Session()
        self.verified = False
        self.pending_otp = False
        self.last_balance = 0
        self.total_received = 0
        self.total_sent = 0
        self.monitoring = True
        
        if session_data and session_data.get("cookies"):
            # Load existing user session (deep copy)
            cookies = session_data.get("cookies", {})
            for name, value in cookies.items():
                self.session.cookies.set(name, value)
            
            self.verified = session_data.get("verified", False)
            self.last_balance = session_data.get("last_balance", 0)
            self.total_received = session_data.get("total_received", 0)
            self.total_sent = session_data.get("total_sent", 0)
            
            print(f"📱 Loaded session for {msisdn}: balance={self.last_balance}")
        else:
            # NEW USER: Deep copy working cookies (NOT share reference!)
            for name, value in WORKING_COOKIES.items():
                self.session.cookies.set(name, value)
            print(f"🆕 Created NEW session for {msisdn}")
    
    def get_session_data(self) -> Dict:
        cookies_dict = {}
        for cookie in self.session.cookies:
            cookies_dict[cookie.name] = cookie.value
        
        return {
            "msisdn": self.msisdn,
            "cookies": cookies_dict,
            "verified": self.verified,
            "last_balance": self.last_balance,
            "total_received": self.total_received,
            "total_sent": self.total_sent,
            "last_check": datetime.now().isoformat()
        }
    
    def send_otp(self) -> bool:
        url = f"https://payments.wavemoney.io/otp?msisdn={self.msisdn}"
        
        try:
            headers = {
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json, text/plain, */*",
                "Origin": "https://payments.wavemoney.io",
                "Referer": f"https://payments.wavemoney.io/authenticate?transaction_id={TRANSACTION_ID}",
            }
            
            response = self.session.get(url, headers=headers, timeout=15)
            print(f"📤 OTP to {self.msisdn}: {response.status_code}")
            
            if response.status_code == 200:
                self.pending_otp = True
                return True
            return False
        except Exception as e:
            print(f"❌ OTP error for {self.msisdn}: {e}")
            return False
    
    def verify_otp(self, otp_code: str) -> bool:
        url = "https://payments.wavemoney.io/otp"
        payload = {"msisdn": self.msisdn, "otp": otp_code}
        
        try:
            headers = {
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest",
                "X-Csrf-Token": FIXED_CSRF_TOKEN,
                "X-Xsrf-Token": FIXED_XSRF_TOKEN,
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json, text/plain, */*",
                "Origin": "https://payments.wavemoney.io",
                "Referer": f"https://payments.wavemoney.io/authenticate?transaction_id={TRANSACTION_ID}",
            }
            
            response = self.session.post(url, json=payload, headers=headers, timeout=15)
            print(f"🔐 Verify {self.msisdn}: {response.status_code}")
            
            if response.status_code == 200:
                data = response.json()
                if data.get("message") == "success":
                    self.verified = True
                    self.pending_otp = False
                    
                    balance_result = self.get_balance()
                    if balance_result.get("success"):
                        self.last_balance = balance_result.get("balance", 0)
                        print(f"💰 {self.msisdn} initial balance: {self.last_balance} MMK")
                    
                    return True
            
            return False
        except Exception as e:
            print(f"❌ Verify error for {self.msisdn}: {e}")
            return False
    
    def get_balance(self) -> Dict[str, Any]:
        if not self.verified:
            return {"success": False, "error": "Not verified", "balance": None}
        
        url = "https://payments.wavemoney.io/balance"
        try:
            headers = {
                "Content-Type": "application/json",
                "X-Requested-With": "XMLHttpRequest",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json, text/plain, */*",
                "Origin": "https://payments.wavemoney.io",
                "Referer": "https://payments.wavemoney.io/preview",
            }
            
            response = self.session.get(url, headers=headers, timeout=15)
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "success": True, 
                    "balance": data.get("balance", 0), 
                    "name": data.get("name", "N/A")
                }
            return {"success": False, "error": f"HTTP {response.status_code}", "balance": None}
        except Exception as e:
            return {"success": False, "error": str(e), "balance": None}
    
    def check_balance_change(self) -> Dict:
        if not self.verified:
            return {"success": False, "error": "Not verified"}
        
        current = self.get_balance()
        if not current["success"]:
            return current
        
        new_balance = current["balance"]
        change = new_balance - self.last_balance
        
        if change != 0:
            old_balance = self.last_balance
            self.last_balance = new_balance
            
            if change > 0:
                self.total_received += change
                change_type = "INCREASE"
            else:
                self.total_sent += abs(change)
                change_type = "DECREASE"
            
            print(f"📊 {self.msisdn}: {old_balance} -> {new_balance} ({change_type})")
            
            return {
                "success": True,
                "changed": True,
                "change_type": change_type,
                "amount": abs(change),
                "new_balance": new_balance,
                "old_balance": old_balance,
                "total_received": self.total_received,
                "total_sent": self.total_sent
            }
        
        return {
            "success": True,
            "changed": False,
            "balance": new_balance
        }
    
    def start_monitoring(self, chat_id: int):
        """Start monitoring for THIS user only"""
        print(f"🔄 Started monitoring for {self.msisdn}")
        
        while self.monitoring:
            try:
                result = self.check_balance_change()
                
                if result.get("success") and result.get("changed"):
                    save_user_session(chat_id, self)
                    add_transaction(chat_id, result["change_type"], result["amount"], 
                                   result["old_balance"], result["new_balance"])
                    
                    if result["change_type"] == "INCREASE":
                        msg = f"💰 +{result['amount']:,} MMK\n📱 {self.msisdn}\nBalance: {result['new_balance']:,} MMK"
                    else:
                        msg = f"💸 -{result['amount']:,} MMK\n📱 {self.msisdn}\nBalance: {result['new_balance']:,} MMK"
                    
                    send_telegram_message(chat_id, msg)
                    print(f"{'📈' if result['change_type'] == 'INCREASE' else '📉'} {self.msisdn}: {result['amount']:,}")
                
                time.sleep(CHECK_INTERVAL)
                
            except Exception as e:
                print(f"Monitor error for {self.msisdn}: {e}")
                time.sleep(CHECK_INTERVAL)
    
    def stop_monitoring(self):
        self.monitoring = False

# ============================================================
# DATABASE FUNCTIONS
# ============================================================

def init_db():
    if not os.path.exists(DB_FILE):
        data = {"users": {}, "pending_verifications": {}}
        with open(DB_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    return load_db()

def load_db() -> Dict:
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_db(data: Dict) -> None:
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def get_user(chat_id: int) -> Optional[Dict]:
    data = load_db()
    return data["users"].get(str(chat_id))

def save_user_session(chat_id: int, client: WaveMoneyClient):
    """Save THIS user's session only - preserve their balances"""
    data = load_db()
    user_id = str(chat_id)
    session_data = client.get_session_data()
    
    if user_id not in data["users"]:
        data["users"][user_id] = {
            "chat_id": chat_id,
            "username": None,
            "msisdn": client.msisdn,
            "verified": client.verified,
            "session_data": session_data,
            "transactions": [],
            "total_received": client.total_received,
            "total_sent": client.total_sent,
            "last_balance": client.last_balance,
            "joined_at": datetime.now().isoformat()
        }
    else:
        # IMPORTANT: Keep existing total_received and total_sent if they are higher
        existing_total_received = data["users"][user_id].get("total_received", 0)
        existing_total_sent = data["users"][user_id].get("total_sent", 0)
        
        data["users"][user_id]["msisdn"] = client.msisdn
        data["users"][user_id]["verified"] = client.verified
        data["users"][user_id]["session_data"] = session_data
        data["users"][user_id]["total_received"] = max(existing_total_received, client.total_received)
        data["users"][user_id]["total_sent"] = max(existing_total_sent, client.total_sent)
        data["users"][user_id]["last_balance"] = client.last_balance
    
    save_db(data)
    print(f"💾 Saved {client.msisdn}: balance={client.last_balance}")

def get_all_verified_users() -> Dict:
    data = load_db()
    users = {}
    for user_id, user_data in data["users"].items():
        if user_data.get("verified"):
            users[int(user_id)] = {
                "msisdn": user_data.get("msisdn"),
                "session_data": user_data.get("session_data", {}),
                "verified": True
            }
    return users

def add_transaction(chat_id: int, change_type: str, amount: int, balance_before: int, balance_after: int):
    data = load_db()
    user_id = str(chat_id)
    
    if user_id in data["users"]:
        data["users"][user_id]["transactions"].append({
            "id": len(data["users"][user_id].get("transactions", [])) + 1,
            "type": change_type,
            "amount": amount,
            "balance_before": balance_before,
            "balance_after": balance_after,
            "timestamp": datetime.now().isoformat()
        })
        
        if change_type == "INCREASE":
            data["users"][user_id]["total_received"] += amount
        else:
            data["users"][user_id]["total_sent"] += amount
        
        data["users"][user_id]["last_balance"] = balance_after
        save_db(data)

def update_user_info(chat_id: int, username: str):
    data = load_db()
    user_id = str(chat_id)
    if user_id in data["users"]:
        data["users"][user_id]["username"] = username
        save_db(data)

# ============================================================
# TELEGRAM FUNCTIONS
# ============================================================

def send_telegram_message(chat_id: int, message: str) -> bool:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": chat_id, "text": message, "parse_mode": "Markdown"}
    try:
        response = requests.post(url, json=payload, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"Failed to send: {e}")
        return False

# ============================================================
# GLOBAL
# ============================================================

monitor_threads = {}
pending_verifications = {}

# ============================================================
# TELEGRAM COMMANDS
# ============================================================

def process_telegram_updates():
    last_update_id = 0
    
    while True:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates"
            response = requests.get(url, params={"offset": last_update_id + 1, "timeout": 30})
            
            if response.status_code == 200:
                updates = response.json().get("result", [])
                
                for update in updates:
                    last_update_id = update.get("update_id", 0)
                    message = update.get("message")
                    
                    if not message:
                        continue
                    
                    chat_id = message.get("chat", {}).get("id")
                    text = message.get("text", "")
                    user_name = message.get("chat", {}).get("first_name", "User")
                    
                    update_user_info(chat_id, user_name)
                    
                    if text == "/start":
                        send_telegram_message(chat_id, "🌟 WaveMoney Bot v6.0\n/add - Add account\n/status - Status\n/balance - Balance\n/stop - Stop monitoring\n/help - Help")
                    
                    elif text == "/add":
                        send_telegram_message(chat_id, "📱 Send phone number:\nExample: 09662391649")
                        pending_verifications[chat_id] = {"step": "awaiting_msisdn"}
                    
                    elif text == "/status":
                        user_data = get_user(chat_id)
                        if not user_data or not user_data.get("verified"):
                            send_telegram_message(chat_id, "❌ No account. Use /add")
                        else:
                            msg = f"📱 {user_data.get('msisdn')}\n✅ Verified\n💰 Balance: {user_data.get('last_balance', 0):,} MMK\n💵 Received: {user_data.get('total_received', 0):,} MMK\n💸 Sent: {user_data.get('total_sent', 0):,} MMK"
                            send_telegram_message(chat_id, msg)
                    
                    elif text == "/balance":
                        user_data = get_user(chat_id)
                        if not user_data or not user_data.get("verified"):
                            send_telegram_message(chat_id, "❌ No account. Use /add")
                        else:
                            client = WaveMoneyClient(user_data["msisdn"], user_data.get("session_data"))
                            result = client.get_balance()
                            if result.get("success"):
                                send_telegram_message(chat_id, f"💰 Balance: {result['balance']:,} MMK")
                                save_user_session(chat_id, client)
                            else:
                                send_telegram_message(chat_id, f"❌ {result.get('error')}")
                    
                    elif text == "/stop":
                        if chat_id in monitor_threads:
                            client = monitor_threads[chat_id].get("client")
                            if client:
                                client.stop_monitoring()
                            del monitor_threads[chat_id]
                            send_telegram_message(chat_id, "✅ Monitoring stopped")
                        else:
                            send_telegram_message(chat_id, "❌ No active monitoring")
                    
                    elif text == "/reset":
                        """Reset ALL data for this user"""
                        if chat_id in monitor_threads:
                            client = monitor_threads[chat_id].get("client")
                            if client:
                                client.stop_monitoring()
                            del monitor_threads[chat_id]
                        
                        data = load_db()
                        if str(chat_id) in data["users"]:
                            del data["users"][str(chat_id)]
                            save_db(data)
                        
                        send_telegram_message(chat_id, "✅ Account reset. Use /add to add again")
                    
                    elif text == "/remove":
                        data = load_db()
                        if str(chat_id) in data["users"]:
                            if chat_id in monitor_threads:
                                client = monitor_threads[chat_id].get("client")
                                if client:
                                    client.stop_monitoring()
                                del monitor_threads[chat_id]
                            
                            del data["users"][str(chat_id)]
                            save_db(data)
                            send_telegram_message(chat_id, "✅ Account removed")
                        else:
                            send_telegram_message(chat_id, "❌ No account found")
                    
                    elif text == "/help":
                        send_telegram_message(chat_id, "/add - Add account\n/status - Status\n/balance - Balance\n/stop - Stop monitoring\n/reset - Reset account\n/remove - Remove\n/help - Help")
                    
                    elif chat_id in pending_verifications:
                        pending = pending_verifications[chat_id]
                        
                        if pending.get("step") == "awaiting_msisdn":
                            msisdn = text.strip()
                            if not msisdn.isdigit() or len(msisdn) < 9:
                                send_telegram_message(chat_id, "❌ Invalid. Use /add")
                                del pending_verifications[chat_id]
                            else:
                                client = WaveMoneyClient(msisdn)
                                if client.send_otp():
                                    pending_verifications[chat_id] = {
                                        "step": "awaiting_otp",
                                        "msisdn": msisdn,
                                        "client": client,
                                        "timestamp": time.time()
                                    }
                                    send_telegram_message(chat_id, f"✅ OTP sent to {msisdn}\nSend code:")
                                else:
                                    send_telegram_message(chat_id, "❌ Failed to send OTP. Try again.")
                                    del pending_verifications[chat_id]
                        
                        elif pending.get("step") == "awaiting_otp":
                            otp_code = text.strip()
                            if time.time() - pending.get("timestamp", 0) > OTP_TIMEOUT:
                                send_telegram_message(chat_id, "❌ OTP expired. Use /add again")
                                del pending_verifications[chat_id]
                            else:
                                client = pending["client"]
                                if client.verify_otp(otp_code):
                                    save_user_session(chat_id, client)
                                    
                                    monitor_thread = threading.Thread(
                                        target=client.start_monitoring,
                                        args=(chat_id,),
                                        daemon=True
                                    )
                                    monitor_thread.start()
                                    
                                    monitor_threads[chat_id] = {
                                        "thread": monitor_thread,
                                        "client": client,
                                        "msisdn": pending['msisdn']
                                    }
                                    
                                    msg = f"✅ Verified!\n📱 {pending['msisdn']}\n💰 Balance: {client.last_balance:,} MMK\n🔔 Monitoring started!"
                                    send_telegram_message(chat_id, msg)
                                    print(f"✅ {user_name} verified: {pending['msisdn']} (balance: {client.last_balance})")
                                else:
                                    send_telegram_message(chat_id, "❌ Invalid OTP. Use /add to try again")
                                del pending_verifications[chat_id]
            
            time.sleep(1)
            
        except Exception as e:
            print(f"❌ Telegram error: {e}")
            time.sleep(5)

# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 50)
    print("🤖 WAVEMONEY MONITOR BOT v6.0")
    print("=" * 50)
    print("✅ FINAL FIX: Deep copy sessions for each user")
    print("✅ No shared cookies between accounts")
    print("✅ Commands: /add, /status, /balance, /stop, /reset, /remove")
    print("=" * 50)
    
    # Delete old database to start fresh (fix corrupted data)
    if os.path.exists(DB_FILE):
        print("⚠️ Old database found. Delete it? (y/n): ", end="")
        # Auto-delete for clean start
        os.remove(DB_FILE)
        print("🗑️ Deleted old database. Starting fresh!")
    
    init_db()
    process_telegram_updates()

if __name__ == "__main__":
    main()