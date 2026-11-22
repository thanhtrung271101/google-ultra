#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Google AI Pro 5TB & AI Ultra (20TB / 30TB) — Interactive Activation Wizard

No CLI knowledge required: double-click start.command on Mac or start.bat on Windows.
Workflow: Environment Check -> Select Plan / Test Offers -> Paste Accounts -> Activate -> Summary Table.

Supported plans:
    1) AI Pro 5TB:
       - g1.2tb.ai.subs_variant (12months-eft / 6months-eft)
       - g1.play.2tb.ai (eft-3mo)
    2) AI Ultra 20TB (5x):
       - g1.play.20tb / g1.20tb.ai.pro / g1.20tb
    3) AI Ultra 30TB (20x):
       - g1.play.ai.pro / g1.ai.pro / g1.30tb
    4) All Ultra + AI Pro tiers (try longest free trial across all tiers with automatic fallback)
    5) Test / Scan all Ultra & AI Pro offers on current account (query-only)

Works with both rooted physical Android devices and emulators (MuMu Player 12 on Windows, MuMu Pro on Mac).
Automatically detects device architecture (x86_64 on MuMu-Windows, arm64 on MuMu-Mac and physical phones).
"""
import lzma
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ultra0  # noqa: E402

IS_WIN = os.name == "nt"


def _setup_console() -> bool:
    """Configure UTF-8 console output and enable ANSI colors on Windows/Mac."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    if IS_WIN:
        try:
            import ctypes
            k = ctypes.windll.kernel32
            k.SetConsoleMode(k.GetStdHandle(-11), 7)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        except Exception:
            return False
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


_COLOR = _setup_console()


# ---------- Terminal Colors / Formatting ----------
class C:
    G = "\033[32m" if _COLOR else ""
    R = "\033[31m" if _COLOR else ""
    Y = "\033[33m" if _COLOR else ""
    B = "\033[36m" if _COLOR else ""
    DIM = "\033[2m" if _COLOR else ""
    BOLD = "\033[1m" if _COLOR else ""
    END = "\033[0m" if _COLOR else ""


def c(txt, color):
    return f"{color}{txt}{C.END}"


def banner(title):
    line = "═" * 58
    print(f"\n{c(line, C.B)}")
    print(f"{c('  ' + title, C.B + C.BOLD)}")
    print(f"{c(line, C.B)}")


def dwidth(s: str) -> int:
    """Calculate display width in terminal (wide characters count as 2)."""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in s)


def pad(s: str, width: int) -> str:
    return s + " " * max(0, width - dwidth(s))


def ask_yes(prompt: str, default=True) -> bool:
    tail = "[Y/n]" if default else "[y/N]"
    try:
        ans = input(f"{prompt} {tail} ").strip().lower()
    except EOFError:
        return default
    if not ans:
        return default
    return ans in ("y", "yes")


# ---------- Friendly Error Messages ----------
def humanize(msg: str) -> str:
    """Translate raw ADB / Frida / Play Store errors into plain English."""
    m = msg or ""
    low = m.lower()
    if "processnotfound" in low or "process not found" in low or "unable to find process" in low:
        return "Google One failed to start. Please try again."
    if "no devices" in low or "no android device" in low or "device not found" in low:
        return "No device detected. Check USB cable & USB debugging, or start emulator with ROOT enabled."
    if "frida-server" in low and "fail" in low:
        return "Failed to start frida-server on the device."
    if "frida" in low and ("not installed" in low or "no module" in low):
        return "frida is not installed on PC. Run: pip3 install frida==16.5.9"
    if "adb not found" in low:
        return "ADB not found. Please install Android platform-tools."
    if "root" in low:
        return "Root access unavailable. Enable ROOT in emulator settings and restart, or use Magisk on a physical device."
    if "already subscribed" in low:
        return "This account has already used the trial. Try another account."
    if "not eligible" in low:
        return "This account is not eligible for the free trial."
    if "item_not_available" in low or "not available for purchase" in low:
        return "Requested offer is not available for purchase on this account."
    return "An unexpected error occurred. Retry or use --advanced mode to inspect full logs."


