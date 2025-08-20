# Tolid.py
# المتطلبات: 
# python-telegram-bot==13.15
# psycopg2-binary
# تثبيت: pip install python-telegram-bot==13.15 psycopg2-binary
# تشغيل: python Tolid.py
# الضبط عبر المتغيرات البيئية: BOT_TOKEN, BOT_OWNER_ID, PGHOST, PGPORT, PGUSER, PGPASSWORD, PGDATABASE

import os
import time
import random
import string
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime
import logging
from collections import deque
import threading
from io import StringIO
from telegram import Update
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, ConversationHandler, CallbackContext
from functools import wraps
import psycopg2
from psycopg2 import sql, errors
import secrets

# ----------------------
# إعدادات PostgreSQL
# ----------------------
POSTGRES_CONFIG = {
    "host": os.getenv("PGHOST", "localhost"),
    "port": os.getenv("PGPORT", "5432"),
    "user": os.getenv("PGUSER", "postgres"),
    "password": os.getenv("PGPASSWORD", "your_password"),
    "database": os.getenv("PGDATABASE", "postgres")
}

# تحسين أداء PostgreSQL
POSTGRES_PERFORMANCE_SETTINGS = {
    "shared_buffers": "1GB",  # 25% من ذاكرة النظام الموصى بها
    "work_mem": "16MB",       # ذاكرة لكل عملية ترتيب/هاش
    "maintenance_work_mem": "256MB",  # للعمليات الإدارية
    "checkpoint_timeout": "30min",    # تقليل تكرار نقاط التفتيش
    "max_wal_size": "2GB",            # حجم أكبر لملفات WAL
    "min_wal_size": "1GB",
    "checkpoint_completion_target": "0.9",
    "random_page_cost": "1.1",        # مفيد للسيرفرات SSD
    "effective_cache_size": "3GB",    # تقدير للذاكرة المتاحة للتخزين المؤقت
}

# ----------------------
# إعدادات التوليد والبرنامج
# ----------------------
PREFIX = "1BJWap1sAU"           # بادئة ثابتة (10 حروف)
TOTAL_LENGTH = 344              # طول السلسلة المطلوب بالكامل
END_CHAR = "="                  # يجب أن تنتهي به
MIDDLE_LEN = TOTAL_LENGTH - len(PREFIX) - len(END_CHAR)  # طول الجزء العشوائي
ALLOWED_CHARS = string.ascii_letters + string.digits + "-_"  # مجموعة الأحرف المستخدمة
DEFAULT_BATCH = 50000           # حجم الدفعة الافتراضي (أكبر لتحسين الأداء)
MAX_ALLOWED = 10_000_000_000    # حد أقصى 10 مليار سجل
MAX_PENDING_BATCHES = 100       # زيادة الحد الأقصى للدفعات المعلقة
PARTITION_SIZE = 100_000_000    # حجم كل partition (100 مليون سجل)

# حالات المحادثة
ASK_COUNT, ASK_DBNAME, ASK_TABLENAME = range(3)

# إعداد النظام
MAX_WORKERS = max(1, mp.cpu_count() * 2)  # استخدام ضعف عدد الأنوية
CHUNK_SIZE = 10000             # حجم chunk للإدخال

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
performance_stats = {
    'total_generated': 0,
    'total_time': 0.0,
    'avg_speed': 0.0
}
task_history = deque(maxlen=200)
stats_lock = threading.Lock()

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
# دوال مساعدة PostgreSQL
# ----------------------
def create_postgres_connection(dbname=None):
    """إنشاء اتصال بقاعدة بيانات PostgreSQL"""
    config = POSTGRES_CONFIG.copy()
    if dbname:
        config["database"] = dbname
    conn = psycopg2.connect(**config)
    
    # تطبيق إعدادات الأداء على الاتصال
    conn.autocommit = False
    cur = conn.cursor()
    try:
        cur.execute("SET work_mem = '16MB'")
        cur.execute("SET maintenance_work_mem = '256MB'")
        cur.execute("SET random_page_cost = 1.1")
    except:
        pass
    cur.close()
    
    return conn

