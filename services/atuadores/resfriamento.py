import socket
import json
import os
from datetime import datetime, timezone, timedelta

TCP_IP         = "0.0.0.0"
TCP_PORT       = 6001
ATUADORES_FILE = "data/atuadores.json"
FUSO_BRASIL    = timezone(timedelta(hours=-3))

os.makedirs("data", exist_ok=True)

SENSORES_TEMP   = os.environ.get("SENSORES_TEMP", "sensor_temp_1,sensor_temp_2,sensor_temp_3")
SENSORES_LIST   = [s.strip() for s in SENSORES_TEMP.split(",")]
TCP_SENSOR_PORT = int(os.environ.get("TCP_SENSOR_PORT", 7000))


def timestamp_br():
    return datetime.now(FUSO_BRASIL).strftime("%Y-%m-%d %H:%M:%S.%f")


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


def notificar_sensores():
    for sensor_id in SENSORES_LIST:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(3)
                s.connect((sensor_id, TCP_SENSOR_PORT))
                s.sendall(json.dumps({"acao": "RESFRIAMENTO"}).encode("utf-8"))
                s.recv(1024)
                print(f"[RESFRIAMENTO] ✅ {sensor_id} notificado!")
        except (socket.error, OSError) as e:
            print(f"[RESFRIAMENTO] ⚠️  Não foi possível notificar {sensor_id}: {e}")


def executar_resfriamento(cmd):
    valor       = cmd.get("valor")
    nome_sensor = cmd.get("nome_sensor")
    sensor      = cmd.get("sensor")

    print(f"\n{'='*40}")
    print(f"🌀 [RESFRIAMENTO] Temperatura crítica: {valor}°C")
    print(f"   → Capturado por: {nome_sensor}")
    print("   → Ventiladores industriais ativados")
    print("   → Válvula de água gelada aberta")
    print("   → Redução de carga na máquina iniciada")
    print(f"{'='*40}\n")
    print("\a\a")

    notificar_sensores()

    salvar_atuacao({
        "nome_sensor": nome_sensor,
        "sensor":      sensor,
        "valor":       valor,
        "acao":        "RESFRIAMENTO",
        "horario":   timestamp_br(),
    })


sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind((TCP_IP, TCP_PORT))
sock.listen(5)

print(f"[RESFRIAMENTO] Escutando TCP na porta {TCP_PORT}...")
print(f"[RESFRIAMENTO] Sensores a notificar: {SENSORES_LIST}")

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
                except (json.JSONDecodeError, UnicodeDecodeError):
                    conn.sendall(b'{"status": "erro"}')

except KeyboardInterrupt:
    print("\n[RESFRIAMENTO] Encerrando...")
    sock.close()