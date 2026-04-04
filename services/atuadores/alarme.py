import socket
import json
import os
from datetime import datetime, timezone, timedelta

TCP_IP         = "0.0.0.0"
TCP_PORT       = 6000
ATUADORES_FILE = "data/atuadores.json"
FUSO_BRASIL    = timezone(timedelta(hours=-3))

COOLDOWN_SEGUNDOS = int(os.environ.get("ALARME_COOLDOWN", 30))

_ultimo_alarme: dict[str, datetime] = {}

os.makedirs("data", exist_ok=True)


def timestamp_br():
    return datetime.now(FUSO_BRASIL).strftime("%Y-%m-%d %H:%M:%S.%f")


def agora():
    return datetime.now(FUSO_BRASIL)


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


def em_cooldown(nome_sensor: str) -> tuple[bool, float]:
    ultimo = _ultimo_alarme.get(nome_sensor)
    if ultimo is None:
        return False, 0.0
    decorrido = (agora() - ultimo).total_seconds()
    restante  = COOLDOWN_SEGUNDOS - decorrido
    return restante > 0, max(0.0, restante)


def executar_alarme(cmd: dict) -> str:
    valor       = cmd.get("valor")
    sensor      = cmd.get("sensor")
    nome_sensor = cmd.get("nome_sensor", "desconhecido")

    if not sensor or valor is None:
        print("[ALARME] Comando inválido recebido.")
        return "erro"

    cooldown, restante = em_cooldown(nome_sensor)
    if cooldown:
        print(
            f"[ALARME] ⏳ Ignorado — {nome_sensor} em cooldown "
            f"({restante:.0f}s restantes)"
        )
        return "cooldown"

    _ultimo_alarme[nome_sensor] = agora()

    print(f"\n{'='*42}")
    print(f"🚨 [ALARME] {sensor.upper()} = {valor} — fora do limite!")
    print(f"   Sensor  : {nome_sensor}")
    print(f"   Horário : {timestamp_br()}")
    print(f"   Cooldown: próximo alarme deste sensor em {COOLDOWN_SEGUNDOS}s")
    print(f"{'='*42}\n")
    print("\a")

    salvar_atuacao({
        "nome_sensor": nome_sensor,
        "sensor":      sensor,
        "valor":       valor,
        "acao":        "ALARME",
        "horario":   timestamp_br(),
    })
    return "ok"


sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind((TCP_IP, TCP_PORT))
sock.listen(5)

print(f"[ALARME] Escutando TCP na porta {TCP_PORT}...")
print(f"[ALARME] Cooldown por sensor: {COOLDOWN_SEGUNDOS}s")

try:
    while True:
        conn, addr = sock.accept()
        with conn:
            data = conn.recv(1024)
            if not data:
                continue
            try:
                comando   = json.loads(data.decode("utf-8"))
                resultado = executar_alarme(comando)
                conn.sendall(json.dumps({"status": resultado}).encode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                print(f"[ALARME] Erro ao decodificar: {e}")
                conn.sendall(b'{"status": "erro"}')

except KeyboardInterrupt:
    print("\n[ALARME] Encerrando...")
    sock.close()