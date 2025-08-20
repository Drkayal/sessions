import os
import sys
import subprocess
import time
import traceback


REQUIRED_PACKAGES = [
    "python-telegram-bot==13.15",
    "psycopg2-binary",
    "telethon>=1.24.0", 
    "pyrogram>=2.0.0",
    "requests>=2.28.0",
]


def run(cmd: list[str]) -> int:
    try:
        proc = subprocess.run(cmd, check=False)
        return proc.returncode
    except Exception:
        return 1


def ensure_packages() -> None:
    python_exe = sys.executable

    # Upgrade pip/setuptools/wheel first for better compatibility
    print("[bootstrap] تحديث pip وأدوات التثبيت...")
    run([python_exe, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])

    # Install required runtime packages
    print("[bootstrap] تثبيت المتطلبات...")
    install_cmd = [python_exe, "-m", "pip", "install", "--no-input"] + REQUIRED_PACKAGES
    code = run(install_cmd)
    if code != 0:
        print("[bootstrap] فشل تثبيت المتطلبات عبر pip", file=sys.stderr)
        sys.exit(1)

    # تحقق صريح من أن الوحدات أصبحت متاحة
    try:
        import telegram  # noqa: F401
        print("[bootstrap] ✅ python-telegram-bot متاح")
    except Exception as e:
        print(f"[bootstrap] ❌ telegram: {e}", file=sys.stderr)

    try:
        import psycopg2  # noqa: F401
        print("[bootstrap] ✅ psycopg2 متاح")
    except Exception as e:
        print(f"[bootstrap] ❌ psycopg2: {e}", file=sys.stderr)

    try:
        import telethon  # noqa: F401
        print("[bootstrap] ✅ telethon متاح")
    except Exception as e:
        print(f"[bootstrap] ❌ telethon: {e}")

    try:
        import pyrogram  # noqa: F401
        print("[bootstrap] ✅ pyrogram متاح")
    except Exception as e:
        print(f"[bootstrap] ❌ pyrogram: {e}")

    print("[bootstrap] اكتمل تثبيت المتطلبات")


def verify_env() -> None:
    bot_token = os.getenv("BOT_TOKEN", "")
    bot_owner_id = os.getenv("BOT_OWNER_ID", "")
    pg_password = os.getenv("PGPASSWORD", "your_password")

    missing = []
    if not bot_token:
        missing.append("BOT_TOKEN")
    if not bot_owner_id:
        missing.append("BOT_OWNER_ID")
    if pg_password == "your_password":
        missing.append("PGPASSWORD (للوظائف التي تحتاج PostgreSQL)")

    if missing:
        print(f"[bootstrap] متغيرات البيئة الناقصة/غير الصحيحة: {', '.join(missing)}", file=sys.stderr)
        if "BOT_TOKEN" in missing or "BOT_OWNER_ID" in missing:
            print("[bootstrap] BOT_TOKEN و BOT_OWNER_ID مطلوبان للتشغيل.")
            sys.exit(1)
        else:
            print("[bootstrap] تحذير: PGPASSWORD غير مضبوط، وظائف PostgreSQL قد لا تعمل.")


def ensure_database() -> None:
    """إنشاء قاعدة البيانات إذا كانت مطلوبة ومتاحة"""
    try:
        import psycopg2

        host = os.getenv("PGHOST", "localhost")
        port = os.getenv("PGPORT", "5432")
        user = os.getenv("PGUSER", "postgres")
        password = os.getenv("PGPASSWORD", "your_password")
        target_db = os.getenv("PGDATABASE", "postgres")

        if password == "your_password":
            print("[bootstrap] تخطي إعداد قاعدة البيانات - كلمة المرور غير مضبوطة")
            return

        # اتصل بقاعدة postgres الافتراضية لإنشاء قاعدة البيانات الهدف إذا لزم
        try:
            conn = psycopg2.connect(host=host, port=port, user=user, password=password, dbname="postgres")
            conn.autocommit = True
            cur = conn.cursor()
            cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target_db,))
            exists = cur.fetchone()
            if not exists:
                cur.execute(f'CREATE DATABASE "{target_db}" WITH ENCODING \'UTF8\'')
                print(f"[bootstrap] تم إنشاء قاعدة البيانات: {target_db}")
            else:
                print(f"[bootstrap] قاعدة البيانات موجودة مسبقاً: {target_db}")
            cur.close()
            conn.close()
            print("[bootstrap] ✅ اكتملت خطوة التحقق/الإنشاء لقاعدة البيانات")
        except Exception as e:
            print(f"[bootstrap] تعذر إنشاء/التحقق من قاعدة البيانات '{target_db}': {e}")

    except ImportError:
        print("[bootstrap] psycopg2 غير متاح - تخطي إعداد قاعدة البيانات")
    except Exception as e:
        print(f"[bootstrap] خطأ في إعداد قاعدة البيانات: {e}")


def run_unified_bot() -> None:
    """تشغيل البوت الموحد"""
    try:
        import UnifiedBot  # noqa: F401
    except Exception as e:
        print(f"[bootstrap] فشل استيراد UnifiedBot.py بعد تثبيت المتطلبات: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)

    try:
        print("[bootstrap] بدء تشغيل البوت الموحد...")
        UnifiedBot.main()
    except KeyboardInterrupt:
        print("[bootstrap] تم الإيقاف بواسطة المستخدم")
    except Exception as e:
        print(f"[bootstrap] حدث خطأ أثناء تشغيل البوت الموحد: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)


def main() -> None:
    print("="*60)
    print("🚀 Bootstrap للبوت الموحد - مركز التحكم الشامل")
    print("="*60)
    
    print("[bootstrap] التحقق من المتطلبات وتثبيتها عند الحاجة...")
    ensure_packages()
    
    print("[bootstrap] التحقق من متغيرات البيئة...")
    verify_env()
    
    print("[bootstrap] التحقق من قاعدة البيانات/إنشائها عند الحاجة...")
    ensure_database()
    
    print("="*60)
    print("✅ الإعداد اكتمل - تشغيل البوت الموحد")
    print("="*60)
    
    run_unified_bot()


if __name__ == "__main__":
    main()