# ---------- 1. Environment Check ----------
def _run(fn, *a, **k):
    """Run an ultra0 function that might call sys.exit and return (ok, message)."""
    try:
        fn(*a, **k)
        return True, ""
    except SystemExit as e:
        return False, str(e.code if e.code is not None else e)
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def check_python() -> bool:
    v = sys.version_info
    if v < (3, 9):
        print(c(f"  ❌ Python {v.major}.{v.minor} detected; Python 3.9+ is required", C.R))
        return False
    print(c(f"  ✅ Python {v.major}.{v.minor}.{v.micro}", C.G))
    return True


def check_frida() -> bool:
    try:
        import frida
        print(c(f"  ✅ frida {frida.__version__}", C.G))
        return True
    except Exception:
        print(c("  ⚠️  frida is not installed on this computer", C.Y))
        if ask_yes("     Install frida now via pip?"):
            r = subprocess.run([sys.executable, "-m", "pip", "install", "frida==16.5.9"])
            if r.returncode == 0:
                try:
                    import frida  # noqa: F401
                    print(c("  ✅ frida installed successfully", C.G))
                    return True
                except Exception:
                    pass
        print(c("     Please install it and re-run: pip3 install frida==16.5.9", C.DIM))
        return False


def _adb(*args, timeout=60):
    """Run ADB with -s SERIAL if set."""
    cmd = [ultra0.ADB] + (["-s", ultra0.SERIAL] if ultra0.SERIAL else []) + list(args)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


MUMU_ADB_WIN = [
    r"D:\MuMuPlayerGlobal\nx_device\12.0\shell\adb.exe",
    r"D:\MuMuPlayerGlobal\nx_main\adb.exe",
    r"C:\MuMuPlayerGlobal\nx_device\12.0\shell\adb.exe",
    r"C:\Program Files\Netease\MuMu Player 12\shell\adb.exe",
    r"C:\Program Files\Netease\MuMuPlayer-12.0\shell\adb.exe",
    r"C:\Program Files\Netease\MuMu Player\shell\adb.exe",
]


def discover_adb():
    """Find ADB across platforms: prefer MuMu bundled ADB on Windows, then PATH / SDK."""
    cands = []
    if IS_WIN:
        cands += MUMU_ADB_WIN
        cands.append(os.path.expanduser(r"~\AppData\Local\Android\Sdk\platform-tools\adb.exe"))
    else:
        cands += ultra0.ADB_CANDIDATES
    for name in ("adb", "adb.exe"):
        w = shutil.which(name)
        if w:
            cands.append(w)
    for cpath in cands:
        if cpath and (cpath in ("adb", "adb.exe") or Path(cpath).exists()):
            try:
                subprocess.run([cpath, "version"], capture_output=True, timeout=5)
                return cpath
            except Exception:
                continue
    return None


def check_adb() -> bool:
    adb = discover_adb()
    if adb:
        ultra0.ADB = adb
        print(c(f"  ✅ adb: {adb}", C.G))
        subprocess.run([adb, "start-server"], capture_output=True)
        return True
    print(c("  ❌ ADB not found", C.R))
    if IS_WIN:
        print(c("     If using MuMu Player, ADB is bundled in its installation folder (shell\\adb.exe).", C.DIM))
        print(c("     Or download Android platform-tools and add it to your system PATH.", C.DIM))
    else:
        print(c("     On macOS, install with: brew install android-platform-tools", C.DIM))
    print(c("     Make sure `adb devices` works in your terminal.", C.DIM))
    return False


def _devices() -> list:
    out = subprocess.run([ultra0.ADB, "devices"], capture_output=True, text=True).stdout
    return [l.split("\t")[0] for l in out.splitlines()[1:] if "\tdevice" in l]


MUMU_PORTS = [16384, 16416, 16448, 16386, 5555, 7555, 21503]


def _try_connect(hostport: str) -> bool:
    subprocess.run([ultra0.ADB, "connect", hostport], capture_output=True, text=True, timeout=10)
    return any(hostport in d or d.startswith("emulator") for d in _devices())


