# UnifiedBot.py
# البوت الموحد - الواجهة التفاعلية لجميع وظائف التوليد والفحص
# يستدعي الوظائف من Tolid_Functions.py و SessionChecker_Functions.py

import os
import time
import threading
from datetime import datetime
import logging
from collections import deque
from functools import wraps

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, Filters, 
    ConversationHandler, CallbackContext, CallbackQueryHandler
)

# استيراد الدوال الوظيفية
try:
    import Tolid_Functions as tolid
    TOLID_AVAILABLE = True
except ImportError as e:
    print(f"تحذير: لا يمكن استيراد Tolid_Functions: {e}")
    TOLID_AVAILABLE = False

try:
    import SessionChecker_Functions as checker
    CHECKER_AVAILABLE = True
except ImportError as e:
    print(f"تحذير: لا يمكن استيراد SessionChecker_Functions: {e}")
    CHECKER_AVAILABLE = False

# ----------------------
# الإعدادات العامة
# ----------------------
# حالات المحادثة
(ASK_MODE, ASK_COUNT, ASK_DBNAME, ASK_TABLENAME, 
 ADD_BOT_TOKEN, ASK_FILE_PATH, CONFIRM_ACTION) = range(7)

# إعداد التسجيل
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# مصادقة المالك
BOT_OWNER_ID = int(os.getenv("BOT_OWNER_ID", "123456789"))

# متغيرات الحالة الموحدة
active_tasks = {}
unified_stats = {
    'tolid_sessions': 0,
    'checked_sessions': 0,
    'valid_sessions': 0,
    'total_operations': 0
}
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
# الواجهة الرئيسية
# ----------------------
@owner_only
def start(update: Update, context: CallbackContext):
    """الواجهة الرئيسية الموحدة"""
    keyboard = []
    
    # قسم Tolid (توليد وحفظ)
    if TOLID_AVAILABLE:
        keyboard.append([
            InlineKeyboardButton("💾 توليد وحفظ (Tolid)", callback_data="mode_tolid")
        ])
    
    # أقسام فحص الجلسات
    if CHECKER_AVAILABLE:
        keyboard.extend([
            [
                InlineKeyboardButton("🔍 فحص Telethon", callback_data="mode_telethon"),
                InlineKeyboardButton("🔍 فحص Pyrogram", callback_data="mode_pyrogram")
            ],
            [
                InlineKeyboardButton("📁 فحص ملف محفوظ", callback_data="mode_file_check")
            ]
        ])
    
    # إدارة البوتات
    if CHECKER_AVAILABLE:
        keyboard.append([
            InlineKeyboardButton("🤖 إدارة بوتات الفحص", callback_data="manage_bots")
        ])
    
    # لوحة التحكم
    keyboard.append([
        InlineKeyboardButton("📊 لوحة التحكم الشاملة", callback_data="dashboard")
    ])
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    # إحصائيات سريعة
    stats_text = ""
    if TOLID_AVAILABLE:
        tolid_stats = tolid.get_performance_stats()
        stats_text += f"💾 Tolid: {tolid_stats['total_generated']} جلسة مولدة\n"
    
    if CHECKER_AVAILABLE:
        checker_stats = checker.get_performance_stats()
        checking_bots = checker.get_checking_bots()
        stats_text += f"🔍 Checker: {checker_stats['total_valid']} جلسة صالحة\n"
        stats_text += f"🤖 بوتات الفحص: {len(checking_bots)}\n"
    
    update.message.reply_text(
        f"🏠 **مركز التحكم الموحد**\n\n"
        f"مرحباً بك في النظام الموحد لتوليد وفحص الجلسات!\n\n"
        f"📊 **الإحصائيات السريعة:**\n{stats_text}\n"
        f"اختر العملية التي تريد تنفيذها:",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )
    
    if TOLID_AVAILABLE:
        tolid.log_activity("UNIFIED_START", "بدء استخدام النظام الموحد")
    elif CHECKER_AVAILABLE:
        checker.log_activity("UNIFIED_START", "بدء استخدام النظام الموحد")
    
    return ASK_MODE

