# Tolid_Functions.py
# دوال توليد وحفظ الجلسات في PostgreSQL - الدوال الوظيفية فقط
# تم فصل هذه الدوال من Tolid.py الأصلي

import os
import time
import random
import string
import math
import base64
import multiprocessing as mp
from concurrent.futures import ProcessPoolExecutor, wait, FIRST_COMPLETED
from datetime import datetime
import logging
from collections import deque
import threading
from io import StringIO
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
DEFAULT_BATCH = int(os.getenv("DEFAULT_BATCH", "50000"))           # حجم الدفعة الافتراضي (قابل للتهيئة)
MAX_ALLOWED = 10_000_000_000    # حد أقصى 10 مليار سجل
MAX_PENDING_BATCHES = int(os.getenv("MAX_PENDING_BATCHES", "100"))       # الحد الأقصى للدفعات المعلقة (قابل للتهيئة)
PARTITION_SIZE = 100_000_000    # حجم كل partition (لم يعد مستخدماً إذا تم استخدام HASH)
HASH_PARTITIONS = int(os.getenv("HASH_PARTITIONS", "64"))  # عدد أقسام HASH الافتراضي

# إعداد النظام
MAX_WORKERS = int(os.getenv("MAX_WORKERS", str(max(1, mp.cpu_count() * 2))))  # استخدام ضعف عدد الأنوية أو من المتغيرات البيئية
CHUNK_SIZE = 10000             # حجم chunk للإدخال

# إعداد التسجيل
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# متغيرات الحالة
performance_stats = {
    'total_generated': 0,
    'total_time': 0.0,
    'avg_speed': 0.0
}
task_history = deque(maxlen=200)
stats_lock = threading.Lock()

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
            
            # تطبيق إعدادات الأداء
            for setting, value in POSTGRES_PERFORMANCE_SETTINGS.items():
                try:
                    cur_db.execute(f"ALTER DATABASE {dbname} SET {setting} = '{value}'")
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
    """إنشاء جدول الجلسات مع تحسينات الأداء والتقسيم"""
    try:
        conn = create_postgres_connection(dbname)
        conn.autocommit = True
        cur = conn.cursor()
        
        # إنشاء الجدول الرئيسي مع HASH partitioning
        create_table_sql = sql.SQL("""
            CREATE TABLE IF NOT EXISTS {} (
                id BIGSERIAL,
                session_code TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) PARTITION BY HASH (session_code)
        """).format(sql.Identifier(tablename))
        
        cur.execute(create_table_sql)
        
        # إنشاء الأقسام (partitions)
        for i in range(HASH_PARTITIONS):
            partition_name = f"{tablename}_part_{i}"
            try:
                partition_sql = sql.SQL("""
                    CREATE TABLE IF NOT EXISTS {} PARTITION OF {} 
                    FOR VALUES WITH (MODULUS {}, REMAINDER {})
                """).format(
                    sql.Identifier(partition_name),
                    sql.Identifier(tablename),
                    sql.Literal(HASH_PARTITIONS),
                    sql.Literal(i)
                )
                cur.execute(partition_sql)
            except errors.DuplicateTable:
                pass  # القسم موجود بالفعل
        
        # إنشاء فهرس فريد على session_code
        try:
            index_sql = sql.SQL("CREATE UNIQUE INDEX IF NOT EXISTS {} ON {} (session_code)").format(
                sql.Identifier(f"idx_{tablename}_session_code"),
                sql.Identifier(tablename)
            )
            cur.execute(index_sql)
        except Exception as e:
            logger.warning(f"تعذر إنشاء الفهرس: {e}")
        
        cur.close()
        conn.close()
        logger.info(f"تم إنشاء الجدول {tablename} مع {HASH_PARTITIONS} قسم")
        return True
        
    except Exception as e:
        logger.error(f"خطأ في إنشاء الجدول: {e}")
        return False

def get_row_count(dbname, tablename):
    """الحصول على عدد الصفوف في الجدول"""
    try:
        conn = create_postgres_connection(dbname)
        cur = conn.cursor()
        
        # استخدام تقدير سريع للجداول الكبيرة
        cur.execute(sql.SQL("""
            SELECT 
                CASE 
                    WHEN reltuples > 1000000 THEN reltuples::bigint
                    ELSE (SELECT COUNT(*) FROM {})
                END as estimated_count
            FROM pg_class 
            WHERE relname = %s
        """).format(sql.Identifier(tablename)), (tablename,))
        
        result = cur.fetchone()
        count = result[0] if result else 0
        
        cur.close()
        conn.close()
        return int(count)
        
    except Exception as e:
        logger.error(f"خطأ في حساب الصفوف: {e}")
        return 0

# ----------------------
# دوال التوليد
# ----------------------
def gen_one():
    """توليد جلسة واحدة عشوائية"""
    s = ''.join(random.choices(ALLOWED_CHARS, k=MIDDLE_LEN + 10))
    middle_part = s[:MIDDLE_LEN]
    return PREFIX + middle_part + END_CHAR

def generate_batch(batch_size):
    """توليد دفعة من السلاسل بسرعة عالية دون فحص تكرار محلي (الاعتماد على UNIQUE في القاعدة)."""
    return [gen_one() for _ in range(batch_size)]

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

def generate_parallel(target_count, dbname, tablename, chat_id, context, progress_message_id, cancel_event):
    """العملية الرئيسية للتوليد المتوازي مع تحديث التقدم"""
    start_time = time.time()
    
    # إنشاء قاعدة البيانات والجدول إذا لم يكونا موجودين
    if not create_database(dbname):
        try:
            context.bot.edit_message_text(chat_id=chat_id, message_id=progress_message_id, text="خطأ في إنشاء قاعدة البيانات")
        except Exception:
            pass
        return 0
    
    if not create_table(dbname, tablename):
        try:
            context.bot.edit_message_text(chat_id=chat_id, message_id=progress_message_id, text="خطأ في إنشاء الجدول")
        except Exception:
            pass
        return 0

    # التحقق من العدد الحالي
    existing_count = get_row_count(dbname, tablename)
    total_inserted = 0
    
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
                        f"✅ اكتمل التوليد!\n\n"
                        f"📊 النتائج:\n"
                        f"• الهدف: {target_count} جلسة\n"
                        f"• المحفوظ: {final_count} جلسة\n"
                        f"• الوقت الإجمالي: {int(total_time)} ثانية\n"
                        f"• السرعة المتوسطة: {final_count/total_time:.0f} جلسة/ثانية"
                    )
                )
                log_activity("COMPLETED", f"اكتملت عملية التوليد: {final_count} جلسة في {total_time:.1f} ثانية")
        except Exception:
            pass

        return final_count

def alert_check(context):
    """فحص التنبيهات للمهام طويلة المدى"""
    # هذه الدالة تحتاج إلى active_tasks من البوت الرئيسي
    # سيتم استدعاؤها من البوت الموحد
    pass

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
        performance_stats['total_time'] = 0.0
        performance_stats['avg_speed'] = 0.0