def create_database(dbname):
    """إنشاء قاعدة بيانات جديدة مع تحسينات الأداء"""
    try:
        conn = create_postgres_connection()
        conn.autocommit = True
        cur = conn.cursor()
        
        # التحقق من وجود قاعدة البيانات
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,))
        exists = cur.fetchone()
        
        if not exists:
            cur.execute(sql.SQL("CREATE DATABASE {} WITH ENCODING 'UTF8'").format(sql.Identifier(dbname)))
            logger.info(f"تم إنشاء قاعدة البيانات: {dbname}")
            
            # تطبيق إعدادات الأداء على قاعدة البيانات الجديدة
            conn_db = create_postgres_connection(dbname)
            conn_db.autocommit = True
            cur_db = conn_db.cursor()
            
            for setting, value in POSTGRES_PERFORMANCE_SETTINGS.items():
                try:
                    cur_db.execute(sql.SQL("ALTER DATABASE {} SET {} TO {}").format(
                        sql.Identifier(dbname),
                        sql.Identifier(setting),
                        sql.Literal(value)
                    ))
                except Exception as e:
                    logger.warning(f"تعذر تطبيق إعداد {setting}: {e}")
            
            cur_db.close()
            conn_db.close()
        
        cur.close()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"خطأ في إنشاء قاعدة البيانات: {e}")
        return False

