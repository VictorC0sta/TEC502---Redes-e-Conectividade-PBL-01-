import json
import socket
import time
import random
import os

SENSOR_ID = os.environ.get("SENSOR_ID", "sensor_umidade_1")
SERVER_IP  = os.environ.get("SERVER_IP", "server")
UDP_PORT   = int(os.environ.get("UDP_PORT", 5001))

# Limites normais de operação
UMIDADE_MIN = 45.0
UMIDADE_MAX = 85.0

COOLDOWN_SEGUNDOS = int(os.environ.get("COOLDOWN_SEGUNDOS", 30))
INTERVALO_ENVIO   = float(os.environ.get("INTERVALO_ENVIO", 0.1))

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
print(f"[{SENSOR_ID}] Iniciando → UDP {SERVER_IP}:{UDP_PORT}")
print(f"[{SENSOR_ID}] Limites: {UMIDADE_MIN}% – {UMIDADE_MAX}% | Cooldown: {COOLDOWN_SEGUNDOS}s")

valor = round(random.uniform(55.0, 65.0), 2)

# Estado de cooldown
em_cooldown       = False
# Bug 1 corrigido: cooldown_restante agora em PASSOS, não em segundos.
# A 0.1s/passo, 30s = 300 passos. O código original decrementava 1/passo
# mas inicializava com 30 (segundos), fazendo o cooldown durar só 3s reais.
cooldown_restante = 0

# Bug 1 corrigido: drift cíclico em vez de random walk simétrico.
# Fase "subindo": delta médio positivo → valor sobe ~0.20%/passo.
# Fase "descendo": delta médio negativo → valor cai de volta.
# Cada fase dura 150–350 passos (15s–35s a 0.1s/passo).
fase             = "subindo"
passos_restantes = random.randint(150, 350)

try:
    while True:

        if em_cooldown:
            # Cooldown: puxa suavemente de volta ao centro da faixa
            alvo  = 65.0
            delta = random.uniform(-0.3, 0.1) + (alvo - valor) * 0.08
            valor = round(max(UMIDADE_MIN + 2, min(UMIDADE_MAX - 2, valor + delta)), 2)

            cooldown_restante -= 1
            if cooldown_restante <= 0:
                em_cooldown = False
                print(f"[{SENSOR_ID}] ✅ Cooldown encerrado — voltando operação normal")
            else:
                segundos = cooldown_restante * INTERVALO_ENVIO
                print(f"[{SENSOR_ID}] [COOLDOWN {segundos:.0f}s] {valor}%")

        else:
            passos_restantes -= 1

            if fase == "subindo":
                delta = random.uniform(0.08, 0.35) + random.uniform(-0.10, 0.10)
                if passos_restantes <= 0:
                    fase             = "descendo"
                    passos_restantes = random.randint(150, 350)
                    print(f"[{SENSOR_ID}] 🔁 Iniciando fase de descida em {valor}%")

            else:  # descendo
                delta = random.uniform(-0.35, -0.08) + random.uniform(-0.10, 0.10)
                if passos_restantes <= 0 or valor < 52.0:
                    fase             = "subindo"
                    passos_restantes = random.randint(150, 350)
                    print(f"[{SENSOR_ID}] 🔁 Iniciando fase de subida em {valor}%")

            valor = round(max(38.0, min(92.0, valor + delta)), 2)

            fora_do_limite = valor > UMIDADE_MAX or valor < UMIDADE_MIN
            if fora_do_limite:
                # Converte segundos de cooldown em passos
                cooldown_restante = int(COOLDOWN_SEGUNDOS / INTERVALO_ENVIO)
                em_cooldown       = True
                print(f"[{SENSOR_ID}] ⚠ {valor}% fora do limite → cooldown de {COOLDOWN_SEGUNDOS}s")
            else:
                print(f"[{SENSOR_ID}] [{fase}] {valor}%")

        payload = json.dumps({
            "id":      SENSOR_ID,
            "tipo":    "umidade",
            "umidade": valor
        }).encode("utf-8")

        sock.sendto(payload, (SERVER_IP, UDP_PORT))
        time.sleep(INTERVALO_ENVIO)

except KeyboardInterrupt:
    print(f"\n[{SENSOR_ID}] Encerrando...")
    sock.close()