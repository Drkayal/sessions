import os
import sys
import subprocess
import time
import traceback
import secrets


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

    # تحقق صريح من أن الوحدات أصبحت متاحة
    try:
        import telegram  # noqa: F401
        import psycopg2  # noqa: F401
        print("[bootstrap] تم تثبيت الحزم والتحقق من توفرها بنجاح")
    except Exception as e:
        print(f"[bootstrap] تم تثبيت الحزم لكن التحقق من الاستيراد فشل: {e}", file=sys.stderr)
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
        print("[bootstrap] اكتملت خطوة التحقق/الإنشاء لقاعدة البيانات")
    except Exception as e:
        print(f"[bootstrap] تعذر إنشاء/التحقق من قاعدة البيانات '{target_db}': {e}", file=sys.stderr)
        # لا نُنهِي البرنامج، قد يتكفل التطبيق لاحقاً بإنشائها أو تكون صلاحيات محدودة


def _write_env_password(pwd: str) -> None:
    try:
        env_path = os.path.join(os.getcwd(), ".env")
        content = ""
        if os.path.exists(env_path):
            try:
                with open(env_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception:
                content = ""

        lines = content.splitlines()
        found = False
        for i, line in enumerate(lines):
            if line.startswith("PGPASSWORD="):
                lines[i] = f"PGPASSWORD={pwd}"
                found = True
                break
        if not found:
            lines.append(f"PGPASSWORD={pwd}")

        with open(env_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        print("[bootstrap] تم تحديث/إنشاء ملف .env بكلمة المرور (PGPASSWORD)")
    except Exception as e:
        print(f"[bootstrap] تعذر كتابة ملف .env: {e}")


def ensure_db_credentials() -> None:
    """محاولة تلقائية لضبط كلمة مرور PostgreSQL إذا لم يتم تعيينها.

    الاستراتيجية:
    - إذا كانت PGPASSWORD مضبوطة وليست القيمة الافتراضية، لا نفعل شيئاً.
    - نحاول الاتصال دون كلمة مرور (peer/trust محلياً). إذا نجح:
      * إن اتصلنا كمستخدم PGUSER: نغير كلمة مرور الدور الحالي.
      * إذا فشل الاتصال بـ PGUSER، نجرب الاتصال كمستخدم 'postgres' ثم ننشئ/نعدل PGUSER ونعيّن له كلمة مرور.
    - نحدّث os.environ['PGPASSWORD'] ونكتبها في .env لتبقى بين الجلسات.
    """
    host = os.getenv("PGHOST", "localhost")
    port = os.getenv("PGPORT", "5432")
    user = os.getenv("PGUSER", "postgres")
    pwd = os.getenv("PGPASSWORD", "your_password")
    target_db = os.getenv("PGDATABASE", "postgres")

    if pwd and pwd != "your_password":
        return

    try:
        import psycopg2
        from psycopg2 import sql
    except Exception:
        # سيتم التثبيت قبل الاستدعاء عادةً، لكن إن لم يكن، نتوقف وسنعاود بعد ensure_packages
        return

    new_password = secrets.token_urlsafe(24)

    # 1) محاولة الاتصال كـ PGUSER بدون كلمة مرور
    try:
        conn = psycopg2.connect(host=host, port=port, user=user, dbname="postgres")
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute(sql.SQL("ALTER ROLE {} WITH PASSWORD %s").format(sql.Identifier(user)), [new_password])
        cur.close()
        conn.close()
        os.environ["PGPASSWORD"] = new_password
        _write_env_password(new_password)
        print(f"[bootstrap] تم تعيين كلمة مرور للمستخدم {user} تلقائياً عبر اتصال بدون كلمة مرور")
        return
    except Exception:
        pass

    # 2) محاولة الاتصال كمستخدم postgres بدون كلمة مرور (محلياً)
    try:
        conn = psycopg2.connect(host=host, port=port, user="postgres", dbname="postgres")
        conn.autocommit = True
        cur = conn.cursor()
        # إنشاء المستخدم إن لم يكن موجوداً، ومنحه كلمة مرور وصلاحية LOGIN
        cur.execute(
            sql.SQL(
                """
                DO $$
                BEGIN
                  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s) THEN
                    CREATE ROLE {} LOGIN;
                  END IF;
                END$$;
                """
            ).format(sql.Identifier(user)),
            [user],
        )
        cur.execute(sql.SQL("ALTER ROLE {} WITH PASSWORD %s").format(sql.Identifier(user)), [new_password])
        cur.close()
        conn.close()
        os.environ["PGPASSWORD"] = new_password
        _write_env_password(new_password)
        print(f"[bootstrap] تم إنشاء/تحديث المستخدم {user} وتعيين كلمة المرور تلقائياً بحساب postgres")
        return
    except Exception:
        pass

    # 3) محاولة عبر psql وsudo إذا كان متاحاً (بيئات بها صلاحيات نظام)
    try:
        cmd = [
            "bash",
            "-lc",
            f"sudo -n -u postgres psql -tAc \"DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{user}') THEN CREATE ROLE \"{user}\" LOGIN; END IF; END$$; ALTER ROLE \"{user}\" WITH PASSWORD '{new_password}';\"",
        ]
        if run(cmd) == 0:
            os.environ["PGPASSWORD"] = new_password
            _write_env_password(new_password)
            print(f"[bootstrap] تم إنشاء/تحديث المستخدم {user} وكلمة المرور عبر sudo/psql")
            return
    except Exception:
        pass

    print("[bootstrap] لم نتمكن من ضبط كلمة مرور PostgreSQL تلقائياً. يرجى تعيين PGPASSWORD يدوياً.", file=sys.stderr)


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
    print("[bootstrap] محاولة ضبط كلمة مرور PostgreSQL تلقائياً عند غيابها...")
    ensure_db_credentials()
    print("[bootstrap] التحقق من متغيرات البيئة...")
    verify_env()
    print("[bootstrap] التحقق من قاعدة البيانات/إنشائها عند الحاجة...")
    ensure_database()
    run_bot()


if __name__ == "__main__":
    main()

