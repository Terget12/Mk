import os
import telebot
import requests
import time
import threading
import json
import uuid
import re
import html
from datetime import datetime, timezone, timedelta
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from pymongo import MongoClient

# ================= CopyTextButton Universal Patch =================
class CopyTextButton:
    """Stub CopyTextButton — যেকোনো pyTelegramBotAPI ভার্সনে কাজ করে।"""
    def __init__(self, text: str):
        self.text = str(text)

_orig_ikb_init    = telebot.types.InlineKeyboardButton.__init__
_orig_ikb_to_dict = telebot.types.InlineKeyboardButton.to_dict

def _patched_ikb_init(self, text, **kwargs):
    ctb = kwargs.pop("copy_text", None)
    if ctb is not None:
        self._copy_text_str = ctb.text if hasattr(ctb, "text") else str(ctb)
    else:
        self._copy_text_str = None
    _orig_ikb_init(self, text, **kwargs)

def _patched_ikb_to_dict(self):
    d = _orig_ikb_to_dict(self)
    if getattr(self, "_copy_text_str", None) is not None:
        d["copy_text"] = {"text": self._copy_text_str}
    return d

telebot.types.InlineKeyboardButton.__init__ = _patched_ikb_init
telebot.types.InlineKeyboardButton.to_dict  = _patched_ikb_to_dict

def make_copy_button(label, copy_value):
    """সব ভার্শনে native copy button — ক্লিক করলেই সরাসরি কপি হয়।"""
    return InlineKeyboardButton(text=label, copy_text=CopyTextButton(text=copy_value))

# ================= কনফিগারেশন =================
BOT_TOKEN = "8532331160:AAF5eQ6XAnerZKn6r7h1HsX62MnXXJqZqHw"
ADMIN_ID = 6901639746          # ✅ মেইন এডমিন (সর্বোচ্চ ক্ষমতা)
SUB_ADMIN_ID = 7259639093            # ✅ হার্ডকোডেড সাব-এডমিন ID (না থাকলে None রাখুন)

# API লগইন ডিটেইলস
API_LOGIN_ID = "Mdsafayet517@gmail.com"
API_PASSWORD = "Safayet@@0498"

# বট স্পিড বাড়ানোর জন্য Threading 50 করা হলো
bot = telebot.TeleBot(BOT_TOKEN, num_threads=50)

# ================= MongoDB কনফিগারেশন =================
MONGO_URI = "mongodb+srv://mdsafayet517:kFA2fjCqFuPnJV6D@cluster0.njxzc5v.mongodb.net/?appName=Cluster0"

try:
    mongo_client = MongoClient(MONGO_URI)
    db = mongo_client["WhiteX2_BotDB"]
    collection = db["bot_data"]
    print("✅ MongoDB ক্লাউডের সাথে সফলভাবে কানেক্ট হয়েছে!")
except Exception as e:
    print(f"❌ MongoDB Connection Error: {e}")

# ================= ডাটাবেস ও হেল্পার =================
def load_data():
    try:
        doc = collection.find_one({"_id": "main_data"})
        if not doc:
            default_data = {
                "_id": "main_data",
                "admins": [],
                "sub_admins": [],
                "global_stats": {"total_numbers": 0, "total_otps": 0, "daily": {}},
                "users": {},
                "services_data": {},
                "forward_groups": [],
                "otp_group_link": "https://t.me/your_admin_group_link_here",
                "force_join_enabled": False,
                "force_join_channels": []
            }
            collection.insert_one(default_data)
            return default_data
        return doc
    except Exception as e:
        print(f"Database Load Error: {e}")
        return {}

def save_data(data):
    try:
        data["_id"] = "main_data"
        collection.replace_one({"_id": "main_data"}, data, upsert=True)
    except Exception as e:
        print(f"Database Save Error: {e}")

# ================= সেশন ম্যানেজমেন্ট (Automated Login) =================
api_session = requests.Session()
api_session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Mobile Safari/537.36',
    'Accept': '*/*',
    'Origin': 'https://mknetworkbd.com',
    'sec-fetch-site': 'same-origin',
    'sec-fetch-mode': 'cors',
})

# একসাথে একাধিক থ্রেড রিলগইন না করতে লক
_login_lock = threading.Lock()

def perform_api_login():
    login_url = "https://mknetworkbd.com/login.php"
    payload = {
        'login_id': API_LOGIN_ID,
        'password': API_PASSWORD
    }
    try:
        response = api_session.post(login_url, data=payload)
        response.raise_for_status()
        print("✅ API Login Successful! Cookies have been saved to session.")
        return True
    except Exception as e:
        print(f"❌ API Login Error: {e}")
        return False

def is_session_expired(data):
    """API রেসপন্স চেক করে Session Expired কিনা"""
    if isinstance(data, dict):
        msg = str(data.get('message', '')).lower()
        status = str(data.get('status', '')).lower()
        if 'session' in msg and ('expired' in msg or 'invalid' in msg):
            return True
        if status == 'error' and 'session' in msg:
            return True
    return False

def relogin_and_retry():
    """Session Expired হলে একবারই লগইন করবে — একাধিক থ্রেড একসাথে না করে"""
    with _login_lock:
        print("🔄 Session Expired! স্বয়ংক্রিয়ভাবে রিলগইন করা হচ্ছে...")
        success = perform_api_login()
        if success:
            print("✅ রিলগইন সফল! আবার চেষ্টা করা হচ্ছে...")
        else:
            print("❌ রিলগইন ব্যর্থ হয়েছে!")
        return success

# ================= ভেরিয়েবল =================
user_last_number = {}
user_current_range = {} 
user_session_data = {} 
number_cooldowns = {}
active_tracking = set()  # কোন নম্বরগুলো এখন OTP এর জন্য অপেক্ষায় আছে 

DEVELOPER_FOOTER = (
    "\n\n┌────────────────────┐\n"
    "      💎 কাস্টমার সাপোর্ট 💎\n"
    "└────────────────────┘\n\n"
    "💬 সরাসরি এডমিনের সাথে কথা বলুন\n"
    "যেকোনো সমস্যার জন্য আমাদের ইনবক্সে মেসেজ দিন।\n\n"
    "💠 𝙳𝙴𝚅𝙴𝙻𝙾𝙿𝙴𝚁 : 👑 𝑺𝑰𝒀𝑨𝑴 𝑪𝑯𝑶𝑾𝑫𝑯𝑼𝑹𝒀\n"
    "নিচের বাটনে ক্লিক করে মেসেজ দিন।\n"
    "━━━━━━━━━━━━━━━━━━\n"
    "🕷 𝙿𝙾𝚆𝙴𝚁𝙴𝙳 𝙱𝚈 𝑺𝑰𝒀𝑨𝑴 𝑪𝑯𝑶𝑾𝑫𝑯𝑼𝑹𝒀 ᯓᡣ𐭩"
)

def today_str():
    # বাংলাদেশ টাইম UTC+6
    bd_time = datetime.now(timezone(timedelta(hours=6)))
    return bd_time.strftime("%Y-%m-%d")

def update_stats(stat_type):
    data = load_data()
    today = today_str()
    gs = data.setdefault("global_stats", {})
    daily = gs.setdefault("daily", {})
    td = daily.setdefault(today, {"numbers": 0, "otps": 0})

    if stat_type == 'number':
        gs["total_numbers"] = gs.get("total_numbers", 0) + 1
        td["numbers"] += 1
    elif stat_type == 'otp':
        gs["total_otps"] = gs.get("total_otps", 0) + 1
        td["otps"] += 1
    save_data(data)

def add_user(user_id):
    data = load_data()
    if str(user_id) not in data.get("users", {}):
        data.setdefault("users", {})[str(user_id)] = True
        save_data(data)

def is_main_admin(user_id):
    """শুধুমাত্র মেইন এডমিন — Sub-Admin যোগ/বাতিল করার ক্ষমতা শুধু এর"""
    return user_id == ADMIN_ID

def is_sub_admin(user_id):
    """হার্ডকোডেড বা DB-তে সেভ করা সাব-এডমিন কিনা চেক করো"""
    if SUB_ADMIN_ID and user_id == SUB_ADMIN_ID:
        return True
    return user_id in load_data().get("sub_admins", [])

