"""管理命令（03 §10.2）。

    python scripts/manage.py serve    # 启动服务（端口取 APP_PORT，默认 8000）
    python scripts/manage.py init     # 初始化数据库；已存在则跳过，不清库
    python scripts/manage.py reset    # 清库并重新导入种子数据
    python scripts/manage.py test [pytest 参数...]
    python scripts/manage.py eval --mode fallback|model   # AI 评测（AC-26）

项目根目录下存在 .venv 时，自动切换到虚拟环境的解释器执行。
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "src" / "backend"


def _venv_python() -> Path:
    if os.name == "nt":
        return ROOT / ".venv" / "Scripts" / "python.exe"
    return ROOT / ".venv" / "bin" / "python"


def _ensure_venv() -> None:
    venv_py = _venv_python()
    in_venv = Path(sys.prefix).resolve() == (ROOT / ".venv").resolve()
    if venv_py.exists() and not in_venv:
        sys.exit(subprocess.call([str(venv_py), *sys.argv]))


def cmd_serve(args) -> int:
    import uvicorn

    from app.config import get_settings

    port = get_settings().app_port
    print(f"[serve] 服务地址：http://localhost:{port}  （按 Ctrl+C 停止）", flush=True)
    uvicorn.run("app.main:app", host=args.host, port=port, log_level="warning")
    return 0


def cmd_init(_args) -> int:
    from app.clock import SystemClock
    from app.config import get_settings
    from app.seed import init_database

    settings = get_settings()
    created = init_database(settings, SystemClock().now())
    if created:
        print(f"[init] 已创建数据库并导入种子数据：{settings.db_file}")
    else:
        print(f"[init] 数据库已存在，跳过（如需清库请执行 reset）：{settings.db_file}")
    return 0


def cmd_reset(_args) -> int:
    from app.clock import SystemClock
    from app.config import get_settings
    from app.seed import reset_database

    settings = get_settings()
    reset_database(settings, SystemClock().now())
    print(f"[reset] 已清库并重新导入种子数据：{settings.db_file}")
    return 0


def cmd_test(args) -> int:
    return subprocess.call([sys.executable, "-m", "pytest", *args.pytest_args], cwd=ROOT)


def cmd_eval(args) -> int:
    sys.path.insert(0, str(ROOT / "tests" / "ai_eval"))
    import run_eval

    return run_eval.main(args.mode)


def _utf8_output() -> None:
    """输出被重定向或经管道（如 Git Bash）时，Windows 默认用 GBK 编码，中文会乱码；统一改为 UTF-8。"""
    for stream in (sys.stdout, sys.stderr):
        if not stream.isatty():
            stream.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    _ensure_venv()
    _utf8_output()
    sys.path.insert(0, str(BACKEND))

    parser = argparse.ArgumentParser(description="校园活动报名与签到系统 管理命令")
    sub = parser.add_subparsers(dest="command", required=True)
    p_serve = sub.add_parser("serve", help="启动服务（端口取配置 APP_PORT）")
    p_serve.add_argument("--host", default="127.0.0.1", help="监听地址；容器中使用 0.0.0.0")
    p_serve.set_defaults(func=cmd_serve)
    sub.add_parser("init", help="初始化数据库（已存在则跳过）").set_defaults(func=cmd_init)
    sub.add_parser("reset", help="清库并重新导入种子数据").set_defaults(func=cmd_reset)
    sub.add_parser("test", help="运行全部自动化测试；其余参数原样传给 pytest").set_defaults(func=cmd_test)
    p_eval = sub.add_parser("eval", help="运行 AI 评测集，结果写入 tests/ai_eval/results/")
    p_eval.add_argument("--mode", choices=["fallback", "model"], default="fallback")
    p_eval.set_defaults(func=cmd_eval)

    # 用 parse_known_args 透传 pytest 参数：argparse.REMAINDER 无法接收以 - 开头的参数（如 -v）
    args, extra = parser.parse_known_args()
    if extra and args.command != "test":
        parser.error(f"无法识别的参数：{' '.join(extra)}")
    args.pytest_args = extra
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
