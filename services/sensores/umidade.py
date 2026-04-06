import json
import socket
import time
import random
import os

SENSOR_ID = os.environ.get("SENSOR_ID", "sensor_umidade_1")
SERVER_IP  = os.environ.get("SERVER_IP", "server")
UDP_PORT   = int(os.environ.get("UDP_PORT", 5001))

UMIDADE_MIN = 45.0
UMIDADE_MAX = 85.0

INTERVALO_ENVIO = float(os.environ.get("INTERVALO_ENVIO", 0.1))

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
print(f"[{SENSOR_ID}] Iniciando → UDP {SERVER_IP}:{UDP_PORT}")

# Valor inicial e fase aleatória — evita sincronismo entre sensores
valor            = round(random.uniform(58.0, 72.0), 2)
fase             = random.choice(["subindo", "descendo"])
passos_restantes = random.randint(200, 500)

# Momentum: inércia que suaviza mudanças bruscas de direção
momentum = 0.0

try:
    while True:
        passos_restantes -= 1

        if fase == "subindo":
            # Sobe com intensidade variável — às vezes passa de 85% naturalmente
            alvo_delta = random.uniform(0.03, 0.10)

            # Perto do teto: desacelera mas NÃO para — pode ultrapassar 85%
            if valor > 80.0:
                alvo_delta *= 0.5
            if valor > 87.0:
                alvo_delta *= 0.2  # quase estagna, sem clampar artificialmente

            if passos_restantes <= 0:
                fase             = "descendo"
                passos_restantes = random.randint(200, 500)
                print(f"[{SENSOR_ID}] 🔁 Descida em {valor}%")

        else:  # descendo
            alvo_delta = random.uniform(-0.10, -0.03)

            # Perto do piso: desacelera simetricamente
            if valor < 52.0:
                alvo_delta *= 0.5
            if valor < 47.0:
                alvo_delta *= 0.2

            if passos_restantes <= 0 or valor < 52.0:
                fase             = "subindo"
                passos_restantes = random.randint(200, 500)
                print(f"[{SENSOR_ID}] 🔁 Subida em {valor}%")

        # Momentum: suaviza a curva — evita zigue-zague abrupto
        momentum = momentum * 0.75 + alvo_delta * 0.25
        ruido    = random.uniform(-0.015, 0.015)
        delta    = momentum + ruido

        # Hard limit físico apenas nos extremos absolutos (não nos limites de alarme)
        valor = round(max(35.0, min(95.0, valor + delta)), 2)

        status = ""
        if valor > UMIDADE_MAX:
            status = " ⚠ ACIMA DO LIMITE"
        elif valor < UMIDADE_MIN:
            status = " ⚠ ABAIXO DO LIMITE"

        print(f"[{SENSOR_ID}] [{fase}] {valor}%{status}")

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