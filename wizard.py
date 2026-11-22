#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Google AI Pro 5TB —— 傻瓜式开通向导

不懂命令行也能用：Mac 双击 start.command、Windows 双击 start.bat，就会进到这里。
整条流程：环境自检 → 粘账号 → 逐个开通 → 终端表格汇总 → 打印报告目录。

主功能只做 AI Pro 5TB，两条 offer 依次试，命中即停：
    g1.2tb.ai.subs_variant  12months-eft   免费 12 个月
    g1.play.2tb.ai          eft-3mo         免费 3 个月
第一条在部分账号上被 Play 判「已订阅」，自动退到第二条；两条都不成就是号不符合资格。

没有安卓手机也行：用 MuMu 模拟器（Windows 装 MuMu Player 12，Mac 装 MuMu Pro），
在设置里打开 ROOT，本向导会用 adb 连上它，后面的流程和真机完全一样。
frida-server 架构按设备自动选（MuMu-Windows 是 x86_64，MuMu-Mac 和真机是 arm64）。

高级模式：菜单最后一项，或 `python3 wizard.py --advanced`，退回原始命令行用法。

注入、查 offer、确认 0 元等全部逻辑都在 ultra0.py 里，本文件只做外壳调用，不改核心。
账号、密码、2FA、卡号只在内存里传给 ultra0，不写任何文件、不打印、不落盘。
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
    """Windows/Mac 通用：把输出转 UTF-8，并在 Windows 上打开 ANSI 颜色。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # py3.7+
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


# ---------- 终端着色 / 排版 ----------
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
    line = "═" * 54
    print(f"\n{c(line, C.B)}")
    print(f"{c('  ' + title, C.B + C.BOLD)}")
    print(f"{c(line, C.B)}")


def dwidth(s: str) -> int:
    """按终端显示宽度算字符数：中日韩全角算 2。"""
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
    return ans in ("y", "yes", "是", "好", "行")


# ---------- 报错翻成人话 ----------
def humanize(msg: str) -> str:
    """把 adb / frida / Play 的原始报错翻成一句人话。"""
    m = msg or ""
    low = m.lower()
    if "processnotfound" in low or "process not found" in low or "unable to find process" in low:
        return "Google One 没启动起来，重试一次。"
    if "no devices" in low or "没有检测到设备" in m or "device not found" in low:
        return "没检测到设备。真机检查数据线和 USB 调试；模拟器检查是否已启动并开了 ROOT。"
    if "frida-server" in low and ("启动失败" in m or "fail" in low):
        return "设备上的 frida-server 没开起来。"
    if "没装 frida" in m or ("frida" in low and "no module" in low):
        return "电脑没装 frida，运行：pip3 install frida"
    if "找不到 adb" in m:
        return "找不到 adb，请安装 Android platform-tools。"
    if "root" in low or "注入" in m:
        return "设备没 root。模拟器在设置里打开 ROOT 权限并重启；真机需要 Magisk 一类。"
    if "已订阅" in m or "already subscribed" in low:
        return "这个号用过了，换一个。"
    if "不符合" in m or "not eligible" in low:
        return "这个号没有试用资格。"
    # 兜底：不把原始 traceback 丢给用户
    return "出了点问题，重试一次；一直不行就切高级模式看详细日志。"


# ---------- 1. 环境自检 ----------
def _run(fn, *a, **k):
    """调用 ultra0 的某个会 sys.exit 的函数，吞掉退出，返回 (ok, 原始信息)。"""
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
        print(c(f"  ❌ Python {v.major}.{v.minor}，需要 3.9 以上", C.R))
        return False
    print(c(f"  ✅ Python {v.major}.{v.minor}.{v.micro}", C.G))
    return True


def check_frida() -> bool:
    try:
        import frida
        print(c(f"  ✅ frida {frida.__version__}", C.G))
        return True
    except Exception:
        print(c("  ⚠️  电脑没装 frida", C.Y))
        if ask_yes("     现在用 pip3 装一下吗？"):
            r = subprocess.run([sys.executable, "-m", "pip", "install", "frida"])
            if r.returncode == 0:
                try:
                    import frida  # noqa: F401
                    print(c("  ✅ frida 安装完成", C.G))
                    return True
                except Exception:
                    pass
        print(c("     装好后重跑。命令：pip3 install frida", C.DIM))
        return False


def _adb(*args, timeout=60):
    """带 -s SERIAL 的 adb 调用（SERIAL 没设就不带）。"""
    cmd = [ultra0.ADB] + (["-s", ultra0.SERIAL] if ultra0.SERIAL else []) + list(args)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


# Windows 上 MuMu 自带的 adb 常见位置
MUMU_ADB_WIN = [
    r"D:\MuMuPlayerGlobal\nx_device\12.0\shell\adb.exe",
    r"D:\MuMuPlayerGlobal\nx_main\adb.exe",
    r"C:\MuMuPlayerGlobal\nx_device\12.0\shell\adb.exe",
    r"C:\Program Files\Netease\MuMu Player 12\shell\adb.exe",
    r"C:\Program Files\Netease\MuMuPlayer-12.0\shell\adb.exe",
    r"C:\Program Files\Netease\MuMu Player\shell\adb.exe",
]


def discover_adb():
    """跨平台找 adb：Windows 优先 MuMu 自带的，再找 PATH / SDK；Mac 用 ultra0 的候选。"""
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
        print(c(f"  ✅ adb：{adb}", C.G))
        subprocess.run([adb, "start-server"], capture_output=True)
        return True
    print(c("  ❌ 找不到 adb", C.R))
    if IS_WIN:
        print(c("     用 MuMu 的话它自带 adb（MuMu 安装目录里的 shell\\adb.exe）。", C.DIM))
        print(c("     或下载 platform-tools，解压后把目录加进系统 PATH。", C.DIM))
    else:
        print(c("     Mac 装：brew install android-platform-tools", C.DIM))
    print(c("     装好后 `adb devices` 能跑就行。", C.DIM))
    return False


def _devices() -> list:
    out = subprocess.run([ultra0.ADB, "devices"], capture_output=True, text=True).stdout
    return [l.split("\t")[0] for l in out.splitlines()[1:] if "\tdevice" in l]


# MuMu（Mac 版）常见的 adb 端口。新版多为 16384，多开按 +32 递增；老版本可能是 5555 / 7555。
MUMU_PORTS = [16384, 16416, 16448, 16386, 5555, 7555, 21503]


def _try_connect(hostport: str) -> bool:
    subprocess.run([ultra0.ADB, "connect", hostport], capture_output=True, text=True, timeout=10)
    return any(hostport in d or d.startswith("emulator") for d in _devices())


def connect_device() -> bool:
    """确保有一台设备可用（真机或 MuMu 模拟器），把 serial 写进 ultra0.SERIAL。"""
    devs = _devices()
    if len(devs) == 1:
        ultra0.SERIAL = devs[0]
        print(c(f"  ✅ 设备已连接：{devs[0]}", C.G))
        return True
    if len(devs) > 1:
        print("  检测到多台设备：")
        for i, d in enumerate(devs, 1):
            print(f"    {i}) {d}")
        sel = input("  用哪一台？输序号：").strip()
        idx = int(sel) - 1 if sel.isdigit() and 0 < int(sel) <= len(devs) else 0
        ultra0.SERIAL = devs[idx]
        print(c(f"  ✅ 使用：{ultra0.SERIAL}", C.G))
        return True

    # 一台都没有
    print(c("  ⚠️  没检测到设备。", C.Y))
    while True:
        print("     你用哪种？")
        print("       1) 有已 root 的安卓手机（插 USB，开 USB 调试，手机上点允许）")
        print("       2) 没有手机，用 MuMu 模拟器（Mac 版）")
        print("       3) 我知道 ADB 地址，手动输入（形如 127.0.0.1:16384）")
        print("       0) 放弃")
        choice = input("     选：").strip()
        if choice == "0":
            return False
        if choice == "1":
            input("     插好手机、点过允许后，按回车继续…")
        elif choice == "2":
            mumu = "MuMu Player 12（Windows 版）" if IS_WIN else "MuMu Pro（Mac 版，需 Apple Silicon）"
            print(c("     MuMu 模拟器准备步骤：", C.B))
            print(f"       1. 装 {mumu} 并启动一个安卓实例")
            print("       2. 设置中心 → 打开「ROOT 权限」，然后重启模拟器")
            print("       3. 回到这里继续，我来自动连")
            input("     弄好后按回车，开始自动连接…")
            hit = None
            for p in MUMU_PORTS:
                hp = f"127.0.0.1:{p}"
                print(c(f"       尝试 {hp} …", C.DIM))
                if _try_connect(hp):
                    hit = hp
                    break
            if not hit:
                print(c("     自动连接没成功。到 MuMu 顶部菜单 →「工具 / Tools」→「打开 ADB」"
                        "看一眼实际端口，", C.Y))
                print(c("     然后回选项 3 手动输入那个 host:port。", C.Y))
        elif choice == "3":
            hp = input("     输入 host:port：").strip()
            if hp and _try_connect(hp):
                ultra0.SERIAL = hp
                print(c(f"  ✅ 已连接：{hp}", C.G))
                return True
            print(c("     没连上，确认模拟器开着、ROOT 开了、端口对。", C.R))
            continue

        devs = _devices()
        if devs:
            ultra0.SERIAL = devs[0]
            print(c(f"  ✅ 设备已连接：{devs[0]}", C.G))
            return True
        print(c("     还是没有。再试一次，或选 0 放弃。", C.Y))


def _abi() -> str:
    return (_adb("shell", "getprop", "ro.product.cpu.abi", timeout=15).stdout or "").strip()


def _frida_running() -> bool:
    return "frida-server" in (_adb("shell", "ps -A | grep frida-server || true").stdout or "")


def _frida_arch() -> str:
    """把设备 ABI 映射到 frida-server 的架构名。MuMu-Win=x86_64，MuMu-Mac/真机=arm64。"""
    abi = _abi().lower()
    if "x86_64" in abi:
        return "x86_64"
    if "x86" in abi:
        return "x86"
    if "arm64" in abi or "v8" in abi:
        return "arm64"
    return "arm"


def start_frida_server() -> bool:
    """按设备架构推送并启动 frida-server。用 stdlib 下载 + 解压，不依赖 curl/xz，Windows 也能跑。

    和 ultra0 的区别只有一个：架构不写死 arm64，而是看设备。其余流程一致。
    ultra0.run_trial 只做 frida.get_usb_device().attach()，frida-server 在这里先起好即可。
    """
    if _frida_running():
        return True
    try:
        import frida
        ver = frida.__version__
    except Exception:
        print(c("     电脑没装 frida，运行：pip3 install frida", C.DIM))
        return False
    on_dev = _adb("shell", f"ls {ultra0.FRIDA_REMOTE} 2>/dev/null").stdout.strip()
    if not on_dev:
        arch = _frida_arch()
        url = (f"https://github.com/frida/frida/releases/download/{ver}/"
               f"frida-server-{ver}-android-{arch}.xz")
        print(c(f"     下载 frida-server（{arch}, v{ver}）…", C.DIM))
        tmp = Path(tempfile.gettempdir())
        xz_path, raw_path = tmp / "frida-server.xz", tmp / "frida-server"
        try:
            urllib.request.urlretrieve(url, xz_path)
            with lzma.open(xz_path) as f:
                raw_path.write_bytes(f.read())
        except Exception as e:  # noqa: BLE001
            print(c(f"     下载失败：{e}", C.R))
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
    """推送 ultra0 内嵌的计费模块。跨平台写临时文件（不走 ultra0 里写死的 /tmp）。"""
    if _adb("shell", f"ls {ultra0.MODULE_REMOTE} 2>/dev/null").stdout.strip():
        return True
    tmp = Path(tempfile.gettempdir()) / "module_521.apk"
    tmp.write_bytes(ultra0.base64.b64decode(ultra0.MODULE_B64))
    return _adb("push", str(tmp), ultra0.MODULE_REMOTE, timeout=120).returncode == 0


def check_device_ready() -> bool:
    """设备连上后，确认 root / frida-server / 计费模块 / 网络。"""
    ok, info = _run(ultra0.ensure_root)
    if not ok:
        print(c("  ❌ 设备没 root", C.R))
        print(c("     模拟器：设置里打开 ROOT 权限并重启。真机：需要 Magisk/KernelSU。", C.DIM))
        _adb("root")  # 模拟器常见：adb root 能直接拿到 root adbd，顺手试一下
        time.sleep(1)
        ok, info = _run(ultra0.ensure_root)
        if not ok:
            return False
    print(c("  ✅ root 正常", C.G))

    _run(ultra0.ensure_network)  # 清代理、关 Clash，失败也不拦
    if not start_frida_server():
        print(c("  ❌ frida-server 没起来，重试一次。", C.R))
        return False
    print(c("  ✅ frida-server 就位", C.G))

    if not push_module():
        print(c("  ❌ 计费模块没推上去，重试一次。", C.R))
        return False
    print(c("  ✅ 计费模块就位", C.G))
    return True


def environment_check() -> bool:
    banner("第一步 · 环境自检")
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
    print(c("\n  环境全部就绪，可以开始开通了。", C.G + C.BOLD))
    return True


# ---------- 2. 输入账号 ----------
FORMAT_HINT = """\
  一行一个号，字段用四个短横线 ---- 隔开，顺序：
      邮箱----密码----辅助邮箱----2FA密钥----卡号----有效期----CVC----持卡人----邮编
  后面的项留空也行。几个例子：

      abc@gmail.com----密码----
      abc@gmail.com----密码----aux@x.com----JBSWY3DPEHPK3PXP
      abc@gmail.com----密码--------JBSWY3DPEHPK3PXP----4242424242424242----10/29----326----ZHANG SAN----97201

  地址不填默认用俄勒冈（免消费税）。卡里留 1 美元就行，试用期间不扣。"""


def read_accounts() -> list:
    banner("第二步 · 粘贴账号")
    print(FORMAT_HINT)
    print(c("\n  把所有账号粘进来，粘完单独一行输入 END 再回车（或按 Ctrl-D）：", C.BOLD))
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


# ---------- 3. 逐号执行 ----------
def progress_bar(i: int, total: int, width: int = 24) -> str:
    done = int(width * i / total)
    bar = "█" * done + "░" * (width - done)
    pct = int(100 * i / total)
    return f"[{i}/{total}] {c(bar, C.B)} {pct:>3}%"


def run_accounts(rows: list) -> list:
    banner("第三步 · 开始开通")
    ultra0.REPORT_DIR.mkdir(exist_ok=True)
    total = len(rows)
    results = []
    for i, row in enumerate(rows, 1):
        email, pw, _rec, sec = row[0], row[1], row[2], row[3]
        card = ultra0.parse_card(row)
        print(f"\n{progress_bar(i - 1, total)}  正在处理 {c(email, C.BOLD)}")
        try:
            rec = ultra0.process(email, pw, sec, add=True, card=card,
                                 plan="pro", no_switch=False)
        except Exception as e:  # noqa: BLE001 — 单个号出错不影响其他号
            rec = {"email": email, "status": "exception", "_hint": humanize(str(e))}
        results.append(rec)
        # 报告只含邮箱 + 状态 + offer 明细，不含密码/2FA/卡号
        (ultra0.REPORT_DIR / f"{email.split('@')[0]}.json").write_text(
            ultra0.json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        label, _ = interpret(rec)
        tone = C.G if "成功" in label else C.R
        print(f"{progress_bar(i, total)}  {c(label, tone)}")
    return results


# ---------- 4. 结果解读 + 汇总 ----------
PERIOD_CN = {12: "12 个月", 6: "6 个月", 3: "3 个月", 1: "1 个月"}
PERIOD_RANK = {"P1Y": 12, "P12M": 12, "P6M": 6, "P3M": 3, "P1M": 1}


def detect_period(rec: dict) -> str:
    text = (rec.get("sheet") or {}).get("text", "") or ""
    m = re.search(r"(\d+)\s*个月", text) or re.search(r"(\d+)\s*months?", text, re.I)
    if m:
        return f"{m.group(1)} 个月"
    if "1 年" in text or "P1Y" in text or "12 个月" in text:
        return "12 个月"
    best = 0
    for o in rec.get("offers", []):
        if str(o.get("micros")) == "0":
            best = max(best, PERIOD_RANK.get(str(o.get("period")), 0))
    return PERIOD_CN.get(best, "未知时长")


STATUS_CN = {
    "add_account_failed": "加号失败，在设备上手动登录这个号后重试",
    "add_account_error": "加号出错，手动登录后重试",
    "wrong_account": "Play 没切到这个号，手动切好后用高级模式 --no-switch 重试",
    "play_account_switch_failed": "切 Play 账号失败，手动切好再重试",
    "app_not_started": "Google One 没启动起来，重试一次",
    "launch_failed": "没查到可用的免费 offer，换个号",
}


def interpret(rec: dict):
    """返回 (结果, 说明)。结果：开通成功（N 个月）/ 失败。"""
    status = rec.get("status")
    sheet = rec.get("sheet") or {}
    if sheet.get("confirmed") or status == "subscribed":
        return (f"开通成功（{detect_period(rec)}）", "免费试用已下单，记得到期前取消")
    if sheet.get("ineligible"):
        return ("失败", "这个号没有试用资格（用过或不符合）")
    if status == "launched":
        return ("失败", "收银台金额不是 0，没有下单")
    if status == "exception":
        return ("失败", rec.get("_hint") or humanize(rec.get("error", "")))
    return ("失败", STATUS_CN.get(status, "未知情况，重试一次或切高级模式看日志"))


def summary(results: list):
    banner("汇总")
    headers = ("账号", "结果", "说明")
    rows = []
    ok_n = 0
    for rec in results:
        label, detail = interpret(rec)
        if "成功" in label:
            ok_n += 1
        rows.append((rec.get("email", "?"), label, detail))

    cols = [headers[i] for i in range(3)]
    widths = [dwidth(cols[i]) for i in range(3)]
    for r in rows:
        for i in range(3):
            widths[i] = max(widths[i], dwidth(r[i]))
    widths = [w + 2 for w in widths]  # 两边留白

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
    print(f"\n  共 {len(results)} 个号，成功 {c(str(ok_n), C.G + C.BOLD)} 个，"
          f"失败 {len(results) - ok_n} 个。")
    print(f"  明细报告：{c(str(ultra0.REPORT_DIR.resolve()), C.B)}")


# ---------- 高级模式 ----------
def advanced():
    banner("高级模式 · 原始命令行")
    py = "python" if IS_WIN else "python3"
    print(f"""  直接用脚本（参数和 ultra0.py 一致）：

      {py} pro.py --check                      环境自检
      {py} pro.py accounts.txt                 批量（账号文件）
      {py} pro.py --account "邮箱:密码:2FA密钥"   单号
      {py} pro.py accounts.txt --no-switch     不自动切号，只校验当前号
      {py} pro.py accounts.txt --no-add        账号已在设备上，跳过加号

  账号文件格式：邮箱----密码----辅助邮箱----2FA密钥----卡号----有效期----CVC----持卡人----邮编
  报告写在 ultra0-report/。""")
    if ask_yes("\n  现在就把剩下的参数交给脚本跑吗？", default=False):
        # 把 --advanced 之外的参数透传给 ultra0
        sys.argv = [sys.argv[0]] + [a for a in sys.argv[1:] if a != "--advanced"]
        if "--plan" not in sys.argv:
            sys.argv += ["--plan", "pro"]
        ultra0.main()


# ---------- 入口 ----------
def wizard():
    banner("Google AI Pro 5TB · 一键开通向导")
    print("  只做一件事：给 Google 账号开 AI Pro 5TB 的 0 元试用。")
    _mumu = "MuMu Player 12" if IS_WIN else "MuMu Pro（Mac）"
    print(c(f"  没有安卓手机？用 {_mumu} 模拟器也能跑，下一步会带你连。", C.DIM))
    if not environment_check():
        print(c("\n  环境没过，按上面的提示弄好再双击一次。", C.Y))
        return 1
    rows = read_accounts()
    if not rows:
        print(c("\n  没读到账号，退出。", C.Y))
        return 1
    print(c(f"\n  共 {len(rows)} 个号，开始。", C.BOLD))
    results = run_accounts(rows)
    summary(results)
    return 0


def main():
    if "--advanced" in sys.argv:
        advanced()
        return 0
    try:
        return wizard()
    except KeyboardInterrupt:
        print(c("\n\n  已取消。", C.Y))
        return 130


if __name__ == "__main__":
    sys.exit(main())