def connect_device() -> bool:
    """Ensure an Android device or MuMu emulator is connected and set ultra0.SERIAL."""
    devs = _devices()
    if len(devs) == 1:
        ultra0.SERIAL = devs[0]
        print(c(f"  ✅ Device connected: {devs[0]}", C.G))
        return True
    if len(devs) > 1:
        print("  Multiple devices detected:")
        for i, d in enumerate(devs, 1):
            print(f"    {i}) {d}")
        sel = input("  Select device number: ").strip()
        idx = int(sel) - 1 if sel.isdigit() and 0 < int(sel) <= len(devs) else 0
        ultra0.SERIAL = devs[idx]
        print(c(f"  ✅ Using device: {ultra0.SERIAL}", C.G))
        return True

    print(c("  ⚠️  No connected device detected.", C.Y))
    while True:
        print("     Which setup are you using?")
        print("       1) Rooted Android phone (plug in USB, enable USB debugging, tap Allow)")
        print("       2) MuMu Emulator (MuMu Player 12 / MuMu Pro)")
        print("       3) Enter ADB address manually (e.g. 127.0.0.1:16384)")
        print("       0) Quit")
        choice = input("     Select: ").strip()
        if choice == "0":
            return False
        if choice == "1":
            input("     Plug in your phone and authorize USB debugging, then press Enter...")
        elif choice == "2":
            mumu = "MuMu Player 12 (Windows)" if IS_WIN else "MuMu Pro (macOS)"
            print(c("     MuMu Emulator Setup Steps:", C.B))
            print(f"       1. Install {mumu} and start an Android instance")
            print("       2. Open Settings -> Enable ROOT access, then restart the emulator")
            print("       3. Return here to auto-connect")
            input("     Press Enter when ready to auto-connect...")
            hit = None
            for p in MUMU_PORTS:
                hp = f"127.0.0.1:{p}"
                print(c(f"       Trying {hp} ...", C.DIM))
                if _try_connect(hp):
                    hit = hp
                    break
            if not hit:
                print(c("     Auto-connect failed. Check the ADB port in MuMu settings,", C.Y))
                print(c("     then choose option 3 to enter host:port manually.", C.Y))
        elif choice == "3":
            hp = input("     Enter host:port: ").strip()
            if hp and _try_connect(hp):
                ultra0.SERIAL = hp
                print(c(f"  ✅ Connected: {hp}", C.G))
                return True
            print(c("     Connection failed. Verify the emulator is running, ROOT is on, and the port is correct.", C.R))
            continue

        devs = _devices()
        if devs:
            ultra0.SERIAL = devs[0]
            print(c(f"  ✅ Device connected: {devs[0]}", C.G))
            return True
        print(c("     Still no device found. Try again or enter 0 to quit.", C.Y))


def _abi() -> str:
    return (_adb("shell", "getprop", "ro.product.cpu.abi", timeout=15).stdout or "").strip()


def _frida_running() -> bool:
    return "frida-server" in (_adb("shell", "ps -A | grep frida-server || true").stdout or "")


def _frida_arch() -> str:
    """Map device ABI to frida-server architecture name."""
    abi = _abi().lower()
    if "x86_64" in abi:
        return "x86_64"
    if "x86" in abi:
        return "x86"
    if "arm64" in abi or "v8" in abi:
        return "arm64"
    return "arm"


def start_frida_server() -> bool:
    """Download, push, and start frida-server matching the device ABI."""
    if _frida_running():
        return True
    try:
        import frida
        ver = frida.__version__
    except Exception:
        print(c("     frida is not installed on PC. Run: pip3 install frida==16.5.9", C.DIM))
        return False
    on_dev = _adb("shell", f"ls {ultra0.FRIDA_REMOTE} 2>/dev/null").stdout.strip()
    if not on_dev:
        arch = _frida_arch()
        url = (f"https://github.com/frida/frida/releases/download/{ver}/"
               f"frida-server-{ver}-android-{arch}.xz")
        print(c(f"     Downloading frida-server ({arch}, v{ver})...", C.DIM))
        tmp = Path(tempfile.gettempdir())
        xz_path, raw_path = tmp / "frida-server.xz", tmp / "frida-server"
        try:
            urllib.request.urlretrieve(url, xz_path)
            with lzma.open(xz_path) as f:
                raw_path.write_bytes(f.read())
        except Exception as e:  # noqa: BLE001
            print(c(f"     Download failed: {e}", C.R))
            return False
        _adb("push", str(raw_path), ultra0.FRIDA_REMOTE, timeout=120)
        _adb("shell", f"chmod 755 {ultra0.FRIDA_REMOTE}")
    _adb("shell", f"su -c 'nohup {ultra0.FRIDA_REMOTE} -D >/dev/null 2>&1 &'", timeout=15)
    for _ in range(20):
        time.sleep(0.5)
        if _frida_running():
            return True
    return False