def is_admin(user_id):
    """মেইন এডমিন অথবা যেকোনো সাব-এডমিন"""
    return is_main_admin(user_id) or is_sub_admin(user_id)

def get_flag(name):
    flags = {
        "bangladesh": "🇧🇩", "togo": "🇹🇬", "india": "🇮🇳", "pakistan": "🇵🇰",
        "usa": "🇺🇸", "uk": "🇬🇧", "indonesia": "🇮🇩", "brazil": "🇧🇷", "russia": "🇷🇺"
    }
    return flags.get(name.lower().strip(), "🌍")

def extract_otp(text):
    match = re.search(r'\b\d{3}[\s-]?\d{3,4}\b|\b\d{4,8}\b', text)
    return match.group(0) if match else "N/A"

# ================= ফোর্স জয়েন চেক (ফিক্সড) =================
def normalize_channel(channel):
    """চ্যানেল/গ্রুপ identifier normalize করে — @username বা numeric ID"""
    channel = channel.strip()
    try:
        return int(channel)
    except ValueError:
        pass
    if not channel.startswith('@'):
        channel = '@' + channel
    return channel

def check_force_join(user_id):
    data = load_data()
    if not data.get("force_join_enabled", False) or is_admin(user_id):
        return True, []
    
    channels = data.get("force_join_channels", [])
    not_joined = []
    
    if not channels: 
        return True, []
    
    for channel in channels:
        try:
            chat_id_norm = normalize_channel(channel)
            chat_member = bot.get_chat_member(chat_id_norm, user_id)
            if chat_member.status in ['left', 'kicked', 'restricted']:
                not_joined.append(channel)
        except telebot.apihelper.ApiTelegramException as e:
            err_msg = str(e).lower()
            if 'user not found' in err_msg or 'member list is inaccessible' in err_msg:
                not_joined.append(channel)
            elif 'chat not found' in err_msg or 'invalid' in err_msg:
                not_joined.append(channel)
            else:
                not_joined.append(channel)
        except Exception as e:
            print(f"Force join check error for {channel}: {e}")
            not_joined.append(channel)
            
    if not_joined:
        return False, not_joined
    return True, []

def send_force_join_message(chat_id, missing_channels):
    markup = InlineKeyboardMarkup(row_width=1)
    for ch in missing_channels:
        ch_str = str(ch).strip()
        if ch_str.startswith('@'):
            link = f"https://t.me/{ch_str.replace('@', '')}"
        elif ch_str.lstrip('-').isdigit():
            link = None
        else:
            link = f"https://t.me/{ch_str.replace('@', '')}"
        
        if link:
            markup.add(InlineKeyboardButton("📢 চ্যানেলে জয়েন করুন", url=link))
    
    markup.add(InlineKeyboardButton("✅ আমি জয়েন করেছি", callback_data="check_join_status"))
    
    msg = "⚠️ <b>বটটি ব্যবহার করতে আপনাকে প্রথমে আমাদের চ্যানেলে যুক্ত হতে হবে!</b>\nনিচের বাটন থেকে চ্যানেলে জয়েন করে <b>✅ আমি জয়েন করেছি</b> বাটনে ক্লিক করুন।"
    bot.send_message(chat_id, msg, reply_markup=markup, parse_mode="HTML")

# ================= API ফাংশন (নম্বর ও OTP) =================
def get_phone_number(number_range):
    url = "https://mknetworkbd.com/API/api_handler_test.php"
    payload = {'action': 'get_number', 'range': number_range}
    post_headers = {'Referer': 'https://mknetworkbd.com/getnum_test.php'}

    for attempt in range(2):
        try:
            response = api_session.post(url, data=payload, headers=post_headers)
            response.raise_for_status()
            data = response.json()
            if data.get('status') == 'success':
                return data.get('number')
            if is_session_expired(data) and attempt == 0:
                if relogin_and_retry():
                    continue
            return f"Failed: {data}"
        except Exception as e:
            return f"Error: {e}"
    return "Failed: Max retry exceeded"

def parse_sms_text(raw):
    """full_sms_list string বা list যাই হোক — plain text বের করে দেয়।"""
    if not raw:
        return ""
    if isinstance(raw, list):
        parts = []
        for item in raw:
            if isinstance(item, dict):
                parts.append(item.get('sms_text') or item.get('text') or item.get('message') or str(item))
            else:
                parts.append(str(item))
        return " | ".join(parts) if parts else ""
    return str(raw)

def check_sms_for_number(phone_number, chat_id, fetch_date=None):
    url = "https://mknetworkbd.com/API/api_handler_test.php"
    clean_number = phone_number.replace("+", "")

    if fetch_date is None:
        fetch_date = today_str()

    max_attempts = 300

    def search_in_date(search_date):
        """নির্দিষ্ট তারিখে নম্বরটির OTP খোঁজে — পেলে sms_text ফেরত দেয়, না পেলে None"""
        params = {'action': 'get_history', 'filter': 'all', 'page': '1', 'limit': '50', 'date': search_date}
        try:
            response = api_session.get(url, params=params)
            if response.status_code == 200:
                data = response.json()
                if is_session_expired(data):
                    relogin_and_retry()
                    return None
                if data.get('status') == 'success':
                    for item in data.get('data', []):
                        item_number = str(item.get('phone_number', '')).replace('+', '')
                        if item_number == clean_number:
                            raw_sms = item.get('full_sms_list')
                            sms_text = parse_sms_text(raw_sms)
                            if sms_text:
                                return sms_text
        except Exception as e:
            print(f"⚠️ search_in_date error ({search_date}): {e}")
        return None

    for attempt in range(max_attempts):
        if clean_number not in active_tracking:
            return

        sms_text = search_in_date(fetch_date)

        current_date = today_str()
        if not sms_text and current_date != fetch_date:
            sms_text = search_in_date(current_date)

        if sms_text:
            session = user_session_data.get(chat_id, {})
            srv_name = session.get("service", "CUSTOM")
            cnt_name = session.get("country", "Unknown")
            flag = session.get("flag", "🌍")
            user_range = session.get("range", "Unknown")

            otp = extract_otp(sms_text)
            escaped_sms = html.escape(sms_text)

            success_msg = (
                f"🟢 ⃟ ⃟ <b>OTP RECEIVED</b> ⃟ ⃟\n"
                f"﹌﹌﹌﹌﹌﹌﹌﹌﹌﹌﹌﹌﹌﹌﹌\n"
                f"╭─❖\n"
                f"│ <b>COUNTRY :</b> {flag} {cnt_name}\n"
                f"│ <b>SERVICE :</b> {srv_name}\n"
                f"│ <b>RANGE   :</b> <code>{user_range}</code>\n"
                f"│ <b>NUMBER  :</b> <code>{clean_number}</code>\n"
                f"│ <b>OTP     :</b> <code>{otp}</code>\n"
                f"╰────────────❖\n"
                f"│ <b>FULL SMS :</b>\n"
                f"<blockquote>{escaped_sms}</blockquote>\n"
                f"╰────────────❖"
            )

            otp_markup = InlineKeyboardMarkup(row_width=1)
            clean_otp = otp.replace(" ", "").replace("-", "")

            btn_copy_otp = make_copy_button(f"✂️ COPY OTP: {otp}", clean_otp)
            btn_panel = InlineKeyboardButton(text="━━👑 NUMBER PANEL 👑━━", url="https://t.me/nssnumber_bot")
            btn_dev = InlineKeyboardButton(text="━━🔥 BOT DEVELOPER 🔥━━", url="https://t.me/siyamchoowdhury1")

            otp_markup.add(btn_copy_otp, btn_panel, btn_dev)

            try:
                bot.send_message(chat_id, success_msg, parse_mode="HTML", reply_markup=otp_markup)
            except Exception as e:
                print(f"❌ OTP send error to {chat_id}: {e}")

            update_stats('otp')
            active_tracking.discard(clean_number)

            fwd_groups = load_data().get("forward_groups", [])
            for grp in fwd_groups:
                try:
                    bot.send_message(grp["chat_id"], success_msg, parse_mode="HTML", reply_markup=otp_markup)
                except Exception as e:
                    print(f"❌ Forward error to {grp['chat_id']}: {e}")
            return

        time.sleep(3)

    active_tracking.discard(clean_number)
    if user_last_number.get(chat_id) == clean_number:
        bot.send_message(chat_id, f"⚠️ নম্বর `{phone_number}` এর মেয়াদ শেষ।", parse_mode="Markdown")

