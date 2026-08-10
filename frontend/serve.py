#!/usr/bin/env python3
"""
Simple HTTP server для frontend (Stage 4).

Запускает статический HTTP server для frontend/index.html
с автоматическим открытием в браузере.

Использование:
    python frontend/serve.py
    python frontend/serve.py --port 8080
"""

import argparse
import http.server
import socketserver
import webbrowser
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="Запуск frontend HTTP server")
    parser.add_argument("--port", type=int, default=8080, help="Порт (default: 8080)")
    parser.add_argument("--no-browser", action="store_true", help="Не открывать браузер")
    args = parser.parse_args()

    # Переход в frontend каталог
    frontend_dir = Path(__file__).parent
    if frontend_dir.exists():
        import os
        os.chdir(frontend_dir)

    # Запуск HTTP server
    handler = http.server.SimpleHTTPRequestHandler

    with socketserver.TCPServer(("", args.port), handler) as httpd:
        url = f"http://localhost:{args.port}"
        print(f"Frontend HTTP server запущен на {url}")
        print(f"Откройте в браузере: {url}")
        print("Нажмите Ctrl+C для остановки")

        # Открыть в браузере
        if not args.no_browser:
            webbrowser.open(url)

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nСервер остановлен")


if __name__ == "__main__":
    main()