def button_handler(update: Update, context: CallbackContext):
    """معالج الأزرار التفاعلية"""
    query = update.callback_query
    query.answer()
    
    if query.data.startswith("mode_"):
        mode = query.data.replace("mode_", "")
        context.user_data['mode'] = mode
        
        if mode == "tolid":
            return handle_tolid_mode(query, context)
        elif mode in ["telethon", "pyrogram"]:
            return handle_checker_mode(query, context, mode)
        elif mode == "file_check":
            return handle_file_check_mode(query, context)
    
    elif query.data == "manage_bots":
        return handle_bot_management(query, context)
    
    elif query.data == "dashboard":
        return handle_unified_dashboard(query, context)
    
    elif query.data.startswith("action_"):
        return handle_action_buttons(query, context)
    
    elif query.data == "back_to_main":
        # العودة للقائمة الرئيسية
        context.user_data.clear()
        return start(update, context)
    
    elif query.data == "cancel":
        query.edit_message_text("❌ تم الإلغاء.")
        return ConversationHandler.END
    
    return ASK_MODE

# ----------------------
# معالجات الأنماط المختلفة
# ----------------------
def handle_tolid_mode(query, context):
    """معالج نمط Tolid (توليد وحفظ)"""
    if not TOLID_AVAILABLE:
        query.edit_message_text("❌ وحدة Tolid غير متاحة.")
        return ConversationHandler.END
    
    query.edit_message_text(
        "💾 **نمط Tolid - توليد وحفظ الجلسات**\n\n"
        "سيتم توليد الجلسات وحفظها في قاعدة بيانات PostgreSQL.\n\n"
        "كم جلسة تريد توليدها؟\n"
        "أرسل رقماً (مثال: 1000000)",
        parse_mode="Markdown"
    )
    return ASK_COUNT

def handle_checker_mode(query, context, session_type):
    """معالج نمط فحص الجلسات"""
    if not CHECKER_AVAILABLE:
        query.edit_message_text("❌ وحدة فحص الجلسات غير متاحة.")
        return ConversationHandler.END
    
    # التحقق من توفر المكتبة المطلوبة
    if session_type == "telethon" and not checker.is_telethon_available():
        query.edit_message_text("❌ مكتبة Telethon غير مثبتة. يرجى تثبيتها أولاً.")
        return ConversationHandler.END
    elif session_type == "pyrogram" and not checker.is_pyrogram_available():
        query.edit_message_text("❌ مكتبة Pyrogram غير مثبتة. يرجى تثبيتها أولاً.")
        return ConversationHandler.END
    
    # التحقق من وجود بوتات فحص
    checking_bots = checker.get_checking_bots()
    if not checking_bots:
        query.edit_message_text(
            "⚠️ **لا توجد بوتات فحص مضافة!**\n\n"
            "يجب إضافة بوت فحص واحد على الأقل قبل البدء.\n"
            "استخدم 'إدارة بوتات الفحص' لإضافة بوت.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🤖 إضافة بوت فحص", callback_data="manage_bots")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main")]
            ])
        )
        return ASK_MODE
    
    query.edit_message_text(
        f"🔍 **فحص جلسات {session_type.title()}**\n\n"
        f"العملية ستبدأ فوراً وتستمر حتى الإيقاف.\n"
        f"ستصلك الجلسات الصالحة في رسائل منفصلة.\n\n"
        f"🤖 بوتات الفحص المتاحة: {len(checking_bots)}\n\n"
        f"هل تريد البدء؟",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ ابدأ الآن", callback_data=f"action_start_check_{session_type}")],
            [InlineKeyboardButton("❌ إلغاء", callback_data="cancel")]
        ])
    )
    return ASK_MODE