def process_and_send_number(chat_id, user_range, srv_name="CUSTOM", cnt_name="Unknown"):
    is_joined, missing = check_force_join(chat_id)
    if not is_joined:
        send_force_join_message(chat_id, missing)
        return

    user_session_data[chat_id] = {
        "service": srv_name,
        "country": cnt_name,
        "flag": get_flag(cnt_name),
        "range": user_range
    }

    number_result = get_phone_number(user_range)
    
    if isinstance(number_result, str) and ("Failed" in number_result or "Error" in number_result):
        bot.send_message(chat_id, f"❌ সমস্যা হয়েছে:\n`{number_result}`", parse_mode="Markdown")
    else:
        update_stats('number')
        cleaned_new_number = number_result.replace("+", "")
        user_last_number[chat_id] = cleaned_new_number
        user_current_range[chat_id] = user_range
        active_tracking.add(cleaned_new_number)

        admin_link = load_data().get("otp_group_link", "https://t.me/")
        
        markup = InlineKeyboardMarkup(row_width=1)
        btn_number = make_copy_button(f"🇹🇬 {cleaned_new_number}", cleaned_new_number)
        btn_change_country = InlineKeyboardButton("Change Country", callback_data="main_menu")
        btn_new_number = InlineKeyboardButton("New number", callback_data="new_number")
        btn_new_2_number = InlineKeyboardButton("🔥 New 2 number", callback_data="new_2_number")
        btn_otp_group = InlineKeyboardButton("OTP Support Group", url=admin_link)
        
        markup.add(btn_number, btn_change_country, btn_new_number, btn_new_2_number, btn_otp_group)
        bot.send_message(chat_id, 'ㅤ', reply_markup=markup)
        
        threading.Thread(target=check_sms_for_number, args=(number_result, chat_id, today_str()), daemon=True).start()

# ================= ২টি নম্বর একসাথে (New 2 number) =================
def process_and_send_two_numbers(chat_id, user_range, srv_name="CUSTOM", cnt_name="Unknown"):
    """একসাথে ২টি নম্বর নিয়ে দেখায় এবং উভয়ের OTP ট্র্যাক করে।"""
    is_joined, missing = check_force_join(chat_id)
    if not is_joined:
        send_force_join_message(chat_id, missing)
        return

    user_session_data[chat_id] = {
        "service": srv_name,
        "country": cnt_name,
        "flag": get_flag(cnt_name),
        "range": user_range
    }

    results = [None, None]

    def fetch_num(idx):
        results[idx] = get_phone_number(user_range)

    t1 = threading.Thread(target=fetch_num, args=(0,), daemon=True)
    t2 = threading.Thread(target=fetch_num, args=(1,), daemon=True)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    num1 = results[0]
    num2 = results[1]

    success_nums = []
    error_msgs = []

    for n in [num1, num2]:
        if n and isinstance(n, str) and "Failed" not in n and "Error" not in n:
            success_nums.append(n)
        else:
            error_msgs.append(str(n))

    if not success_nums:
        bot.send_message(chat_id, f"❌ ২টি নম্বর নিতে সমস্যা হয়েছে:\n`{error_msgs}`", parse_mode="Markdown")
        return

    update_stats('number')
    if len(success_nums) == 2:
        update_stats('number')

    admin_link = load_data().get("otp_group_link", "https://t.me/")
    markup = InlineKeyboardMarkup(row_width=1)

    clean_nums = []
    for n in success_nums:
        cleaned = n.replace("+", "")
        clean_nums.append(cleaned)
        active_tracking.add(cleaned)

    user_current_range[chat_id] = user_range
    if clean_nums:
        user_last_number[chat_id] = clean_nums[-1]

    for cleaned in clean_nums:
        markup.add(make_copy_button(f"🇹🇬 {cleaned}", cleaned))

    btn_change_country = InlineKeyboardButton("Change Country", callback_data="main_menu")
    btn_new_number = InlineKeyboardButton("New number", callback_data="new_number")
    btn_new_2_number = InlineKeyboardButton("🔥 New 2 number", callback_data="new_2_number")
    btn_otp_group = InlineKeyboardButton("OTP Support Group", url=admin_link)

    markup.add(btn_change_country, btn_new_number, btn_new_2_number, btn_otp_group)

    msg_text = f"✅ <b>২টি নম্বর পাওয়া গেছে!</b>\nউভয় নম্বরের OTP ট্র্যাক করা হচ্ছে..."
    bot.send_message(chat_id, msg_text, reply_markup=markup, parse_mode="HTML")

    fetch_date = today_str()
    for n, cleaned in zip(success_nums, clean_nums):
        threading.Thread(target=check_sms_for_number, args=(n, chat_id, fetch_date), daemon=True).start()

# ================= মেনু ও ডিজাইন ফাংশন =================
def safe_send(chat_id, text, markup=None, message_id=None):
    try:
        if message_id:
            bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, reply_markup=markup, parse_mode="HTML")
        else:
            bot.send_message(chat_id, text, reply_markup=markup, parse_mode="HTML")
    except Exception as e:
        print(f"Edit error: {e}")

def get_main_menu_markup(user_id):
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    btn_get_num = telebot.types.KeyboardButton("📞 𝙶𝙴𝚃 𝙽𝚄𝙼𝙱𝙴𝚁")
    btn_custom = telebot.types.KeyboardButton("⚙️ 𝙲𝚄𝚂𝚃𝙾𝙼 𝚁𝙰𝙽𝙶𝙴")
    btn_new_num = telebot.types.KeyboardButton("🔁 𝙽𝙴𝚆 𝙽𝚄𝙼𝙱𝙴𝚁")
    btn_support = telebot.types.KeyboardButton("📞 𝚂𝚄𝙿𝙿𝙾𝚁𝚃 𝙸𝙽𝙱𝙾𝚇")
    
    markup.add(btn_get_num, btn_custom)
    markup.add(btn_new_num)
    markup.add(btn_support)
    if is_admin(user_id):
        markup.add(telebot.types.KeyboardButton("⚙️ ADMIN PANEL"))
    return markup

def show_support_inbox(chat_id):
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("🚀 সরাসরি মেসেজ দিন (Admin)", url="https://t.me/siyamchoowdhury1"))
    bot.send_message(chat_id, DEVELOPER_FOOTER.strip(), reply_markup=markup, parse_mode="HTML")

# --- ইউজার ফ্লো ---
def show_user_services(chat_id, message_id=None):
    data    = load_data()
    markup  = InlineKeyboardMarkup(row_width=2)
    buttons = []
    
    for srv_id, srv in data.get("services_data", {}).items():
        has_ranges = any(len(cnt.get("ranges", {})) > 0 for cnt in srv.get("countries", {}).values())
        if has_ranges:
            buttons.append(InlineKeyboardButton(text=f"📁 {srv['name']}", callback_data=f"usr_s|{srv_id}"))
    
    if buttons:
        markup.add(*buttons)
        text = "⬇️ <b>সার্ভিস সিলেক্ট করুন:</b>"
    else:
        text = "⚠️ বর্তমানে কোনো সার্ভিস এভেলেবেল নেই।"
        
    markup.row(InlineKeyboardButton("📋 My History", callback_data="my_history"))
    safe_send(chat_id, text, markup, message_id)

def show_user_countries(chat_id, srv_id, message_id=None):
    data     = load_data()
    srv_data = data.get("services_data", {}).get(srv_id)
    if not srv_data: return

    markup  = InlineKeyboardMarkup(row_width=2)
    buttons = []
    
    for cnt_id, cnt in srv_data.get("countries", {}).items():
        if len(cnt.get("ranges", {})) > 0:
            flag = get_flag(cnt['name'])
            buttons.append(InlineKeyboardButton(text=f"{flag} {cnt['name']}", callback_data=f"usr_c|{srv_id}|{cnt_id}"))
    
    if buttons:
        markup.add(*buttons)
        markup.add(InlineKeyboardButton("🔙 Back to Services", callback_data="back_to_user_services"))
        text = f"🌍 <b>দেশ সিলেক্ট করুন:</b>\nসার্ভিস: <code>{srv_data['name']}</code>"
    else:
        markup.add(InlineKeyboardButton("🔙 Back", callback_data="back_to_user_services"))
        text = "⚠️ এই সার্ভিসে এখনো কোনো দেশ অ্যাড করা হয়নি অথবা রেঞ্জ খালি।"

    safe_send(chat_id, text, markup, message_id)

