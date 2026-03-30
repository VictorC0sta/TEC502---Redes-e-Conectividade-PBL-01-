import json
import socket
import time
import random
import os

SENSOR_ID    = os.environ.get("SENSOR_ID", "sensor_umidade_1")
SERVER_IP    = os.environ.get("SERVER_IP", "server")
UDP_PORT     = int(os.environ.get("UDP_PORT", 5001))

# ── Limites normais de operação ───────────────────────────────────────────────
UMIDADE_MIN  = 45.0
UMIDADE_MAX  = 85.0

# ── Configuração de cooldown ──────────────────────────────────────────────────
# Após disparar um alarme, o sensor fica COOLDOWN_SEGUNDOS enviando
# apenas valores dentro da faixa normal (simulando que o problema foi tratado).
COOLDOWN_SEGUNDOS = int(os.environ.get("COOLDOWN_SEGUNDOS", 30))
INTERVALO_ENVIO   = float(os.environ.get("INTERVALO_ENVIO", 0.1))  # segundos entre envios

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
print(f"[{SENSOR_ID}] Iniciando → UDP {SERVER_IP}:{UDP_PORT}")
print(f"[{SENSOR_ID}] Limites: {UMIDADE_MIN}% – {UMIDADE_MAX}% | Cooldown: {COOLDOWN_SEGUNDOS}s")

em_cooldown        = False
cooldown_restante  = 0  # segundos restantes no cooldown

try:
    while True:
        if em_cooldown:
            # Durante o cooldown envia apenas valores normais
            valor = round(random.uniform(UMIDADE_MIN + 2, UMIDADE_MAX - 2), 2)
            cooldown_restante -= INTERVALO_ENVIO

            if cooldown_restante <= 0:
                em_cooldown = False
                print(f"[{SENSOR_ID}] Cooldown encerrado — voltando operação normal")
            else:
                print(f"[{SENSOR_ID}] [COOLDOWN {cooldown_restante:.0f}s] Enviado: {valor}%")
        else:
            # Operação normal — pode gerar valor fora do limite
            valor = round(random.uniform(40.0, 90.0), 2)

            fora_do_limite = valor > UMIDADE_MAX or valor < UMIDADE_MIN
            if fora_do_limite:
                em_cooldown       = True
                cooldown_restante = COOLDOWN_SEGUNDOS
                print(f"[{SENSOR_ID}] ⚠ Valor fora do limite: {valor}% → entrando em cooldown de {COOLDOWN_SEGUNDOS}s")
            else:
                print(f"[{SENSOR_ID}] Enviado: {valor}%")

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