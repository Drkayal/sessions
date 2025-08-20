import os
import sys
import subprocess
import time
import traceback


REQUIRED_PACKAGES = [
    "python-telegram-bot==13.15",
    "psycopg2-binary",
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
    run([python_exe, "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])  # best-effort

    # Install required runtime packages
    install_cmd = [python_exe, "-m", "pip", "install", "--no-input"] + REQUIRED_PACKAGES
    code = run(install_cmd)
    if code != 0:
        print("[bootstrap] فشل تثبيت المتطلبات عبر pip", file=sys.stderr)
        sys.exit(1)


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
        missing.append("PGPASSWORD")

    if missing:
        print(f"[bootstrap] متغيرات البيئة الناقصة/غير الصحيحة: {', '.join(missing)}", file=sys.stderr)
        print("[bootstrap] الرجاء تعيين المتغيرات المطلوبة قبل التشغيل.")
        sys.exit(1)


def ensure_database() -> None:
    import psycopg2

    host = os.getenv("PGHOST", "localhost")
    port = os.getenv("PGPORT", "5432")
    user = os.getenv("PGUSER", "postgres")
    password = os.getenv("PGPASSWORD", "your_password")
    target_db = os.getenv("PGDATABASE", "postgres")

    # اتصل بقاعدة postgres الافتراضية لإنشاء قاعدة البيانات الهدف إذا لزم
    try:
        conn = psycopg2.connect(host=host, port=port, user=user, password=password, dbname="postgres")
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target_db,))
        exists = cur.fetchone()
        if not exists:
            cur.execute(f"CREATE DATABASE \"{target_db}\" WITH ENCODING 'UTF8'")
            print(f"[bootstrap] تم إنشاء قاعدة البيانات: {target_db}")
        else:
            print(f"[bootstrap] قاعدة البيانات موجودة مسبقاً: {target_db}")
        cur.close()
        conn.close()
    except Exception as e:
        print(f"[bootstrap] تعذر إنشاء/التحقق من قاعدة البيانات '{target_db}': {e}", file=sys.stderr)
        # لا نُنهِي البرنامج، قد يتكفل التطبيق لاحقاً بإنشائها أو تكون صلاحيات محدودة


def run_bot() -> None:
    # استيراد التطبيق وتشغيله
    try:
        import Tolid  # noqa: F401
    except Exception as e:
        print(f"[bootstrap] فشل استيراد Tolid.py بعد تثبيت المتطلبات: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)

    try:
        print("[bootstrap] بدء تشغيل البوت...")
        Tolid.main()
    except KeyboardInterrupt:
        print("[bootstrap] تم الإيقاف بواسطة المستخدم")
    except Exception as e:
        print(f"[bootstrap] حدث خطأ أثناء تشغيل البوت: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)


def main() -> None:
    print("[bootstrap] التحقق من المتطلبات وتثبيتها عند الحاجة...")
    ensure_packages()
    print("[bootstrap] التحقق من متغيرات البيئة...")
    verify_env()
    print("[bootstrap] التحقق من قاعدة البيانات/إنشائها عند الحاجة...")
    ensure_database()
    run_bot()


if __name__ == "__main__":
    main()