def show_user_ranges(chat_id, srv_id, cnt_id, message_id=None):
    data     = load_data()
    srv_data = data.get("services_data", {}).get(srv_id)
    cnt_data = srv_data.get("countries", {}).get(cnt_id) if srv_data else None
    
    if not cnt_data: return

    markup  = InlineKeyboardMarkup(row_width=2)
    buttons = []
    for idx, (rng_id, rng_val) in enumerate(cnt_data.get("ranges", {}).items(), 1):
        buttons.append(InlineKeyboardButton(text=f"⚙️ Server {idx}", callback_data=f"usr_r|{srv_id}|{cnt_id}|{rng_id}"))

    if buttons:
        markup.add(*buttons)
        markup.add(InlineKeyboardButton("🔙 Back to Countries", callback_data=f"usr_s|{srv_id}"))
        text = f"🔢 <b>সার্ভার সিলেক্ট করুন:</b>\nদেশ: {cnt_data['name']}\nসার্ভিস: {srv_data['name']}"
    else:
        text = "⚠️ দুঃখিত, এই দেশের কোনো রেঞ্জ এখন এভেলেবেল নেই।"
        markup.add(InlineKeyboardButton("🔙 Back", callback_data=f"usr_s|{srv_id}"))

    safe_send(chat_id, text, markup, message_id)

def process_user_range(message):
    text = message.text.strip()
    if text in ["📞 𝙶𝙴𝚃 𝙽𝚄𝙼𝙱𝙴𝚁", "⚙️ 𝙲𝚄𝚂𝚃𝙾𝙼 𝚁𝙰𝙽𝙶𝙴", "🔁 𝙽𝙴𝚆 𝙽𝚄𝙼𝙱𝙴𝚁", "📞 𝚂𝚄𝙿𝙿𝙾𝚁𝚃 𝙸𝙽𝙱𝙾𝚇", "⚙️ ADMIN PANEL"]:
        handle_text_messages(message)
        return
    process_and_send_number(message.chat.id, text, srv_name="CUSTOM", cnt_name="Unknown")

OTP_PRICE = 0.5  # প্রতিটি OTP এর মূল্য (টাকায়)

# ================= এডমিন প্যানেল UI =================
def show_admin_panel(chat_id, message_id=None):
    data  = load_data()
    gs    = data.get("global_stats", {})
    today = today_str()
    td    = gs.get("daily", {}).get(today, {"otps": 0, "numbers": 0})
    today_income = round(td['otps'] * OTP_PRICE, 2)
    total_income = round(gs.get('total_otps', 0) * OTP_PRICE, 2)
    text  = (
        f"👑 <b>ADMIN PANEL</b> 👑\n━━━━━━━━━━━━━━━━━━\n"
        f"📅 <b>আজকে</b> ({today})\n"
        f"🔢 Numbers: <code>{td['numbers']}</code>  🔐 OTPs: <code>{td['otps']}</code>\n"
        f"💰 আজকের ইনকাম: <code>{today_income} ৳</code>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🌍 <b>সর্বমোট (All-Time)</b>\n"
        f"🔢 Numbers: <code>{gs.get('total_numbers', 0)}</code>  🔐 OTPs: <code>{gs.get('total_otps', 0)}</code>\n"
        f"💵 মোট ইনকাম: <code>{total_income} ৳</code>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👥 Total Users: <code>{len(data.get('users', {}))}</code>"
    )
    role = "👑 MAIN ADMIN"
    text = f"<b>{role}</b>\n" + text[text.index("\n")+1:]

    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton("📊 OTP হিস্ট্রি ও ইনকাম", callback_data="admin_otp_history"),
               InlineKeyboardButton("🛠️ Manage Services", callback_data="admin_manage_service"),
               InlineKeyboardButton("📢 Broadcast Message", callback_data="admin_broadcast"),
               InlineKeyboardButton("🔗 Group Settings", callback_data="admin_group_settings"),
               InlineKeyboardButton("📣 Force Join Settings", callback_data="admin_force_join"))
    if is_main_admin(chat_id):
        markup.add(InlineKeyboardButton("👤 Sub-Admin Management", callback_data="admin_sub_mgmt"))
    safe_send(chat_id, text, markup, message_id)

def show_otp_history(chat_id, message_id=None):
    from datetime import timedelta as td_delta
    data = load_data()
    gs   = data.get("global_stats", {})
    daily = gs.get("daily", {})

    bd_tz = timezone(timedelta(hours=6))
    today_dt = datetime.now(bd_tz)

    lines = []
    grand_otps = 0
    for i in range(7):
        day_dt  = today_dt - td_delta(days=i)
        day_key = day_dt.strftime("%Y-%m-%d")
        day_label = day_dt.strftime("%d %b")
        rec = daily.get(day_key, {"otps": 0, "numbers": 0})
        otps    = rec.get("otps", 0)
        numbers = rec.get("numbers", 0)
        income  = round(otps * OTP_PRICE, 2)
        grand_otps += otps
        marker = "📅" if i == 0 else "🗓️"
        lines.append(
            f"{marker} <b>{day_label}</b> ({'আজ' if i == 0 else f'{i} দিন আগে'})\n"
            f"   🔢 Numbers: <code>{numbers}</code>  🔐 OTPs: <code>{otps}</code>  💰 <code>{income} ৳</code>"
        )

    grand_income = round(grand_otps * OTP_PRICE, 2)
    text = (
        f"📊 <b>OTP হিস্ট্রি (শেষ ৭ দিন)</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        + "\n".join(lines) +
        f"\n━━━━━━━━━━━━━━━━━━\n"
        f"🧾 <b>৭ দিনের মোট OTP:</b> <code>{grand_otps}</code>\n"
        f"💵 <b>৭ দিনের মোট ইনকাম:</b> <code>{grand_income} ৳</code>\n"
        f"<i>(প্রতি OTP = {OTP_PRICE} ৳)</i>"
    )
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton("🔙 Back to Admin", callback_data="back_to_admin"))
    safe_send(chat_id, text, markup, message_id)

def show_sub_admin_panel(chat_id, message_id=None):
    """শুধু মেইন এডমিন দেখতে পারবে"""
    if not is_main_admin(chat_id):
        return
    data = load_data()
    sub_admins = data.get("sub_admins", [])

    lines = []
    if SUB_ADMIN_ID:
        lines.append(f"🔰 <code>{SUB_ADMIN_ID}</code> <i>(হার্ডকোডেড)</i>")

    markup = InlineKeyboardMarkup(row_width=1)
    for uid in sub_admins:
        lines.append(f"🔰 <code>{uid}</code>")
        markup.add(InlineKeyboardButton(f"❌ Remove {uid}", callback_data=f"del_sub|{uid}"))

    if not lines:
        lines.append("⚠️ এখনো কোনো Sub-Admin নেই।")

    text = (
        f"👤 <b>Sub-Admin Management</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        + "\n".join(lines) +
        f"\n━━━━━━━━━━━━━━━━━━\n"
        f"<i>Sub-Admin এডমিন প্যানেলের সব ফিচার ব্যবহার করতে পারবে কিন্তু নতুন Admin যোগ করতে পারবে না।</i>"
    )
    markup.add(InlineKeyboardButton("➕ নতুন Sub-Admin যোগ করুন", callback_data="add_sub_admin"))
    markup.add(InlineKeyboardButton("🔙 Back to Admin", callback_data="back_to_admin"))
    safe_send(chat_id, text, markup, message_id)