def handle_file_check_mode(query, context):
    """معالج نمط فحص الملفات"""
    if not CHECKER_AVAILABLE:
        query.edit_message_text("❌ وحدة فحص الجلسات غير متاحة.")
        return ConversationHandler.END
    
    # التحقق من وجود بوتات فحص
    checking_bots = checker.get_checking_bots()
    if not checking_bots:
        query.edit_message_text(
            "⚠️ لا توجد بوتات فحص مضافة! يجب إضافة بوت فحص أولاً.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🤖 إضافة بوت فحص", callback_data="manage_bots")],
                [InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main")]
            ])
        )
        return ASK_MODE
    
    query.edit_message_text(
        "📁 **فحص ملف الجلسات**\n\n"
        "أرسل مسار الملف الذي يحتوي على الجلسات المراد فحصها.\n"
        "يجب أن يكون كل سطر يحتوي على جلسة واحدة.\n\n"
        "مثال: `/home/user/sessions.txt`",
        parse_mode="Markdown"
    )
    return ASK_FILE_PATH

def handle_bot_management(query, context):
    """معالج إدارة بوتات الفحص"""
    if not CHECKER_AVAILABLE:
        query.edit_message_text("❌ وحدة إدارة البوتات غير متاحة.")
        return ConversationHandler.END
    
    checking_bots = checker.get_checking_bots()
    bots_list = ""
    
    if checking_bots:
        for i, bot in enumerate(checking_bots):
            status_emoji = "🟢" if bot['status'] == 'active' else "🔴"
            bots_list += f"{i+1}. {status_emoji} @{bot['username']}\n"
    else:
        bots_list = "لا توجد بوتات مضافة"
    
    keyboard = [
        [InlineKeyboardButton("➕ إضافة بوت فحص", callback_data="action_add_bot")],
    ]
    
    if checking_bots:
        keyboard.append([InlineKeyboardButton("🗑️ حذف بوت", callback_data="action_remove_bot")])
    
    keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main")])
    
    query.edit_message_text(
        f"🤖 **إدارة بوتات الفحص**\n\n"
        f"البوتات المضافة ({len(checking_bots)}):\n{bots_list}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ASK_MODE

def handle_unified_dashboard(query, context):
    """معالج لوحة التحكم الموحدة"""
    active_count = len(active_tasks)
    active_info = ""
    
    if active_tasks:
        for chat_id, task in active_tasks.items():
            elapsed = int(time.time() - task['start_time'])
            active_info += f"• Chat {chat_id}: {task['type']} ({elapsed}s)\n"
    else:
        active_info = "لا توجد مهام نشطة"
    
    # إحصائيات Tolid
    tolid_info = "غير متاح"
    if TOLID_AVAILABLE:
        tolid_stats = tolid.get_performance_stats()
        tolid_info = (
            f"• مولد: {tolid_stats['total_generated']}\n"
            f"• متوسط السرعة: {tolid_stats['avg_speed']:.0f}/ثانية\n"
            f"• إجمالي الوقت: {tolid_stats['total_time']:.1f}s"
        )
    
    # إحصائيات Checker
    checker_info = "غير متاح"
    if CHECKER_AVAILABLE:
        checker_stats = checker.get_performance_stats()
        checking_bots = checker.get_checking_bots()
        checker_info = (
            f"• مولد: {checker_stats['total_generated']}\n"
            f"• مفحوص: {checker_stats['total_checked']}\n"
            f"• صالح: {checker_stats['total_valid']}\n"
            f"• معدل النجاح: {checker_stats['success_rate']:.1f}%\n"
            f"• بوتات الفحص: {len(checking_bots)}"
        )
    
    # آخر الأنشطة
    recent_activities = "لا توجد أنشطة"
    if TOLID_AVAILABLE:
        tolid_history = tolid.get_task_history()
        if tolid_history:
            recent_activities = "\n".join(tolid_history[-3:])
    elif CHECKER_AVAILABLE:
        checker_history = checker.get_task_history()
        if checker_history:
            recent_activities = "\n".join(checker_history[-3:])
    
    query.edit_message_text(
        f"📊 **لوحة التحكم الشاملة**\n\n"
        f"🔹 **المهام النشطة ({active_count}):**\n{active_info}\n\n"
        f"💾 **إحصائيات Tolid:**\n{tolid_info}\n\n"
        f"🔍 **إحصائيات Checker:**\n{checker_info}\n\n"
        f"📝 **آخر الأنشطة:**\n{recent_activities}",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🔄 تحديث", callback_data="dashboard")],
            [InlineKeyboardButton("🔙 رجوع", callback_data="back_to_main")]
        ])
    )
    return ASK_MODE

