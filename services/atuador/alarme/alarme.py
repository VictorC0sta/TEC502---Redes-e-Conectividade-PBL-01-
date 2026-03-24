import socket
import json
import os
from datetime import datetime

TCP_IP = "0.0.0.0"
TCP_PORT = 6000
ATUADORES_FILE = "dados/atuadores.json"

os.makedirs("dados", exist_ok=True)

def carregar_atuadores():
    try:
        with open(ATUADORES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def salvar_atuacao(evento):
    historico = carregar_atuadores()
    historico.append(evento)
    with open(ATUADORES_FILE, "w", encoding="utf-8") as f:
        json.dump(historico, f, indent=2)

def executar_alarme(cmd):
    valor = cmd.get("valor")
    sensor = cmd.get("sensor")
    nome_sensor = cmd.get("nome_sensor")

    print(f"\n{'='*40}")
    print(f"🚨 [ALARME] {sensor.upper()} em {valor} — fora do limite!")
    print(f"   → Capturado por: {nome_sensor}")
    print(f"{'='*40}\n")
    print("\a")

    evento = {
        "nome_sensor": nome_sensor,
        "sensor": sensor,
        "valor": valor,
        "acao": "ALARME",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    salvar_atuacao(evento)

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind((TCP_IP, TCP_PORT))
sock.listen(5)

print(f"[ALARME] Escutando TCP na porta {TCP_PORT}...")

try:
    while True:
        conn, addr = sock.accept()
        with conn:
            data = conn.recv(1024)
            if data:
                try:
                    comando = json.loads(data.decode("utf-8"))
                    executar_alarme(cmd=comando)
                    conn.sendall(b'{"status": "ok"}')
                except (json.JSONDecodeError, UnicodeDecodeError):
                    conn.sendall(b'{"status": "erro"}')

except KeyboardInterrupt:
    print("\n[ALARME] Encerrando...")
    sock.close()