def process_add_sub_admin(message, msg_id):
    if not is_main_admin(message.chat.id):
        return
    if message.text == "/cancel":
        bot.delete_message(message.chat.id, message.message_id)
        return show_sub_admin_panel(message.chat.id, msg_id)
    try:
        new_uid = int(message.text.strip())
    except ValueError:
        bot.send_message(message.chat.id, "❌ সঠিক Telegram User ID দিন (শুধু নম্বর)।")
        return show_sub_admin_panel(message.chat.id, msg_id)
    if new_uid == ADMIN_ID:
        bot.send_message(message.chat.id, "❌ মেইন এডমিনকে সাব-এডমিন করা যাবে না।")
        return show_sub_admin_panel(message.chat.id, msg_id)
    data = load_data()
    sub_admins = data.setdefault("sub_admins", [])
    if new_uid in sub_admins:
        bot.send_message(message.chat.id, f"⚠️ <code>{new_uid}</code> ইতিমধ্যে Sub-Admin আছে।", parse_mode="HTML")
    else:
        sub_admins.append(new_uid)
        save_data(data)
        bot.send_message(message.chat.id, f"✅ <code>{new_uid}</code> Sub-Admin হিসেবে যোগ করা হয়েছে!", parse_mode="HTML")
    bot.delete_message(message.chat.id, message.message_id)
    show_sub_admin_panel(message.chat.id, msg_id)

def show_admin_services(chat_id, message_id=None):
    data   = load_data()
    markup = InlineKeyboardMarkup(row_width=1)
    for srv_id, srv in data.get("services_data", {}).items():
        markup.row(
            InlineKeyboardButton(text=f"📁 {srv['name']}", callback_data=f"adm_s|{srv_id}"),
            InlineKeyboardButton(text="🗑️ Delete", callback_data=f"del_srv_confirm|{srv_id}")
        )
    markup.add(InlineKeyboardButton("➕ Add Service", callback_data="add_srv"))
    markup.add(InlineKeyboardButton("🔙 Back to Admin", callback_data="back_to_admin"))
    safe_send(chat_id, "⚙️ <b>MANAGE SERVICES</b>\nSelect a service:", markup, message_id)

def show_admin_countries(chat_id, srv_id, message_id=None):
    data = load_data()
    srv = data.get("services_data", {}).get(srv_id)
    if not srv: return
    markup = InlineKeyboardMarkup(row_width=1)
    for cnt_id, cnt in srv.get("countries", {}).items():
        markup.row(
            InlineKeyboardButton(text=f"🌍 {cnt['name']}", callback_data=f"adm_c|{srv_id}|{cnt_id}"),
            InlineKeyboardButton(text="🗑️ Delete", callback_data=f"del_cnt_confirm|{srv_id}|{cnt_id}")
        )
    markup.add(InlineKeyboardButton("➕ Add Country", callback_data=f"add_cnt|{srv_id}"))
    markup.add(InlineKeyboardButton("🗑️ Delete This Service", callback_data=f"del_srv_confirm|{srv_id}"))
    markup.add(InlineKeyboardButton("🔙 Back to Services", callback_data="admin_manage_service"))
    safe_send(chat_id, f"📁 <b>{srv['name']}</b>\nSelect a country:", markup, message_id)

def show_admin_ranges(chat_id, srv_id, cnt_id, message_id=None):
    data = load_data()
    srv = data.get("services_data", {}).get(srv_id)
    if not srv: return
    cnt = srv.get("countries", {}).get(cnt_id)
    if not cnt: return
    markup = InlineKeyboardMarkup(row_width=1)
    for rng_id, rng_val in cnt.get("ranges", {}).items():
        markup.row(
            InlineKeyboardButton(text=f"🔢 {rng_val}", callback_data="ignore"),
            InlineKeyboardButton(text="❌ Remove", callback_data=f"del_rng|{srv_id}|{cnt_id}|{rng_id}")
        )
    markup.add(InlineKeyboardButton("➕ Add Range", callback_data=f"add_rng|{srv_id}|{cnt_id}"))
    markup.add(InlineKeyboardButton("🗑️ Delete This Country", callback_data=f"del_cnt_confirm|{srv_id}|{cnt_id}"))
    markup.add(InlineKeyboardButton("🔙 Back to Countries", callback_data=f"adm_s|{srv_id}"))
    safe_send(chat_id, f"🌍 <b>{cnt['name']}</b>\nExisting ranges are above:", markup, message_id)

def process_add_srv(message, msg_id):
    if message.text == "/cancel": 
        bot.delete_message(message.chat.id, message.message_id)
        return show_admin_services(message.chat.id, msg_id)
    data   = load_data()
    srv_id = "s_" + str(uuid.uuid4())[:8] 
    data.setdefault("services_data", {})[srv_id] = {"name": message.text.strip(), "countries": {}}
    save_data(data)
    bot.delete_message(message.chat.id, message.message_id)
    show_admin_services(message.chat.id, msg_id)

def process_add_cnt(message, srv_id, msg_id):
    if message.text == "/cancel": 
        bot.delete_message(message.chat.id, message.message_id)
        return show_admin_countries(message.chat.id, srv_id, msg_id)
    data = load_data()
    cnt_id = "c_" + str(uuid.uuid4())[:8]
    if srv_id in data.get("services_data", {}):
        data["services_data"][srv_id]["countries"][cnt_id] = {"name": message.text.strip(), "ranges": {}}
        save_data(data)
    bot.delete_message(message.chat.id, message.message_id)
    show_admin_countries(message.chat.id, srv_id, msg_id)

def process_add_rng(message, srv_id, cnt_id, msg_id):
    if message.text == "/cancel": 
        bot.delete_message(message.chat.id, message.message_id)
        return show_admin_ranges(message.chat.id, srv_id, cnt_id, msg_id)
    data = load_data()
    rng_id = "r_" + str(uuid.uuid4())[:8]
    try:
        data["services_data"][srv_id]["countries"][cnt_id]["ranges"][rng_id] = message.text.strip()
        save_data(data)
    except: pass
    bot.delete_message(message.chat.id, message.message_id)
    show_admin_ranges(message.chat.id, srv_id, cnt_id, msg_id)

def process_broadcast(message, msg_id):
    if message.text == "/cancel": 
        bot.delete_message(message.chat.id, message.message_id)
        return show_admin_panel(message.chat.id, msg_id)
    safe_send(message.chat.id, "⏳ <b>Broadcasting...</b>", None, msg_id)
    threading.Thread(target=run_broadcast, args=(message.chat.id, message, msg_id), daemon=True).start()

def run_broadcast(chat_id, original_message, msg_id):
    data    = load_data()
    users   = list(data.get("users", {}).keys())
    success = 0
    for u in users:
        try:
            bot.copy_message(chat_id=int(u), from_chat_id=chat_id, message_id=original_message.message_id)
            success += 1
            time.sleep(0.05) 
        except: pass
    bot.send_message(chat_id, f"✅ Broadcast Done! Sent to {success} users.")
    show_admin_panel(chat_id)

def get_group_settings_menu():
    data = load_data()
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton("🔗 Set OTP Group Link", callback_data="set_main_otp_link"))
    markup.add(InlineKeyboardButton("➕ Add Forward Group", callback_data="add_fwd_group"))
    for grp in data.get("forward_groups", []):
        markup.add(InlineKeyboardButton(f"⚙️ Remove {grp['chat_id']}", callback_data=f"delgrp_{grp['chat_id']}"))
    markup.add(InlineKeyboardButton("🔙 Back to Admin", callback_data="back_to_admin"))
    return markup

def process_set_otp_link(message, msg_id):
    if message.text == "/cancel": 
        bot.delete_message(message.chat.id, message.message_id)
        return safe_send(message.chat.id, "⚙️ <b>GROUP SETTINGS</b>", get_group_settings_menu(), msg_id)
    data = load_data()
    data["otp_group_link"] = message.text.strip()
    save_data(data)
    bot.delete_message(message.chat.id, message.message_id)
    safe_send(message.chat.id, "✅ <b>Link Updated!</b>", get_group_settings_menu(), msg_id)

def process_add_fwd_group(message, msg_id):
    if message.text == "/cancel": 
        bot.delete_message(message.chat.id, message.message_id)
        return safe_send(message.chat.id, "⚙️ <b>GROUP SETTINGS</b>", get_group_settings_menu(), msg_id)
    data = load_data()
    data.setdefault("forward_groups", []).append({"chat_id": message.text.strip(), "buttons": []})
    save_data(data)
    bot.delete_message(message.chat.id, message.message_id)
    safe_send(message.chat.id, "✅ <b>Group Added!</b>", get_group_settings_menu(), msg_id)