def handle_action_buttons(query, context):
    """معالج أزرار الإجراءات"""
    action = query.data.replace("action_", "")
    
    if action == "add_bot":
        query.edit_message_text(
            "🤖 **إضافة بوت فحص جديد**\n\n"
            "أرسل توكن البوت الذي تريد إضافته:\n"
            "مثال: `123456789:ABCdefGHIjklMNOpqrSTUvwxYZ`",
            parse_mode="Markdown"
        )
        return ADD_BOT_TOKEN
    
    elif action.startswith("start_check_"):
        session_type = action.replace("start_check_", "")
        return start_session_checking(query, context, session_type)
    
    return ASK_MODE

def start_session_checking(query, context, session_type):
    """بدء عملية فحص الجلسات"""
    chat_id = query.message.chat_id
    
    if chat_id in active_tasks:
        query.edit_message_text("⚠️ هناك مهمة قائمة بالفعل. أرسل /cancel لإيقافها أولاً.")
        return ConversationHandler.END
    
    query.edit_message_text(f"🚀 بدء فحص جلسات {session_type.title()}...")
    
    # إنشاء رسالة تقدم
    progress_message = context.bot.send_message(
        chat_id=chat_id,
        text="⏳ جاري التحضير للفحص..."
    )
    
    cancel_event = threading.Event()
    active_tasks[chat_id] = {
        'start_time': time.time(),
        'type': f'check_{session_type}',
        'cancel_event': cancel_event,
        'progress_message_id': progress_message.message_id
    }
    
    # بدء عملية التوليد والفحص في خيط منفصل
    thread = threading.Thread(
        target=checker.session_generation_and_check_process,
        args=(session_type, chat_id, context, progress_message.message_id, cancel_event),
        daemon=True
    )
    thread.start()
    
    checker.log_activity("START_UNIFIED_CHECKING", f"بدء فحص جلسات {session_type}")
    return ConversationHandler.END

# ----------------------
# معالجات الرسائل النصية
# ----------------------
@owner_only
def handle_count_input(update: Update, context: CallbackContext):
    """معالج إدخال العدد لـ Tolid"""
    try:
        count = int(update.message.text.strip())
        if count <= 0:
            update.message.reply_text("❌ العدد يجب أن يكون أكبر من صفر.")
            return ASK_COUNT
        
        if count > tolid.MAX_ALLOWED:
            update.message.reply_text(f"❌ العدد كبير جداً. الحد الأقصى: {tolid.MAX_ALLOWED:,}")
            return ASK_COUNT
        
        context.user_data['target_count'] = count
        update.message.reply_text(
            f"✅ سيتم توليد {count:,} جلسة.\n\n"
            f"الآن أرسل اسم قاعدة البيانات:"
        )
        return ASK_DBNAME
        
    except ValueError:
        update.message.reply_text("❌ يرجى إرسال رقم صحيح.")
        return ASK_COUNT

