"""啟動方式：python -m app [--host 127.0.0.1] [--port 5000]"""

import argparse
import secrets

from . import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="課堂搶答系統")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5000)
    args = parser.parse_args()

    # 老師金鑰每次啟動隨機產生，只存在記憶體並印在終端機。
    teacher_key = secrets.token_urlsafe(16)
    app = create_app(teacher_key)

    base = f"http://{'127.0.0.1' if args.host in ('0.0.0.0', '') else args.host}:{args.port}"
    print("=" * 60, flush=True)
    print(f"學生頁面：{base}/", flush=True)
    print(f"老師頁面：{base}/teacher?key={teacher_key}", flush=True)
    print("（老師網址請勿分享給學生；重新啟動後金鑰會改變）", flush=True)
    print("=" * 60, flush=True)
    app.run(host=args.host, port=args.port, threaded=True, use_reloader=False, debug=False)


if __name__ == "__main__":
    main()