def get_force_join_menu():
    data        = load_data()
    is_enabled  = data.get("force_join_enabled", False)
    status_text = "🟢 ENABLED" if is_enabled else "🔴 DISABLED"
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton(f"Toggle: {status_text}", callback_data="toggle_force_join"))
    for idx, link in enumerate(data.get("force_join_channels", [])):
        markup.add(InlineKeyboardButton(f"❌ Remove: {link}", callback_data=f"delfjc_{idx}"))
    markup.add(InlineKeyboardButton("➕ Add Channel", callback_data="add_fjc"))
    markup.add(InlineKeyboardButton("🔙 Back to Admin", callback_data="back_to_admin"))
    return markup

def process_add_fjc(message, msg_id):
    if message.text == "/cancel": 
        bot.delete_message(message.chat.id, message.message_id)
        return safe_send(message.chat.id, "📣 <b>FORCE JOIN SETTINGS</b>", get_force_join_menu(), msg_id)
    data = load_data()
    raw = message.text.strip()
    try:
        int(raw)
        channel_entry = raw
    except ValueError:
        if not raw.startswith('@'):
            channel_entry = '@' + raw
        else:
            channel_entry = raw
    data.setdefault("force_join_channels", []).append(channel_entry)
    save_data(data)
    bot.delete_message(message.chat.id, message.message_id)
    safe_send(message.chat.id, f"✅ <b>Channel Added:</b> <code>{channel_entry}</code>", get_force_join_menu(), msg_id)

# ================= ইউজার ইন্টারঅ্যাকশন =================
@bot.message_handler(commands=['stats'])
def cmd_stats(message):
    if not is_admin(message.from_user.id):
        return
    data  = load_data()
    gs    = data.get("global_stats", {})
    today = today_str()
    td    = gs.get("daily", {}).get(today, {"otps": 0, "numbers": 0})
    today_income = round(td['otps'] * OTP_PRICE, 2)
    total_income = round(gs.get('total_otps', 0) * OTP_PRICE, 2)
    text = (
        f"📊 <b>STATS</b>\n━━━━━━━━━━━━━━━━━━\n"
        f"📅 <b>আজকে</b> ({today})\n"
        f"🔢 Numbers: <code>{td['numbers']}</code>\n"
        f"🔐 OTPs: <code>{td['otps']}</code>\n"
        f"💰 আজকের ইনকাম: <code>{today_income} ৳</code>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🌍 <b>সর্বমোট (All-Time)</b>\n"
        f"🔢 Numbers: <code>{gs.get('total_numbers', 0)}</code>\n"
        f"🔐 OTPs: <code>{gs.get('total_otps', 0)}</code>\n"
        f"💵 মোট ইনকাম: <code>{total_income} ৳</code>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👥 Total Users: <code>{len(data.get('users', {}))}</code>\n"
        f"<i>(প্রতি OTP = {OTP_PRICE} ৳)</i>"
    )
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("📊 বিস্তারিত হিস্ট্রি", callback_data="admin_otp_history"))
    bot.send_message(message.chat.id, text, parse_mode="HTML", reply_markup=markup)

@bot.message_handler(commands=['start', 'help', 'menu'])
def send_welcome(message):
    add_user(message.chat.id)
    
    if message.chat.type in ['group', 'supergroup']:
        remove_kb = telebot.types.ReplyKeyboardRemove()
        bot.reply_to(message, "👋 Private চ্যাটে বট ব্যবহার করুন: @nssnumber_bot", reply_markup=remove_kb)
        return
    
    is_joined, missing = check_force_join(message.chat.id)
    if not is_joined:
        send_force_join_message(message.chat.id, missing)
        return
        
    markup = get_main_menu_markup(message.from_user.id)
    
    welcome_text = (
        "👋𓆩𓆩𝚆𝙴𝙻𝙲𝙾𝙼𝙴 𝚃𝙾 ℕ𝕊 𝔽𝕠𝕝𝕝𝕠𝕨𝕖𝕣 𝚂𝙴𝚁𝚅𝙸𝙲𝙴𓆪𓆪\n"
        "﹌﹌﹌﹌﹌﹌﹌﹌﹌﹌﹌﹌﹌﹌﹌﹌\n"
        "🤖 ℕ𝕊 𝔽𝕠𝕝𝕝𝕠𝕨𝕖𝕣 𝙽𝚄𝙼𝙱𝙴𝚁 𝙱𝙾𝚃 এ আপনাকে স্বাগতম!\n\n"
        "﹌﹌﹌﹌﹌﹌﹌﹌﹌﹌﹌﹌﹌﹌﹌﹌\n"
        "🕷 𝙿𝙾𝚆𝙴𝚁𝙴𝙳 𝙱𝚈 𝑺𝑰𝒀𝑨𝑴 𝑪𝑯𝑶𝑾𝑫𝑯𝑼𝑹𝒀ᯓᡣ𐭩"
    )
    
    bot.reply_to(message, welcome_text, reply_markup=markup, parse_mode="HTML")

@bot.message_handler(func=lambda message: True)
def handle_text_messages(message):
    add_user(message.chat.id)
    text = message.text.strip() if message.text else ""
    chat_id = message.chat.id

    if message.chat.type in ['group', 'supergroup']:
        return

    if text == "⚙️ ADMIN PANEL" and is_admin(message.from_user.id):
        show_admin_panel(message.chat.id)
        
    elif text == "📞 𝙶𝙴𝚃 𝙽𝚄𝙼𝙱𝙴𝚁":
        show_user_services(message.chat.id)
        
    elif text == "⚙️ 𝙲𝚄𝚂𝚃𝙾𝙼 𝚁𝙰𝙽𝙶𝙴":
        msg = bot.send_message(message.chat.id, "⚙️ PLEASE ENTER YOUR CUSTOM RANGE(S): (e.g., 22890XXX)")
        bot.register_next_step_handler(msg, process_user_range)
        
    elif text == "🔁 𝙽𝙴𝚆 𝙽𝚄𝙼𝙱𝙴𝚁":
        uid = message.from_user.id
        now = time.time()
        last_fetch = number_cooldowns.get(uid, 0)
        
        if now - last_fetch < 5: 
            wait = int(5 - (now - last_fetch))
            bot.send_message(chat_id, f"⏳ দয়া করে {wait} সেকেন্ড অপেক্ষা করুন...")
            return

        saved_range = user_current_range.get(chat_id)
        
        if not saved_range:
            bot.send_message(chat_id, "⚠️ <b>কোনো পূর্বের তথ্য পাওয়া যায়নি!</b>\nপ্রথমে '📞 𝙶𝙴𝚃 𝙽𝚄𝙼𝙱𝙴𝚁' থেকে একটি নম্বর নিন।", parse_mode="HTML")
            return

        number_cooldowns[uid] = now
        bot.send_message(chat_id, "🔄 <b>নতুন নম্বর নেওয়া হচ্ছে...</b>", parse_mode="HTML")
        
        session = user_session_data.get(chat_id, {})
        srv_name = session.get("service", "CUSTOM")
        cnt_name = session.get("country", "Unknown")
        
        threading.Thread(
            target=process_and_send_number, 
            args=(chat_id, saved_range, srv_name, cnt_name), 
            daemon=True
        ).start()
        
    elif text == "📞 𝚂𝚄𝙿𝙿𝙾𝚁𝚃 𝙸𝙽𝙱𝙾𝚇":
        show_support_inbox(message.chat.id)
        
    else:
        if text and ("X" in text.upper() or text.isdigit()):
            process_and_send_number(message.chat.id, text, srv_name="CUSTOM", cnt_name="Unknown")

