import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _popup(message: str):
    print(message, file=sys.stderr)
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, message, "Lookup", 0x10)
    except Exception:
        pass


def main():
    try:
        from pdflookup.window import install_excepthook, run
    except ImportError as exc:
        _popup(f"Missing dependency: {exc}\n\nDouble-click run.bat again, or run:\npip install -r requirements.txt")
        return 1
    install_excepthook()
    return run()


if __name__ == "__main__":
    sys.exit(main())
