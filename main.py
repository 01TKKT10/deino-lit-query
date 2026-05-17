#!/usr/bin/env python3
"""
Deinococcus radiodurans 文献查询系统 - 一键启动器
运行方式: python main.py（或双击运行）
"""

import http.server
import socketserver
import webbrowser
import threading
import os

PORT = 8765
DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(DIR)

class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass  # 静默日志

    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        super().end_headers()

def open_browser():
    try:
        webbrowser.open(f'http://localhost:{PORT}', new=2)
        print(f'[信息] 已自动打开浏览器')
    except Exception:
        print(f'[提示] 请手动访问: http://localhost:{PORT}')

if __name__ == '__main__':
    print('=' * 55)
    print('  Deinococcus radiodurans 文献查询系统 v2')
    print('=' * 55)

    for f in ['index.html', 'database.json']:
        if not os.path.exists(f):
            print(f'[错误] 未找到 {f}')
            input('按 Enter 退出...')
            exit(1)

    socketserver.TCPServer.allow_reuse_address = True
    try:
        with socketserver.TCPServer(('', PORT), Handler) as httpd:
            print(f'\n[启动] 服务器: http://localhost:{PORT}')
            print('[数据] 1,344 篇文献 (PubMed规范化数据)')
            threading.Timer(1.0, open_browser).start()
            print('\n[提示] 按 Ctrl+C 停止\n')
            httpd.serve_forever()
    except KeyboardInterrupt:
        print('\n[关闭] 服务器已停止')
    except OSError as e:
        print(f'\n[错误] 端口 {PORT} 被占用: {e}')
        input('按 Enter 退出...')