@owner_only
def handle_dbname_input(update: Update, context: CallbackContext):
    """معالج إدخال اسم قاعدة البيانات"""
    dbname = update.message.text.strip()
    
    if not dbname or len(dbname) < 3:
        update.message.reply_text("❌ اسم قاعدة البيانات يجب أن يكون 3 أحرف على الأقل.")
        return ASK_DBNAME
    
    context.user_data['dbname'] = dbname
    update.message.reply_text(
        f"✅ قاعدة البيانات: {dbname}\n\n"
        f"الآن أرسل اسم الجدول:"
    )
    return ASK_TABLENAME

@owner_only
def handle_tablename_input(update: Update, context: CallbackContext):
    """معالج إدخال اسم الجدول وبدء التوليد"""
    tablename = update.message.text.strip()
    
    if not tablename or len(tablename) < 3:
        update.message.reply_text("❌ اسم الجدول يجب أن يكون 3 أحرف على الأقل.")
        return ASK_TABLENAME
    
    target_count = context.user_data.get('target_count')
    dbname = context.user_data.get('dbname')
    chat_id = update.effective_chat.id
    
    if chat_id in active_tasks:
        update.message.reply_text("⚠️ هناك مهمة توليد قائمة بالفعل.")
        return ConversationHandler.END
    
    update.message.reply_text(
        f"🚀 **بدء عملية التوليد**\n\n"
        f"• العدد: {target_count:,} جلسة\n"
        f"• قاعدة البيانات: `{dbname}`\n"
        f"• الجدول: `{tablename}`\n\n"
        f"ابتدأت العملية الآن...",
        parse_mode="Markdown"
    )
    
    # إنشاء رسالة تقدم
    progress_message = update.message.reply_text("⏳ بدء العملية...")
    
    cancel_event = threading.Event()
    active_tasks[chat_id] = {
        'start_time': time.time(),
        'type': 'tolid_generation',
        'target_count': target_count,
        'dbname': dbname,
        'tablename': tablename,
        'cancel_event': cancel_event,
        'progress_message_id': progress_message.message_id
    }
    
    # بدء التوليد في خيط منفصل
    thread = threading.Thread(
        target=tolid.generate_parallel,
        args=(target_count, dbname, tablename, chat_id, context, progress_message.message_id, cancel_event),
        daemon=True
    )
    thread.start()
    
    tolid.log_activity("START_UNIFIED_GENERATION", f"الهدف: {target_count}, قاعدة البيانات: {dbname}, الجدول: {tablename}")
    return ConversationHandler.END

@owner_only
def handle_bot_token_input(update: Update, context: CallbackContext):
    """معالج إدخال توكن البوت"""
    token = update.message.text.strip()
    
    if not token or len(token.split(':')) != 2:
        update.message.reply_text("❌ تنسيق التوكن غير صحيح. يرجى المحاولة مرة أخرى.")
        return ADD_BOT_TOKEN
    
    update.message.reply_text("⏳ جاري التحقق من صلاحية التوكن...")
    
    if checker.add_checking_bot(token):
        checking_bots = checker.get_checking_bots()
        update.message.reply_text(
            f"✅ تم إضافة البوت بنجاح!\n"
            f"إجمالي بوتات الفحص: {len(checking_bots)}"
        )
        checker.log_activity("UNIFIED_BOT_ADDED", "تم إضافة بوت فحص جديد")
    else:
        update.message.reply_text("❌ فشل في إضافة البوت. تأكد من صحة التوكن.")
    
    return ConversationHandler.END

@owner_only
def handle_file_path_input(update: Update, context: CallbackContext):
    """معالج إدخال مسار الملف"""
    file_path = update.message.text.strip()
    
    if not os.path.exists(file_path):
        update.message.reply_text("❌ الملف غير موجود. تأكد من المسار.")
        return ASK_FILE_PATH
    
    update.message.reply_text("🔍 جاري فحص الملف...")
    
    # فحص الملف في خيط منفصل
    thread = threading.Thread(
        target=checker.check_file_sessions,
        args=(file_path, update.effective_chat.id, context),
        daemon=True
    )
    thread.start()
    
    checker.log_activity("UNIFIED_FILE_CHECK", f"بدء فحص ملف: {file_path}")
    return ConversationHandler.END