def push_module() -> bool:
    """Push embedded billing module APK to device."""
    if _adb("shell", f"ls {ultra0.MODULE_REMOTE} 2>/dev/null").stdout.strip():
        return True
    tmp = Path(tempfile.gettempdir()) / "module_521.apk"
    tmp.write_bytes(ultra0.base64.b64decode(ultra0.MODULE_B64))
    return _adb("push", str(tmp), ultra0.MODULE_REMOTE, timeout=120).returncode == 0


def check_device_ready() -> bool:
    """Verify root access, network, frida-server, and billing module on device."""
    ok, _ = _run(ultra0.ensure_root)
    if not ok:
        print(c("  ❌ Root access not available on device", C.R))
        print(c("     Emulator: enable ROOT in settings and restart. Phone: enable root in Magisk/KernelSU.", C.DIM))
        _adb("root")
        time.sleep(1)
        ok, _ = _run(ultra0.ensure_root)
        if not ok:
            return False
    print(c("  ✅ Root access OK", C.G))

    _run(ultra0.ensure_network)
    if not start_frida_server():
        print(c("  ❌ Failed to start frida-server. Please retry.", C.R))
        return False
    print(c("  ✅ frida-server is running", C.G))

    if not push_module():
        print(c("  ❌ Failed to push billing module. Please retry.", C.R))
        return False
    print(c("  ✅ Billing module is ready", C.G))
    return True


def environment_check() -> bool:
    banner("Step 1 · Environment Self-Check")
    if not check_python():
        return False
    if not check_frida():
        return False
    if not check_adb():
        return False
    if not connect_device():
        return False
    if not check_device_ready():
        return False
    print(c("\n  Environment is ready!", C.G + C.BOLD))
    return True


# ---------- 2. Choose Plan & Input Accounts ----------
def choose_plan() -> tuple[str, bool]:
    banner("Step 2 · Choose Plan / Stack / Test Ultra Offers")
    print("  Select which action or plan to run:")
    print("    1) Google AI Pro 5TB — Free Trial with Auto-Fallback (12m -> 6m -> 3m)")
    print("    2) Stack +6 Months (Step 2 -> 18 months total, uses --stack --plan pro6)")
    print("    3) Stack +6 Months (Step 3 -> 24 months total, uses --stack --plan pro6b)")
    print("    4) Stack +6 Months Backup (Step 4 -> 30 months total, uses --stack --plan pro6c)")
    print("    5) Google AI Ultra 20TB (5x plan & $24.99/mo 75% off promo SKU)")
    print("    6) Google AI Ultra 30TB (20x plan & $19.99/mo 90% off promo SKU)")
    print("    7) All Ultra + AI Pro tiers (Try Ultra first, fallback to AI Pro 5TB)")
    print("    8) Scan / Test all available Ultra & AI Pro offers on current device account (No purchase)")
    sel = input("\n  Enter choice [1-8, default=1]: ").strip()
    mapping = {
        "1": ("pro", False),
        "2": ("pro6", True),
        "3": ("pro6b", True),
        "4": ("pro6c", True),
        "5": ("5x", False),
        "6": ("20x", False),
        "7": ("all", False),
        "8": ("test", False),
    }
    return mapping.get(sel, ("pro", False))


FORMAT_HINT = """\
  Enter one account per line, fields separated by four dashes (----):
      email----password----recovery_email----totp_secret----card_number----exp----cvc----holder----zip
  Trailing fields are optional. Examples:

      abc@gmail.com----MyPassword123!----
      abc@gmail.com----MyPassword123!----aux@x.com----JBSWY3DPEHPK3PXP
      abc@gmail.com----MyPassword123!--------JBSWY3DPEHPK3PXP----4242424242424242----10/29----326----JOHN DOE----97201

  Default billing zip is Oregon (97201, tax-free). $0 is charged during the free trial."""