# ================= কলব্যাক হ্যান্ডলার =================
@bot.callback_query_handler(func=lambda call: True)
def handle_query(call):
    chat_id = call.message.chat.id
    msg_id = call.message.message_id
    
    if call.data.startswith("docopy|"):
        value = call.data[7:] 
        bot.answer_callback_query(call.id)
        bot.send_message(chat_id, f"📋 কপি করুন:\n<code>{html.escape(value)}</code>", parse_mode="HTML")
        return

    if call.data == "check_join_status":
        def do_join_check():
            time.sleep(1)
            is_joined, missing = check_force_join(chat_id)
            if is_joined:
                bot.answer_callback_query(call.id, "✅ জয়েন নিশ্চিত হয়েছে!")
                try:
                    bot.delete_message(chat_id, msg_id)
                except Exception:
                    pass
                markup = get_main_menu_markup(call.from_user.id)
                bot.send_message(chat_id, f"✅ <b>ধন্যবাদ! আপনি সফলভাবে জয়েন হয়েছেন।</b>\nএবার বট ব্যবহার করতে পারেন।{DEVELOPER_FOOTER}", reply_markup=markup, parse_mode="HTML")
            else:
                bot.answer_callback_query(call.id, "⚠️ আপনি এখনো চ্যানেলে জয়েন করেননি! জয়েন করে আবার চেষ্টা করুন।", show_alert=True)
        threading.Thread(target=do_join_check, daemon=True).start()
        return

    if call.data == "main_menu":
        bot.answer_callback_query(call.id)
        markup = get_main_menu_markup(chat_id)
        bot.send_message(chat_id, "🌍 **মেইন মেনু:**", reply_markup=markup, parse_mode="Markdown")
        
    elif call.data == "new_number":
        uid = call.from_user.id
        now = time.time()
        last_fetch = number_cooldowns.get(uid, 0)
        
        if now - last_fetch < 5: 
            wait = int(5 - (now - last_fetch))
            bot.answer_callback_query(call.id, f"⏳ দয়া করে {wait} সেকেন্ড অপেক্ষা করুন...", show_alert=True)
            return

        saved_range = user_current_range.get(chat_id)
        if not saved_range:
            bot.answer_callback_query(call.id, "⚠️ কোনো পূর্বের তথ্য পাওয়া যায়নি! প্রথমে একটি নম্বর নিন।", show_alert=True)
            return

        number_cooldowns[uid] = now
        bot.answer_callback_query(call.id, "🔄 নতুন নম্বর নেওয়া হচ্ছে...")
        bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text="🔄 <b>নতুন নম্বর নেওয়া হচ্ছে...</b>", parse_mode="HTML")
        
        session = user_session_data.get(chat_id, {})
        srv_name = session.get("service", "CUSTOM")
        cnt_name = session.get("country", "Unknown")
        
        threading.Thread(
            target=process_and_send_number, 
            args=(chat_id, saved_range, srv_name, cnt_name), 
            daemon=True
        ).start()

    elif call.data == "new_2_number":
        uid = call.from_user.id
        now = time.time()
        last_fetch = number_cooldowns.get(uid, 0)
        
        if now - last_fetch < 5: 
            wait = int(5 - (now - last_fetch))
            bot.answer_callback_query(call.id, f"⏳ দয়া করে {wait} সেকেন্ড অপেক্ষা করুন...", show_alert=True)
            return

        saved_range = user_current_range.get(chat_id)
        if not saved_range:
            bot.answer_callback_query(call.id, "⚠️ কোনো পূর্বের তথ্য পাওয়া যায়নি! প্রথমে একটি নম্বর নিন।", show_alert=True)
            return

        number_cooldowns[uid] = now
        bot.answer_callback_query(call.id, "🔥 ২টি নতুন নম্বর নেওয়া হচ্ছে...")
        try:
            bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text="🔥 <b>২টি নতুন নম্বর নেওয়া হচ্ছে...</b>", parse_mode="HTML")
        except Exception:
            pass
        
        session = user_session_data.get(chat_id, {})
        srv_name = session.get("service", "CUSTOM")
        cnt_name = session.get("country", "Unknown")
        
        threading.Thread(
            target=process_and_send_two_numbers, 
            args=(chat_id, saved_range, srv_name, cnt_name), 
            daemon=True
        ).start()

    elif call.data == "back_to_user_services":
        bot.answer_callback_query(call.id)
        show_user_services(chat_id, msg_id)

    elif call.data.startswith("usr_s|"):
        bot.answer_callback_query(call.id)
        srv_id = call.data.split("|")[1]
        show_user_countries(chat_id, srv_id, msg_id)

    elif call.data.startswith("usr_c|"):
        bot.answer_callback_query(call.id)
        _, srv_id, cnt_id = call.data.split("|")
        show_user_ranges(chat_id, srv_id, cnt_id, msg_id)

    elif call.data.startswith("usr_r|"):
        bot.answer_callback_query(call.id)
        _, srv_id, cnt_id, rng_id = call.data.split("|")
        data = load_data()
        try:
            srv_name = data["services_data"][srv_id]["name"]
            cnt_name = data["services_data"][srv_id]["countries"][cnt_id]["name"]
            rng_val = data["services_data"][srv_id]["countries"][cnt_id]["ranges"][rng_id]
            
            bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text="🔄 <b>নম্বর নেওয়া হচ্ছে...</b>", parse_mode="HTML")
            threading.Thread(
                target=process_and_send_number, 
                args=(chat_id, rng_val, srv_name, cnt_name), 
                daemon=True
            ).start()
            
        except KeyError:
            bot.send_message(chat_id, "⚠️ রেঞ্জটি ডাটাবেসে খুঁজে পাওয়া যায়নি।")

    elif call.data == "my_history":
        bot.answer_callback_query(call.id, "এই ফিচারটি শীঘ্রই যুক্ত করা হবে!", show_alert=True)

    elif not is_admin(chat_id):
        return bot.answer_callback_query(call.id, "Access Denied!", show_alert=True)

    elif call.data == "back_to_admin":
        bot.answer_callback_query(call.id)
        show_admin_panel(chat_id, msg_id)

    elif call.data == "admin_otp_history":
        bot.answer_callback_query(call.id)
        show_otp_history(chat_id, msg_id)

    elif call.data == "admin_sub_mgmt":
        if not is_main_admin(chat_id):
            return bot.answer_callback_query(call.id, "❌ শুধু মেইন এডমিন এটি ব্যবহার করতে পারবে!", show_alert=True)
        bot.answer_callback_query(call.id)
        show_sub_admin_panel(chat_id, msg_id)

    elif call.data == "add_sub_admin":
        if not is_main_admin(chat_id):
            return bot.answer_callback_query(call.id, "❌ শুধু মেইন এডমিন এটি ব্যবহার করতে পারবে!", show_alert=True)
        bot.answer_callback_query(call.id)
        safe_send(chat_id, "👤 <b>নতুন Sub-Admin এর Telegram User ID দিন</b>\n(বা /cancel লিখুন বাতিল করতে):", None, msg_id)
        bot.register_next_step_handler(call.message, process_add_sub_admin, msg_id)

    elif call.data.startswith("del_sub|"):
        if not is_main_admin(chat_id):
            return bot.answer_callback_query(call.id, "❌ শুধু মেইন এডমিন এটি ব্যবহার করতে পারবে!", show_alert=True)
        bot.answer_callback_query(call.id)
        uid_str = call.data.split("|")[1]
        try:
            uid = int(uid_str)
        except ValueError:
            uid = uid_str
        data = load_data()
        if uid in data.get("sub_admins", []):
            data["sub_admins"].remove(uid)
            save_data(data)
            bot.answer_callback_query(call.id, f"✅ {uid} সরিয়ে দেওয়া হয়েছে!")
        show_sub_admin_panel(chat_id, msg_id)

    elif call.data == "admin_manage_service":
        bot.answer_callback_query(call.id)
        show_admin_services(chat_id, msg_id)

    elif call.data == "add_srv":
        bot.answer_callback_query(call.id)
        safe_send(chat_id, "📝 <b>নতুন সার্ভিসের নাম লিখুন</b> (বা /cancel):", None, msg_id)
        bot.register_next_step_handler(call.message, process_add_srv, msg_id)

    elif call.data.startswith("adm_s|"):
        bot.answer_callback_query(call.id)
        srv_id = call.data.split("|")[1]
        show_admin_countries(chat_id, srv_id, msg_id)

    elif call.data.startswith("add_cnt|"):
        bot.answer_callback_query(call.id)
        srv_id = call.data.split("|")[1]
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Cancel", callback_data=f"adm_s|{srv_id}"))
        safe_send(chat_id, "🌍 <b>Send Country Name</b> (or /cancel):", markup, msg_id)
        bot.register_next_step_handler(call.message, process_add_cnt, srv_id, msg_id)

    elif call.data.startswith("adm_c|"):
        bot.answer_callback_query(call.id)
        _, srv_id, cnt_id = call.data.split("|")
        show_admin_ranges(chat_id, srv_id, cnt_id, msg_id)

    elif call.data.startswith("del_srv_confirm|"):
        bot.answer_callback_query(call.id)
        srv_id = call.data.split("|")[1]
        data = load_data()
        srv_name = data.get("services_data", {}).get(srv_id, {}).get("name", "?")
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(
            InlineKeyboardButton("✅ হ্যাঁ, ডিলিট করো", callback_data=f"del_srv|{srv_id}"),
            InlineKeyboardButton("❌ না, বাতিল করো", callback_data=f"adm_s|{srv_id}")
        )
        safe_send(chat_id, f"⚠️ <b>আপনি কি নিশ্চিত?</b>\n\n🗑️ সার্ভিস <b>'{srv_name}'</b> এবং এর সমস্ত কান্ট্রি ও রেঞ্জ মুছে যাবে!", markup, msg_id)

    elif call.data.startswith("del_srv|"):
        bot.answer_callback_query(call.id)
        srv_id = call.data.split("|")[1]
        data = load_data()
        srv_name = data.get("services_data", {}).get(srv_id, {}).get("name", "?")
        data.get("services_data", {}).pop(srv_id, None)
        save_data(data)
        safe_send(chat_id, f"✅ <b>'{srv_name}'</b> সার্ভিস ডিলিট হয়েছে।", None, msg_id)
        show_admin_services(chat_id)

    elif call.data.startswith("del_cnt_confirm|"):
        bot.answer_callback_query(call.id)
        _, srv_id, cnt_id = call.data.split("|")
        data = load_data()
        cnt_name = data.get("services_data", {}).get(srv_id, {}).get("countries", {}).get(cnt_id, {}).get("name", "?")
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(
            InlineKeyboardButton("✅ হ্যাঁ, ডিলিট করো", callback_data=f"del_cnt|{srv_id}|{cnt_id}"),
            InlineKeyboardButton("❌ না, বাতিল করো", callback_data=f"adm_c|{srv_id}|{cnt_id}")
        )
        safe_send(chat_id, f"⚠️ <b>আপনি কি নিশ্চিত?</b>\n\n🗑️ কান্ট্রি <b>'{cnt_name}'</b> এবং এর সমস্ত রেঞ্জ মুছে যাবে!", markup, msg_id)

    elif call.data.startswith("del_cnt|"):
        bot.answer_callback_query(call.id)
        _, srv_id, cnt_id = call.data.split("|")
        data = load_data()
        cnt_name = data.get("services_data", {}).get(srv_id, {}).get("countries", {}).get(cnt_id, {}).get("name", "?")
        try:
            del data["services_data"][srv_id]["countries"][cnt_id]
            save_data(data)
        except KeyError:
            pass
        safe_send(chat_id, f"✅ <b>'{cnt_name}'</b> কান্ট্রি ডিলিট হয়েছে।", None, msg_id)
        show_admin_countries(chat_id, srv_id)

    elif call.data.startswith("del_rng|"):
        bot.answer_callback_query(call.id)
        _, srv_id, cnt_id, rng_id = call.data.split("|")
        data = load_data()
        rng_val = data.get("services_data", {}).get(srv_id, {}).get("countries", {}).get(cnt_id, {}).get("ranges", {}).get(rng_id, "?")
        try:
            del data["services_data"][srv_id]["countries"][cnt_id]["ranges"][rng_id]
            save_data(data)
        except KeyError:
            pass
        bot.answer_callback_query(call.id, f"✅ রেঞ্জ '{rng_val}' মুছে গেছে!")
        show_admin_ranges(chat_id, srv_id, cnt_id, msg_id)

    elif call.data.startswith("add_rng|"):
        bot.answer_callback_query(call.id)
        _, srv_id, cnt_id = call.data.split("|")
        markup = InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Cancel", callback_data=f"adm_c|{srv_id}|{cnt_id}"))
        safe_send(chat_id, "🔢 <b>Send Range:</b>\nExample: <code>88017XXX</code> (or /cancel)", markup, msg_id)
        bot.register_next_step_handler(call.message, process_add_rng, srv_id, cnt_id, msg_id)

    elif call.data == "admin_broadcast":
        bot.answer_callback_query(call.id)
        safe_send(chat_id, "📝 যে মেসেজটি ব্রডকাস্ট করতে চান সেটি টাইপ করে পাঠান (বা /cancel):", None, msg_id)
        bot.register_next_step_handler(call.message, process_broadcast, msg_id)

    elif call.data == "admin_group_settings":
        bot.answer_callback_query(call.id)
        safe_send(chat_id, "⚙️ <b>GROUP SETTINGS</b>", get_group_settings_menu(), msg_id)

    elif call.data == "set_main_otp_link":
        bot.answer_callback_query(call.id)
        safe_send(chat_id, "🔗 গ্রুপের ইনভাইট লিংক দিন (বা /cancel):", None, msg_id)
        bot.register_next_step_handler(call.message, process_set_otp_link, msg_id)

    elif call.data == "add_fwd_group":
        bot.answer_callback_query(call.id)
        safe_send(chat_id, "⚙️ ফরোয়ার্ড গ্রুপের Chat ID দিন (যেমন: -100123... বা /cancel):", None, msg_id)
        bot.register_next_step_handler(call.message, process_add_fwd_group, msg_id)

    elif call.data.startswith("delgrp_"):
        bot.answer_callback_query(call.id)
        grp_id = call.data.split("_")[1]
        data = load_data()
        data["forward_groups"] = [g for g in data.get("forward_groups", []) if str(g["chat_id"]) != str(grp_id)]
        save_data(data)
        safe_send(chat_id, "⚙️ <b>GROUP SETTINGS</b>", get_group_settings_menu(), msg_id)

    elif call.data == "admin_force_join":
        bot.answer_callback_query(call.id)
        safe_send(chat_id, "📣 <b>FORCE JOIN SETTINGS</b>", get_force_join_menu(), msg_id)

    elif call.data == "toggle_force_join":
        bot.answer_callback_query(call.id)
        data = load_data()
        data["force_join_enabled"] = not data.get("force_join_enabled", False)
        save_data(data)
        safe_send(chat_id, "📣 <b>FORCE JOIN SETTINGS</b>", get_force_join_menu(), msg_id)

    elif call.data == "add_fjc":
        bot.answer_callback_query(call.id)
        safe_send(chat_id, "📣 চ্যানেলের Username দিন\nউদাহরণ: <code>@MyChannel</code> বা <code>MyChannel</code> (বা /cancel):", None, msg_id)
        bot.register_next_step_handler(call.message, process_add_fjc, msg_id)

    elif call.data.startswith("delfjc_"):
        bot.answer_callback_query(call.id)
        idx = int(call.data.split("_")[1])
        data = load_data()
        channels = data.get("force_join_channels", [])
        if 0 <= idx < len(channels):
            channels.pop(idx)
        save_data(data)
        safe_send(chat_id, "📣 <b>FORCE JOIN SETTINGS</b>", get_force_join_menu(), msg_id)

    elif call.data == "ignore":
        bot.answer_callback_query(call.id)

# ================= অটো লগইন শিডিউলার =================
def auto_login_scheduler():
    """প্রতি ৩০ মিনিট পর পর প্রিভেন্টিভ সেশন রিফ্রেশ করবে।"""
    while True:
        time.sleep(30 * 60)
        print("🔄 প্রিভেন্টিভ সেশন রিফ্রেশ করা হচ্ছে...")
        with _login_lock:
            perform_api_login()

# ================= বট রান =================
if __name__ == "__main__":
    perform_api_login()
    
    threading.Thread(target=auto_login_scheduler, daemon=True).start()
    
    bot.delete_webhook(drop_pending_updates=True)
    time.sleep(1)
    
    print("বট চলছে... (Automated API Login ও Session ম্যানেজমেন্ট সহ)")
    
    while True:
        try:
            bot.infinity_polling(timeout=30, long_polling_timeout=20)
        except Exception as e:
            print(f"⚠️ বট বন্ধ হয়ে গেছে: {e}")
            print("🔄 ৫ সেকেন্ড পরে আবার চালু হচ্ছে...")
            time.sleep(5)
            try:
                perform_api_login()
            except Exception as login_err:
                print(f"❌ লগইন এরর: {login_err}")
            continue