# ----------------------
# أوامر البوت العامة
# ----------------------
@owner_only
def cancel(update: Update, context: CallbackContext):
    """إلغاء المهمة النشطة"""
    chat_id = update.effective_chat.id
    if chat_id in active_tasks:
        active_tasks[chat_id]['cancel_event'].set()
        task_type = active_tasks[chat_id]['type']
        update.message.reply_text(f"⏹️ تم إرسال أمر الإيقاف لمهمة {task_type}...")
        
        if TOLID_AVAILABLE:
            tolid.log_activity("UNIFIED_CANCEL", f"طلب إلغاء مهمة {task_type}")
        elif CHECKER_AVAILABLE:
            checker.log_activity("UNIFIED_CANCEL", f"طلب إلغاء مهمة {task_type}")
    else:
        update.message.reply_text("❌ لا توجد مهمة نشطة للإلغاء.")
    return ConversationHandler.END

@owner_only
def status(update: Update, context: CallbackContext):
    """عرض حالة المهام النشطة"""
    chat_id = update.effective_chat.id
    
    if chat_id in active_tasks:
        task = active_tasks[chat_id]
        elapsed = time.time() - task['start_time']
        
        status_text = (
            f"📊 **حالة المهمة النشطة**\n\n"
            f"🔹 النوع: {task['type']}\n"
            f"⏱️ الوقت المنقضي: {int(elapsed)} ثانية\n"
        )
        
        if task['type'] == 'tolid_generation':
            # إحصائيات Tolid
            current_count = tolid.get_row_count(task['dbname'], task['tablename'])
            status_text += (
                f"🎯 الهدف: {task['target_count']:,}\n"
                f"💾 المحفوظ: {current_count:,}\n"
                f"📊 التقدم: {(current_count/task['target_count']*100):.1f}%"
            )
        elif task['type'].startswith('check_'):
            # إحصائيات الفحص
            checker_stats = checker.get_performance_stats()
            checking_bots = checker.get_checking_bots()
            status_text += (
                f"🔍 مفحوص: {checker_stats['total_checked']:,}\n"
                f"✅ صالح: {checker_stats['total_valid']:,}\n"
                f"📈 معدل النجاح: {checker_stats['success_rate']:.1f}%\n"
                f"🤖 بوتات الفحص: {len(checking_bots)}"
            )
        
        status_text += "\n\nلإيقاف المهمة أرسل /cancel"
        update.message.reply_text(status_text, parse_mode="Markdown")
    else:
        update.message.reply_text("❌ لا توجد مهمة نشطة حالياً.")

@owner_only
def help_command(update: Update, context: CallbackContext):
    """عرض المساعدة"""
    help_text = (
        "🔧 **أوامر البوت الموحد**\n\n"
        "/start - عرض القائمة الرئيسية\n"
        "/status - حالة المهمة النشطة\n"
        "/cancel - إيقاف المهمة النشطة\n"
        "/help - عرض هذه المساعدة\n\n"
        "📋 **الوظائف المتاحة:**\n"
    )
    
    if TOLID_AVAILABLE:
        help_text += "💾 توليد وحفظ الجلسات في PostgreSQL\n"
    
    if CHECKER_AVAILABLE:
        help_text += (
            "🔍 فحص جلسات Telethon و Pyrogram\n"
            "📁 فحص ملفات الجلسات المحفوظة\n"
            "🤖 إدارة بوتات الفحص\n"
        )
    
    help_text += "\n📊 لوحة تحكم شاملة لجميع العمليات"
    
    update.message.reply_text(help_text, parse_mode="Markdown")