def read_accounts() -> list:
    banner("Step 3 · Paste Accounts")
    print(FORMAT_HINT)
    print(c("\n  Paste your account lines below, then type END on a new line and press Enter:", C.BOLD))
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip().upper() == "END":
            break
        lines.append(line)

    rows = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("----")]
        while len(parts) < 9:
            parts.append("")
        if parts[0]:
            rows.append(parts[:9])
    return rows


# ---------- 3. Batch Execution ----------
def progress_bar(i: int, total: int, width: int = 24) -> str:
    done = int(width * i / total)
    bar = "█" * done + "░" * (width - done)
    pct = int(100 * i / total)
    return f"[{i}/{total}] {c(bar, C.B)} {pct:>3}%"


def run_accounts(rows: list, plan: str = "pro", stack: bool = False) -> list:
    banner(f"Step 4 · Activating Accounts (plan={plan}{', stack=True' if stack else ''})")
    ultra0.REPORT_DIR.mkdir(exist_ok=True)
    total = len(rows)
    results = []
    for i, row in enumerate(rows, 1):
        email, pw, _rec, sec = row[0], row[1], row[2], row[3]
        card = ultra0.parse_card(row)
        print(f"\n{progress_bar(i - 1, total)}  Processing {c(email, C.BOLD)}")
        try:
            rec = ultra0.process(email, pw, sec, add=True, card=card,
                                 plan=plan, no_switch=False, stack=stack)
        except Exception as e:  # noqa: BLE001
            rec = {"email": email, "status": "exception", "_hint": humanize(str(e))}
        results.append(rec)
        (ultra0.REPORT_DIR / f"{email.split('@')[0]}.json").write_text(
            ultra0.json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        label, _ = interpret(rec)
        tone = C.G if "Success" in label else C.R
        print(f"{progress_bar(i, total)}  {c(label, tone)}")
    return results


# ---------- 4. Result Interpretation & Summary ----------
PERIOD_EN = {12: "12 months", 6: "6 months", 3: "3 months", 1: "1 month"}
PERIOD_RANK = {"P1Y": 12, "P12M": 12, "P6M": 6, "P3M": 3, "P1M": 1}


def detect_period(rec: dict) -> str:
    text = (rec.get("sheet") or {}).get("text", "") or ""
    m = re.search(r"(\d+)[\s-]*months?", text, re.I)
    if m:
        return f"{m.group(1)} months"
    if "1 year" in text.lower() or "P1Y" in text:
        return "12 months"
    chosen = rec.get("chosen") or {}
    if chosen.get("period") in PERIOD_RANK:
        return PERIOD_EN.get(PERIOD_RANK[chosen["period"]], chosen["period"])
    best = 0
    for o in rec.get("offers", []):
        if str(o.get("micros")) == "0":
            best = max(best, PERIOD_RANK.get(str(o.get("period")), 0))
    return PERIOD_EN.get(best, "unknown duration")


STATUS_EN = {
    "add_account_failed": "Failed to add account; log in manually on the device and retry",
    "add_account_error": "Error while adding account; log in manually and retry",
    "wrong_account": "Play Store account mismatch; switch manually and run with --no-switch",
    "play_account_switch_failed": "Failed to switch Play Store account; switch manually and retry",
    "app_not_started": "Google One app failed to start; please retry",
    "launch_failed": "No eligible $0 free trial offer found for this account",
}


def interpret(rec: dict):
    """Return (result_label, description)."""
    status = rec.get("status")
    sheet = rec.get("sheet") or {}
    if sheet.get("subscribed") or status == "subscribed":
        return (f"Success ({detect_period(rec)})", "Free trial activated; remember to cancel before renewal")
    if sheet.get("ineligible"):
        return ("Failed", "Account is not eligible for free trial")
    if sheet.get("error") == "item_not_available":
        return ("Failed", "Offer not available for purchase on this account")
    if status == "launched":
        return ("Incomplete", "Billing sheet launched but subscription was not confirmed")
    if status == "exception":
        return ("Failed", rec.get("_hint") or humanize(rec.get("error", "")))
    return ("Failed", STATUS_EN.get(status, "Unknown status; check logs or retry in advanced mode"))


def summary(results: list):
    banner("Summary")
    headers = ("Account", "Result", "Notes")
    rows = []
    ok_n = 0
    for rec in results:
        label, detail = interpret(rec)
        if "Success" in label:
            ok_n += 1
        rows.append((rec.get("email", "?"), label, detail))

    cols = [headers[i] for i in range(3)]
    widths = [dwidth(cols[i]) for i in range(3)]
    for r in rows:
        for i in range(3):
            widths[i] = max(widths[i], dwidth(r[i]))
    widths = [w + 2 for w in widths]

    def hline(l, m, rr):
        return l + m.join("─" * w for w in widths) + rr

    def line(cells):
        return "│" + "│".join(" " + pad(cells[i], widths[i] - 1) for i in range(3)) + "│"

    print("  " + hline("┌", "┬", "┐"))
    print("  " + line(cols))
    print("  " + hline("├", "┼", "┤"))
    for r in rows:
        print("  " + line(r))
    print("  " + hline("└", "┴", "┘"))
    print(f"\n  Total: {len(results)} account(s) | Succeeded: {c(str(ok_n), C.G + C.BOLD)} | "
          f"Failed: {len(results) - ok_n}")
    print(f"  Detailed reports: {c(str(ultra0.REPORT_DIR.resolve()), C.B)}")


# ---------- Advanced CLI Mode ----------
def advanced():
    banner("Advanced Mode · CLI Usage")
    py = "python" if IS_WIN else "python3"
    print(f"""  Direct CLI commands (supports all ultra0.py options):

      {py} pro.py --check                                  Environment self-check
      {py} pro.py --test-plans                             Scan all Ultra (30TB/20TB) & AI Pro (5TB) offers
      {py} pro.py accounts.txt                             Batch run from file
      {py} pro.py --account "email:password:totp_secret"   Single account (AI Pro 5TB)
      {py} ultra0.py --account "email:pass:totp" --plan ultra  Test/activate Ultra 20TB/30TB
      {py} ultra0.py --account "email:pass:totp" --plan all    Try Ultra first, fallback to AI Pro
      {py} pro.py accounts.txt --no-switch                 Verify current Play account without switching
      {py} pro.py accounts.txt --no-add                    Skip adding account (already on device)

  Account line format: email----password----recovery----totp----card----exp----cvc----holder----zip
  Reports are saved in ultra0-report/.""")
    if ask_yes("\n  Run with remaining CLI arguments now?", default=False):
        sys.argv = [sys.argv[0]] + [a for a in sys.argv[1:] if a != "--advanced"]
        if "--plan" not in sys.argv and "--test-plans" not in sys.argv:
            sys.argv += ["--plan", "pro"]
        ultra0.main()


# ---------- Entry Point ----------
def wizard():
    banner("Google AI Pro 5TB & AI Ultra · One-Click Wizard")
    print("  Automates $0 free trial activation for Google AI Pro (5TB) and AI Ultra (20TB / 30TB).")
    _mumu = "MuMu Player 12" if IS_WIN else "MuMu Pro (macOS)"
    print(c(f"  No Android phone? You can use {_mumu} with ROOT enabled.", C.DIM))
    if not environment_check():
        print(c("\n  Environment check failed. Follow the instructions above and run again.", C.Y))
        return 1
    plan, stack = choose_plan()
    if plan == "test":
        return ultra0.test_all_plans()
    rows = read_accounts()
    if not rows:
        print(c("\n  No accounts entered. Exiting.", C.Y))
        return 1
    print(c(f"\n  Loaded {len(rows)} account(s). Starting activation...", C.BOLD))
    results = run_accounts(rows, plan=plan, stack=stack)
    summary(results)
    return 0


def main():
    if "--advanced" in sys.argv:
        advanced()
        return 0
    try:
        return wizard()
    except KeyboardInterrupt:
        print(c("\n\n  Cancelled by user.", C.Y))
        return 130


if __name__ == "__main__":
    sys.exit(main())