def create_table(dbname, tablename):
    """إنشاء جدول بسيط مع قيود فريدة مناسبة (بدون تجزئة)"""
    try:
        conn = create_postgres_connection(dbname)
        cur = conn.cursor()

        # إنشاء جدول عادي مع مفتاح أساسي على id وقيد فريد على session_code
        cur.execute(sql.SQL(
            """
            CREATE TABLE IF NOT EXISTS {} (
                id BIGSERIAL PRIMARY KEY,
                session_code TEXT NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        ).format(sql.Identifier(tablename)))

        # فهرس إضافي اختياري على session_code غير ضروري لأن UNIQUE ينشئ فهرساً ضمنياً
        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as e:
        logger.error(f"خطأ في إنشاء الجدول: {e}")
        return False

def get_row_count(dbname, tablename):
    """الحصول على عدد الصفوف (تقديري) لتجنب تكلفة COUNT(*) على جداول ضخمة"""
    try:
        conn = create_postgres_connection(dbname)
        cur = conn.cursor()

        # استخدام تقدير reltuples من pg_class
        cur.execute(
            "SELECT COALESCE(reltuples, 0)::BIGINT FROM pg_class WHERE oid = to_regclass(%s)",
            (f"public.{tablename}",)
        )
        row = cur.fetchone()
        count = int(row[0]) if row and row[0] is not None else 0

        cur.close()
        conn.close()
        return count
    except Exception as e:
        logger.error(f"خطأ في الحصول على عدد الصفوف: {e}")
        return 0

# ----------------------
# دوال مساعدة التوليد
# ----------------------
def gen_one():
    """مولد لسلسلة واحدة باستخدام secrets للأمان القوي"""
    middle_part = ''.join(secrets.choice(ALLOWED_CHARS) for _ in range(MIDDLE_LEN))
    return PREFIX + middle_part + END_CHAR

def generate_batch(batch_size):
    """توليد دفعة من السلاسل باستخدام مولد أكثر كفاءة"""
    generated = set()
    while len(generated) < batch_size:
        # استخدام تقنية أكثر كفاءة لتجنب التكرار
        session = gen_one()
        if session not in generated:
            generated.add(session)
    return list(generated)

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

def monitor_performance(delta_inserted, delta_time):
    """تحديث إحصاءات الأداء وإرجاع السرعة اللحظية خلال الفترة"""
    elapsed = max(1e-6, delta_time)
    speed = delta_inserted / elapsed

    with stats_lock:
        performance_stats['total_generated'] += delta_inserted
        performance_stats['total_time'] += elapsed
        if performance_stats['total_time'] > 0:
            performance_stats['avg_speed'] = performance_stats['total_generated'] / performance_stats['total_time']

    return speed, elapsed

def bulk_insert_sessions(dbname, tablename, sessions):
    """إدخال دفعات كبيرة باستخدام COPY FROM STDIN للأداء الأمثل"""
    if not sessions:
        return 0
    
    conn = None
    try:
        conn = create_postgres_connection(dbname)
        cur = conn.cursor()
        
        # استخدام COPY لأداء أفضل
        f = StringIO()
        for session in sessions:
            f.write(f"{session}\n")
        
        f.seek(0)
        cur.copy_expert(
            sql.SQL("COPY {} (session_code) FROM STDIN WITH CSV").format(
                sql.Identifier(tablename)
            ), 
            f
        )
        
        conn.commit()
        inserted = len(sessions)
        
        cur.close()
        conn.close()
        return inserted
        
    except errors.UniqueViolation:
        # في حالة وجود تكرار، نستخدم الإدخال مع تجاهل التكرار
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        return safe_bulk_insert(dbname, tablename, sessions)
    except Exception as e:
        logger.error(f"خطأ في الإدراج الجماعي: {e}")
        try:
            if conn:
                conn.rollback()
        except Exception:
            pass
        return safe_bulk_insert(dbname, tablename, sessions)

def safe_bulk_insert(dbname, tablename, sessions):
    """إدخال آمن مع التعامل مع التكرارات"""
    if not sessions:
        return 0
    
    try:
        conn = create_postgres_connection(dbname)
        cur = conn.cursor()
        
        # تقسيم الجلسات إلى chunks
        inserted = 0
        for i in range(0, len(sessions), CHUNK_SIZE):
            chunk = sessions[i:i + CHUNK_SIZE]
            
            cur.execute(
                sql.SQL("""
                    INSERT INTO {} (session_code) 
                    SELECT * FROM UNNEST(%s::text[]) 
                    ON CONFLICT (session_code) DO NOTHING
                """).format(sql.Identifier(tablename)),
                [chunk]
            )
            inserted += cur.rowcount
        
        conn.commit()
        cur.close()
        conn.close()
        return inserted
        
    except Exception as e:
        logger.error(f"خطأ في الإدراج الآمن: {e}")
        return 0

# ----------------------
# الوظيفة الرئيسية للتوليد المتوازي
# ----------------------
def generate_parallel(target_count, dbname, tablename, chat_id, context, progress_message_id, cancel_event):
    """توليد متوازي مُحسّن مع تحديث نفس رسالة التقدم كل 60 ثانية"""
    start_time = time.time()
    total_inserted = 0

    # التحقق من وجود قاعدة البيانات والجدول
    try:
        if not create_database(dbname):
            context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=progress_message_id,
                text=f"❌ فشل في إنشاء/الاتصال بقاعدة البيانات: {dbname}"
            )
            return 0
        if not create_table(dbname, tablename):
            context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=progress_message_id,
                text=f"❌ فشل في إنشاء/الاتصال بالجدول: {tablename}"
            )
            return 0
    except Exception as e:
        logger.exception(f"خطأ في تهيئة قاعدة البيانات/الجدول: {e}")
        try:
            context.bot.edit_message_text(chat_id=chat_id, message_id=progress_message_id, text=f"حدث خطأ أثناء التهيئة: {e}")
        except Exception:
            pass
        return 0

    # التحقق من عدد الصفوف الموجودة
    existing_count = get_row_count(dbname, tablename)
    if existing_count >= target_count:
        try:
            context.bot.edit_message_text(
                chat_id=chat_id,
                message_id=progress_message_id,
                text=f"الجدول يحتوي بالفعل على {existing_count} جلسة (>= المطلوب)."
            )
        except Exception:
            pass
        return existing_count

    remaining = target_count - existing_count
    batch_size = min(DEFAULT_BATCH, max(10000, remaining // 100))
    last_report_time = time.time()
    last_report_inserted = 0

    # حد أقصى ديناميكي للدفعات المعلقة لتقليل الضغط على الذاكرة
    dynamic_max_pending = min(MAX_PENDING_BATCHES, MAX_WORKERS * 2)

    try:
        with ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
            pending = set()
            submitted = 0
            total_batches = (remaining + batch_size - 1) // batch_size

            # إرسال الدفعات الأولية
            for _ in range(min(dynamic_max_pending, total_batches)):
                if submitted >= total_batches:
                    break
                pending.add(executor.submit(generate_batch, batch_size))
                submitted += 1

            # معالجة الدفعات
            while (pending or submitted < total_batches) and not cancel_event.is_set():
                if not pending and submitted < total_batches:
                    for _ in range(min(dynamic_max_pending, total_batches - submitted)):
                        pending.add(executor.submit(generate_batch, batch_size))
                        submitted += 1

                if not pending:
                    break

                done, _ = wait(pending, return_when=FIRST_COMPLETED, timeout=30)
                for fut in done:
                    pending.discard(fut)
                    try:
                        batch = fut.result(timeout=30)
                        if batch:
                            inserted = bulk_insert_sessions(dbname, tablename, batch)
                            total_inserted += inserted

                            # تحديث التقدم كل 60 ثانية في نفس الرسالة
                            now = time.time()
                            should_report = (now - last_report_time >= 60) or (existing_count + total_inserted >= target_count)
                            if should_report:
                                current_total = existing_count + total_inserted
                                perc = min(100.0, (current_total / target_count) * 100)
                                delta_inserted = total_inserted - last_report_inserted
                                delta_time = now - last_report_time
                                speed, _ = monitor_performance(delta_inserted, delta_time)
                                try:
                                    context.bot.edit_message_text(
                                        chat_id=chat_id,
                                        message_id=progress_message_id,
                                        text=(
                                            f"{progress_bar(perc)}\n"
                                            f"التقدم: {current_total}/{target_count}\n"
                                            f"السرعة: {speed:.0f} جلسة/ثانية\n"
                                            f"الوقت المنقضي: {int(now - start_time)} ثانية"
                                        ),
                                        parse_mode="Markdown"
                                    )
                                except Exception as e:
                                    logger.debug(f"تعذر تحديث رسالة التقدم: {e}")

                                last_report_time = now
                                last_report_inserted = total_inserted

                    except Exception as e:
                        logger.error(f"خطأ في معالجة الدفعة: {e}")

    except Exception as e:
        logger.exception(f"خطأ في generate_parallel: {e}")
        try:
            context.bot.edit_message_text(chat_id=chat_id, message_id=progress_message_id, text=f"حدث خطأ أثناء التوليد: {e}")
        except Exception:
            pass

    finally:
        # الإبلاغ عن النتيجة النهائية عبر تعديل نفس الرسالة
        final_count = existing_count + total_inserted
        total_time = time.time() - start_time

        try:
            if cancel_event.is_set():
                context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=progress_message_id,
                    text=f"تم إلغاء العملية. تم حفظ {final_count} جلسة.")
                log_activity("CANCELLED", f"أوقف المستخدم بعد توليد {total_inserted} جلسة")
            else:
                context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=progress_message_id,
                    text=(
                        f"✅ انتهى التوليد. تم حفظ {final_count} جلسة في:\n"
                        f"قاعدة البيانات: `{dbname}`\nالجدول: `{tablename}`\n"
                        f"الوقت: {total_time:.0f} ثانية"
                    ),
                    parse_mode="Markdown"
                )
                log_activity("COMPLETED", f"تم توليد {total_inserted} جلسة في {total_time:.2f} ثانية")
        except Exception:
            pass

        if chat_id in active_tasks:
            del active_tasks[chat_id]

    return final_count

# ----------------------
# معالجات أوامر التليجرام (نفس الكود السابق)
# ----------------------
@owner_only
def start(update: Update, context: CallbackContext):
    log_activity("START", "بدأ المحادثة")
    update.message.reply_text("أدخل عدد الجلسات المراد توليدها (مثلاً: 1000000):")
    return ASK_COUNT

@owner_only
def ask_dbname(update: Update, context: CallbackContext):
    txt = update.message.text.strip()
    try:
        count = int(txt)
        if count <= 0:
            update.message.reply_text("أدخل رقماً موجباً أكبر من صفر.")
            return ASK_COUNT
        if count > MAX_ALLOWED:
            update.message.reply_text(f"الحد الأقصى المسموح هنا هو {MAX_ALLOWED} (يمكنك تعديل الكود إن احتجت أكثر).")
            return ASK_COUNT

        context.user_data['target_count'] = count
        log_activity("SET_COUNT", f"حدد العدد: {count}")
        update.message.reply_text("حسناً. الآن أرسل اسم قاعدة البيانات التي تريد حفظ الجلسات فيها:")
        return ASK_DBNAME
    except ValueError:
        update.message.reply_text("الرجاء إرسال رقم صحيح (عدد صحيح).")
        return ASK_COUNT

@owner_only
def ask_tablename(update: Update, context: CallbackContext):
    dbname = update.message.text.strip()
    if not dbname:
        update.message.reply_text("الرجاء إرسال اسم قاعدة بيانات صالح.")
        return ASK_DBNAME
        
    context.user_data['dbname'] = dbname
    log_activity("SET_DBNAME", f"حدد قاعدة البيانات: {dbname}")
    update.message.reply_text("ممتاز. الآن أرسل اسم الجدول الذي تريد حفظ الجلسات فيه:")
    return ASK_TABLENAME

@owner_only
def begin_generation(update: Update, context: CallbackContext):
    tablename = update.message.text.strip()
    target = context.user_data.get('target_count')
    dbname = context.user_data.get('dbname')
    
    if not target or not dbname:
        update.message.reply_text("لم أتلق جميع المعلومات المطلوبة. أعد التشغيل بإرسال /start.")
        return ConversationHandler.END

    chat_id = update.effective_chat.id
    if chat_id in active_tasks:
        update.message.reply_text("هناك مهمة توليد قائمة بالعمل بالفعل في هذه المحادثة. أرسل /cancel لإيقافها أولاً.")
        return ConversationHandler.END

    update.message.reply_text(f"سيتم توليد {target} جلسة وحفظها في:\nقاعدة البيانات: `{dbname}`\nالجدول: `{tablename}`\n\nابتدأت العملية الآن...", parse_mode="Markdown")

    # إنشاء رسالة تقدم أولية ليتم تعديلها لاحقاً كل 60 ثانية
    progress_message = update.message.reply_text("بدء العملية... سيتم تحديث هذه الرسالة كل 60 ثانية.")

    cancel_event = threading.Event()

    active_tasks[chat_id] = {
        'start_time': time.time(),
        'target_count': target,
        'dbname': dbname,
        'tablename': tablename,
        'cancel_event': cancel_event,
        'progress_message_id': progress_message.message_id
    }
    log_activity("START_GENERATION", f"الهدف: {target}, قاعدة البيانات: {dbname}, الجدول: {tablename}")

    # بدء التوليد في خيط منفصل
    thread = threading.Thread(
        target=generate_parallel,
        args=(target, dbname, tablename, chat_id, context, progress_message.message_id, cancel_event),
        daemon=True
    )
    thread.start()

    update.message.reply_text("العملية بدأت في الخلفية. ستصلك تحديثات تقدّم من حين لآخر. لإلغاء العملية أرسل /cancel.")
    return ConversationHandler.END

@owner_only
def cancel(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    if chat_id in active_tasks:
        active_tasks[chat_id]['cancel_event'].set()
        log_activity("CANCEL_REQUEST", "طلب إلغاء المهمة")
        update.message.reply_text("تم إرسال أمر الإلغاء، جاري إيقاف العملية...")
    else:
        update.message.reply_text("لا توجد عملية جارية للإلغاء.")
    return ConversationHandler.END

@owner_only
def status(update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    if chat_id in active_tasks:
        task = active_tasks[chat_id]
        elapsed = time.time() - task['start_time']
        
        current_count = get_row_count(task['dbname'], task['tablename'])
        
        update.message.reply_text(
            f"حالة المهمة:\n"
            f"الهدف: {task['target_count']} جلسة\n"
            f"قاعدة البيانات: {task['dbname']}\n"
            f"الجدول: {task['tablename']}\n"
            f"المحفوظ حتى الآن: {current_count} جلسة\n"
            f"الوقت المنقضي: {elapsed:.0f} ثانية\n\n"
            f"لإلغاء المهمة أرسل /cancel."
        )
    else:
        update.message.reply_text("لا توجد عملية توليد جارية الآن.")
    log_activity("STATUS_CHECK", "طلب حالة المهمة")

@owner_only
def dashboard(update: Update, context: CallbackContext):
    active_count = len(active_tasks)
    active_info = "\n".join([
        f"- Chat {cid}: {task['target_count']} جلسة إلى {task['dbname']}.{task['tablename']}"
        for cid, task in active_tasks.items()
    ]) if active_tasks else "لا توجد مهام نشطة"

    with stats_lock:
        perf_info = (
            f"إجمالي الجلسات المولدة: {performance_stats['total_generated']}\n"
            f"إجمالي وقت التوليد: {performance_stats['total_time']:.2f} ثانية\n"
            f"متوسط السرعة: {performance_stats['avg_speed']:.2f} جلسة/ثانية"
        )

    recent_activities = "\n".join(list(task_history)[-8:]) if task_history else "لا توجد أنشطة مسجلة"

    update.message.reply_text(
        f"📊 لوحة التحكم\n\n"
        f"🔹 المهام النشطة ({active_count}):\n{active_info}\n\n"
        f"📈 إحصائيات الأداء:\n{perf_info}\n\n"
        f"📝 آخر الأنشطة:\n{recent_activities}"
    )
    log_activity("DASHBOARD_VIEW", "عرض لوحة التحكم")

def alert_check(context: CallbackContext):
    for chat_id, task in list(active_tasks.items()):
        elapsed = time.time() - task['start_time']
        if elapsed > 3600:
            try:
                context.bot.send_message(chat_id=chat_id, text="⚠️ تنبيه: المهمة تستغرق وقتاً طويلاً. قد ترغب في التحقق من التقدم أو إلغاء المهمة.")
            except Exception:
                pass
            logger.warning(f"مهمة طويلة المدة في chat {chat_id}")

# ----------------------
# نقطة الدخول
# ----------------------
def main():
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")

    # التحقق من الإعدادات
    if BOT_OWNER_ID == 123456789:
        logger.error("❗ لم تقم بتعيين معرف المالك الصحيح في BOT_OWNER_ID")
        return

    if POSTGRES_CONFIG["password"] == "your_password":
        logger.error("❗ لم تقم بتعيين كلمة مرور PostgreSQL الصحيحة")
        return

    if not BOT_TOKEN:
        logger.error("❗ لم تقم بتعيين متغير البيئة BOT_TOKEN")
        return

    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    job_queue = updater.job_queue

    conv = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            ASK_COUNT: [MessageHandler(Filters.text & ~Filters.command, ask_dbname)],
            ASK_DBNAME: [MessageHandler(Filters.text & ~Filters.command, ask_tablename)],
            ASK_TABLENAME: [MessageHandler(Filters.text & ~Filters.command, begin_generation)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )

    dp.add_handler(conv)
    dp.add_handler(CommandHandler('cancel', cancel))
    dp.add_handler(CommandHandler('status', status))
    dp.add_handler(CommandHandler('dashboard', dashboard))
    # تمت إضافة /start كمدخل في ConversationHandler أعلاه، لا داعي لإضافته مرة أخرى

    job_queue.run_repeating(alert_check, interval=1800, first=0)

    logger.info("Bot started successfully")
    print("Bot started. Press Ctrl+C to stop.")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
