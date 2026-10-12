"""一键启动（NFR-01、T6.1）：python scripts/start.py

依次完成：检查 Python ≥ 3.11、Node ≥ 20 → 创建虚拟环境 .venv 并安装后端依赖 → npm ci 并构建前端
→ 首次运行时初始化数据库（已有数据库不会被清空）→ 启动服务（默认 http://localhost:8000）。
只使用标准库，Windows、macOS、Linux 通用。依赖已安装时会跳过安装步骤，再次启动只需几秒。
"""
import hashlib
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_REQ = ROOT / "src" / "backend" / "requirements.txt"
FRONTEND = ROOT / "src" / "frontend"
VENV = ROOT / ".venv"
VENV_PY = VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
MIN_PYTHON = (3, 11)
MIN_NODE = 20


def step(msg: str) -> None:
    print(f"\n==> {msg}", flush=True)


def fail(msg: str) -> None:
    print(f"\n[失败] {msg}", flush=True)
    sys.exit(1)


def run(cmd: list, cwd: Path = ROOT) -> None:
    result = subprocess.run([str(c) for c in cmd], cwd=cwd)
    if result.returncode != 0:
        fail(f"命令执行失败（退出码 {result.returncode}）：{' '.join(map(str, cmd))}")


def digest(*files: Path) -> str:
    h = hashlib.sha256()
    for f in files:
        h.update(f.read_bytes())
    return h.hexdigest()


def check_versions() -> str:
    step("检查运行环境")
    if sys.version_info < MIN_PYTHON:
        fail(f"需要 Python ≥ 3.11，当前为 {sys.version.split()[0]}。Windows 可尝试：py -3.11 scripts/start.py")
    print(f"Python {sys.version.split()[0]}")
    npm = shutil.which("npm")
    node = shutil.which("node")
    if not node or not npm:
        fail("未找到 Node.js / npm。请安装 Node ≥ 20（https://nodejs.org）后重试")
    out = subprocess.run([node, "--version"], capture_output=True, text=True).stdout.strip()
    major = int(out.lstrip("v").split(".")[0] or 0)
    if major < MIN_NODE:
        fail(f"需要 Node ≥ 20，当前为 {out}")
    print(f"Node {out}")
    return npm


def install_backend() -> None:
    marker = VENV / ".requirements.sha256"
    if not VENV_PY.exists():
        step("创建虚拟环境 .venv")
        run([sys.executable, "-m", "venv", VENV])
    want = digest(BACKEND_REQ)
    if marker.exists() and marker.read_text() == want:
        step("后端依赖已是最新，跳过安装")
        return
    step("安装后端依赖（首次约 1 分钟）")
    run([VENV_PY, "-m", "pip", "install", "--disable-pip-version-check", "-q", "-r", BACKEND_REQ])
    marker.write_text(want)


def build_frontend(npm: str) -> None:
    marker = FRONTEND / "node_modules" / ".package-lock.sha256"
    want = digest(FRONTEND / "package-lock.json")
    if marker.exists() and marker.read_text() == want:
        step("前端依赖已是最新，跳过安装")
    else:
        step("安装前端依赖（npm ci，首次约 1 分钟）")
        run([npm, "ci", "--no-audit", "--no-fund"], cwd=FRONTEND)
        marker.write_text(want)
    step("构建前端")
    run([npm, "run", "build"], cwd=FRONTEND)


def main() -> None:
    for stream in (sys.stdout, sys.stderr):  # 管道或重定向时统一 UTF-8 输出，避免中文乱码
        if not stream.isatty():
            stream.reconfigure(encoding="utf-8", errors="replace")
    started = time.time()
    npm = check_versions()
    install_backend()
    build_frontend(npm)
    step("初始化数据库（已有数据库时跳过，不会清空数据）")
    run([VENV_PY, ROOT / "scripts" / "manage.py", "init"])
    step(f"准备完成，用时 {time.time() - started:.0f} 秒。启动服务")
    try:
        subprocess.run([str(VENV_PY), str(ROOT / "scripts" / "manage.py"), "serve"], cwd=ROOT)
    except KeyboardInterrupt:
        pass
    print("\n服务已停止。", flush=True)


if __name__ == "__main__":
    main()
