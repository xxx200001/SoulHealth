# -*- coding: utf-8 -*-
"""一键 Cloudflare 隧道启动脚本

用法: python start_tunnel.py [端口号]
默认端口: 5173 (TongueDiag 前端)

会依次尝试:
  1. 系统 PATH 中的 cloudflared
  2. 当前目录下的 cloudflared.exe
  3. winget 安装路径
  4. npx 临时下载
"""
import os
import re
import sys
import glob
import shutil
import subprocess
import webbrowser

port = sys.argv[1] if len(sys.argv) > 1 else "5173"

print("=" * 58, flush=True)
print(f"  SoulHealth 平台 - 开启公网穿透 (端口 {port})", flush=True)
print("=" * 58 + "\n", flush=True)


def find_cloudflared():
    """查找 cloudflared 可执行文件"""
    # 1. scripts 目录或项目根目录
    cur_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.dirname(cur_dir)
    candidates = [
        os.path.join(cur_dir, "cloudflared.exe"),
        os.path.join(cur_dir, "cloudflared"),
        os.path.join(root_dir, "cloudflared.exe"),
        os.path.join(root_dir, "cloudflared"),
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c

    # 2. 系统 PATH 中
    cf = shutil.which("cloudflared")
    if cf:
        return cf

    # 3. winget 安装路径
    appdata = os.environ.get("LOCALAPPDATA", "")
    if appdata:
        pattern = os.path.join(appdata, "Microsoft", "WinGet", "Packages",
                               "*cloudflared*", "cloudflared.exe")
        hits = glob.glob(pattern)
        if hits:
            return hits[0]
    return None


def launch_tunnel():
    cf_exe = find_cloudflared()
    if cf_exe:
        print(f"[OK] 使用本地 cloudflared: {cf_exe}", flush=True)
        cmd = [cf_exe, "tunnel", "--url", f"http://localhost:{port}"]
        return subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace"
        )

    # 4. 回退到 npx
    print("[*] 未找到本地 cloudflared，尝试 npx 临时调用...", flush=True)
    npm_dir = os.path.join(os.environ.get("APPDATA", ""), "npm")
    os.makedirs(npm_dir, exist_ok=True)
    cmd = f'npx --yes cloudflared tunnel --url http://localhost:{port}'
    return subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, encoding="utf-8", errors="replace", shell=True
    )


print("[*] 正在启动穿透服务...\n", flush=True)

try:
    proc = launch_tunnel()
except Exception as e:
    print(f"[错误] 无法启动穿透: {e}", flush=True)
    print("\n请安装 cloudflared 或将 cloudflared.exe 放入 scripts 目录", flush=True)
    input("\n按回车退出...")
    sys.exit(1)

found = False
for line in proc.stdout:
    line_clean = line.strip()
    if line_clean:
        print(line_clean, flush=True)
    m = re.search(r"(https://[a-z0-9-]+\.trycloudflare\.com)", line)
    if m and not found:
        found = True
        url = m.group(1)
        print("\n" + "=" * 62, flush=True)
        print(f"  [√] 公网访问链接已生成: {url}", flush=True)
        print("=" * 62, flush=True)
        # 尝试复制到剪贴板
        try:
            subprocess.run("clip", input=url.strip().encode("utf-8"),
                           check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print("  [提示] 链接已自动复制到剪贴板！", flush=True)
        except Exception:
            pass
        # 自动在浏览器中打开
        try:
            webbrowser.open(url)
            print("  [提示] 已自动在默认浏览器中打开公网链接！", flush=True)
        except Exception:
            pass
        print(f"\n  把上面的链接发给他人，即可在外网直接访问与演示本系统！", flush=True)
        print(f"  按 Ctrl+C 停止穿透\n", flush=True)

proc.wait()
