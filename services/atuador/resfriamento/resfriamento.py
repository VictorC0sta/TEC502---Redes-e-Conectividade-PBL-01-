import socket
import json
import os
from datetime import datetime

TCP_IP = "0.0.0.0"
TCP_PORT = 6001                      
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

def executar_resfriamento(cmd): 
    valor = cmd.get("valor")
    nome_sensor = cmd.get("nome_sensor")
    sensor = cmd.get("sensor")

    print(f"\n{'='*40}")
    print(f"🌀 [RESFRIAMENTO] Temperatura crítica: {valor}°C")
    print(f"   → Capturado por: {nome_sensor}")
    print("   → Ventiladores industriais ativados")
    print("   → Válvula de água gelada aberta")
    print("   → Redução de carga na máquina iniciada")
    print("{'='*40}\n")
    print("\a\a")

    # Notifica o sensor_temp para simular queda de temperatura
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect(("sensor_temp", 7000))          # hostname do container
            s.sendall(json.dumps({"acao": "RESFRIAMENTO"}).encode("utf-8"))
    except (socket.error, OSError) as e:
        print(f"[RESFRIAMENTO] ⚠️  Não foi possível notificar sensor_temp: {e}")

    evento = {
        "nome_sensor": nome_sensor,
        "sensor": sensor,
        "valor": valor,
        "acao": "RESFRIAMENTO",
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    salvar_atuacao(evento)

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind((TCP_IP, TCP_PORT))
sock.listen(5)

print(f"[RESFRIAMENTO] Escutando TCP na porta {TCP_PORT}...")

try:
    while True:
        conn, addr = sock.accept()
        with conn:
            data = conn.recv(1024)
            if data:
                try:
                    comando = json.loads(data.decode("utf-8"))
                    executar_resfriamento(cmd=comando)
                    conn.sendall(b'{"status": "ok"}')
                except json.JSONDecodeError:
                    conn.sendall(b'{"status": "erro"}')

except KeyboardInterrupt:
    print("\n[RESFRIAMENTO] Encerrando...")
    sock.close()