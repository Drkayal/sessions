import os
import sys
import subprocess
import time
import traceback


REQUIRED_PACKAGES = [
    "python-telegram-bot==13.15",
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
        print("[bootstrap] تم تثبيت الحزم والتحقق من توفرها بنجاح")
    except Exception as e:
        print(f"[bootstrap] تم تثبيت الحزم لكن التحقق من الاستيراد فشل: {e}", file=sys.stderr)
        sys.exit(1)


def verify_env() -> None:
    bot_token = os.getenv("BOT_TOKEN", "")
    bot_owner_id = os.getenv("BOT_OWNER_ID", "")

    missing = []
    if not bot_token:
        missing.append("BOT_TOKEN")
    if not bot_owner_id:
        missing.append("BOT_OWNER_ID")

    if missing:
        print(f"[bootstrap] متغيرات البيئة الناقصة/غير الصحيحة: {', '.join(missing)}", file=sys.stderr)
        print("[bootstrap] الرجاء تعيين المتغيرات المطلوبة قبل التشغيل.")
        sys.exit(1)


def run_bot() -> None:
    # استيراد التطبيق وتشغيله
    try:
        import SessionChecker  # noqa: F401
    except Exception as e:
        print(f"[bootstrap] فشل استيراد SessionChecker.py بعد تثبيت المتطلبات: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)

    try:
        print("[bootstrap] بدء تشغيل فاحص الجلسات...")
        SessionChecker.main()
    except KeyboardInterrupt:
        print("[bootstrap] تم الإيقاف بواسطة المستخدم")
    except Exception as e:
        print(f"[bootstrap] حدث خطأ أثناء تشغيل فاحص الجلسات: {e}", file=sys.stderr)
        traceback.print_exc()
        sys.exit(1)


def main() -> None:
    print("[bootstrap] التحقق من المتطلبات وتثبيتها عند الحاجة...")
    ensure_packages()
    print("[bootstrap] التحقق من متغيرات البيئة...")
    verify_env()
    run_bot()


if __name__ == "__main__":
    main()