def alert_check(context: CallbackContext):
    """فحص التنبيهات للمهام طويلة المدى"""
    for chat_id, task in list(active_tasks.items()):
        elapsed = time.time() - task['start_time']
        if elapsed > 3600:  # ساعة واحدة
            try:
                context.bot.send_message(
                    chat_id=chat_id, 
                    text=f"⚠️ تنبيه: المهمة {task['type']} تستغرق وقتاً طويلاً ({int(elapsed/60)} دقيقة)."
                )
            except Exception:
                pass
            logger.warning(f"مهمة طويلة المدى في chat {chat_id}: {task['type']}")

# ----------------------
# نقطة الدخول الرئيسية
# ----------------------
def main():
    """الدالة الرئيسية لتشغيل البوت الموحد"""
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")
    
    # التحقق من الإعدادات
    if BOT_OWNER_ID == 123456789:
        logger.error("❗ لم تقم بتعيين معرف المالك الصحيح في BOT_OWNER_ID")
        return
    
    if not BOT_TOKEN:
        logger.error("❗ لم تقم بتعيين متغير البيئة BOT_TOKEN")
        return
    
    # التحقق من توفر الوحدات
    if not TOLID_AVAILABLE and not CHECKER_AVAILABLE:
        logger.error("❗ لا توجد وحدات وظيفية متاحة")
        return
    
    # تحميل إعدادات بوتات الفحص إذا كانت متاحة
    if CHECKER_AVAILABLE:
        checker.load_bots_config()
    
    # إعداد البوت
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    job_queue = updater.job_queue
    
    # معالج المحادثة الرئيسي
    conv = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            ASK_MODE: [CallbackQueryHandler(button_handler)],
            ASK_COUNT: [MessageHandler(Filters.text & ~Filters.command, handle_count_input)],
            ASK_DBNAME: [MessageHandler(Filters.text & ~Filters.command, handle_dbname_input)],
            ASK_TABLENAME: [MessageHandler(Filters.text & ~Filters.command, handle_tablename_input)],
            ADD_BOT_TOKEN: [MessageHandler(Filters.text & ~Filters.command, handle_bot_token_input)],
            ASK_FILE_PATH: [MessageHandler(Filters.text & ~Filters.command, handle_file_path_input)],
        },
        fallbacks=[CommandHandler('cancel', cancel)]
    )
    
    # إضافة المعالجات
    dp.add_handler(conv)
    dp.add_handler(CommandHandler('cancel', cancel))
    dp.add_handler(CommandHandler('status', status))
    dp.add_handler(CommandHandler('help', help_command))
    
    # مهام دورية
    job_queue.run_repeating(alert_check, interval=1800, first=0)  # كل 30 دقيقة
    
    # رسائل البدء
    logger.info("🚀 Unified Bot started successfully")
    print("="*50)
    print("🏠 البوت الموحد - مركز التحكم الشامل")
    print("="*50)
    print(f"💾 Tolid Functions: {'✅ متاح' if TOLID_AVAILABLE else '❌ غير متاح'}")
    print(f"🔍 Session Checker: {'✅ متاح' if CHECKER_AVAILABLE else '❌ غير متاح'}")
    
    if CHECKER_AVAILABLE:
        checking_bots = checker.get_checking_bots()
        print(f"🤖 بوتات الفحص: {len(checking_bots)}")
        print(f"📱 Telethon: {'✅' if checker.is_telethon_available() else '❌'}")
        print(f"📱 Pyrogram: {'✅' if checker.is_pyrogram_available() else '❌'}")
    
    print("="*50)
    print("✅ البوت جاهز للاستخدام. اضغط Ctrl+C للإيقاف.")
    print("="*50)
    
    # تشغيل البوت
    updater.start_polling()
    updater.idle()
    
    # تنظيف عند الإغلاق
    logger.info("🛑 Unified Bot stopped")

if __name__ == "__main__":
    main()