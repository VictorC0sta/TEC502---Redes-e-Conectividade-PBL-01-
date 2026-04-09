# =============================================================================
# SENSOR_UMIDADE.PY — Simulador de Sensor de Umidade (UDP)
# =============================================================================

import json
import socket
import time
import random
import os

# =============================================================================
# CONFIGURAÇÃO (via variáveis de ambiente — facilita uso com Docker)
# =============================================================================

# Identificador único deste sensor — diferencia instâncias rodando em paralelo
SENSOR_ID = os.environ.get("SENSOR_ID", "sensor_umidade_1")

# Endereço do servidor central (hostname Docker ou IP direto)
SERVER_IP = os.environ.get("SERVER_IP", "server")

# Porta UDP do servidor que recebe as leituras
UDP_PORT  = int(os.environ.get("UDP_PORT", 5001))

# Faixa de operação normal — valores fora disso geram alerta no terminal
# (a decisão de acionar alarme/resfriamento fica no server.py)
UMIDADE_MIN = 45.0   # %
UMIDADE_MAX = 85.0   # %

# Intervalo entre cada envio de leitura (em segundos)
# Padrão: 0.1s = 10 leituras por segundo — alto para fins de simulação/teste
INTERVALO_ENVIO = float(os.environ.get("INTERVALO_ENVIO", 0.1))


# =============================================================================
# INICIALIZAÇÃO DO SOCKET UDP
# =============================================================================

# UDP (SOCK_DGRAM): sem conexão, sem garantia de entrega, mas mais leve.
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
print(f"[{SENSOR_ID}] Iniciando → UDP {SERVER_IP}:{UDP_PORT}")


# =============================================================================
# ESTADO INICIAL DA SIMULAÇÃO
# =============================================================================

# Valor inicial aleatório dentro de uma faixa confortável (longe dos limites)
valor = round(random.uniform(58.0, 72.0), 2)

# Fase define a direção atual da curva: "subindo" ou "descendo"
fase = random.choice(["subindo", "descendo"])

# Quantidade de passos (leituras) até a próxima inversão de fase
# A variação aleatória evita que múltiplos sensores fiquem em sincronia
passos_restantes = random.randint(200, 500)

# Momentum: acumulador de inércia que suaviza transições de direção.
# Sem isso, o valor mudaria de forma telegráfica (zigue-zague abrupto).
momentum = 0.0


# =============================================================================
# LOOP PRINCIPAL DE SIMULAÇÃO E ENVIO
# =============================================================================

try:
    while True:
        passos_restantes -= 1

        # ── Fase SUBINDO ──────────────────────────────────────────────────────
        if fase == "subindo":
            # Delta positivo: o sensor está aumentando a umidade
            alvo_delta = random.uniform(0.03, 0.10)

            # Desaceleração natural perto do teto — imita saturação física.
            # O sensor pode ultrapassar 85% (limite de alarme) naturalmente;
            if valor > 80.0:
                alvo_delta *= 0.5   # Desacelera ao se aproximar do limite
            if valor > 87.0:
                alvo_delta *= 0.2   # Quase estagna — imita resistência física

            # Inverte a fase quando esgota os passos planejados
            if passos_restantes <= 0:
                fase             = "descendo"
                passos_restantes = random.randint(200, 500)
                print(f"[{SENSOR_ID}] 🔁 Descida em {valor}%")

        # ── Fase DESCENDO ─────────────────────────────────────────────────────
        else:
            # Delta negativo: o sensor está reduzindo a umidade
            alvo_delta = random.uniform(-0.10, -0.03)

            # Desaceleração simétrica perto do piso
            if valor < 52.0:
                alvo_delta *= 0.5
            if valor < 47.0:
                alvo_delta *= 0.2

            # Inverte a fase ao esgotar passos OU ao se aproximar do piso
            # (evita que o sensor fique abaixo de 52% por muito tempo)
            if passos_restantes <= 0 or valor < 52.0:
                fase             = "subindo"
                passos_restantes = random.randint(200, 500)
                print(f"[{SENSOR_ID}] 🔁 Subida em {valor}%")

        # ── Cálculo do delta com momentum e ruído ─────────────────────────────
        momentum = momentum * 0.75 + alvo_delta * 0.25

        # Pequenas oscilações aleatórias que imitam variação ambiental real do sensor
        ruido = random.uniform(-0.015, 0.015)

        delta = momentum + ruido

        # Hard limit físico absoluto: impede valores absurdos (sensor quebrado).
        valor = round(max(35.0, min(95.0, valor + delta)), 2)

        # ── Log local com indicação visual de violação de limite ──────────────
        status = ""
        if valor > UMIDADE_MAX:
            status = " ⚠ ACIMA DO LIMITE"
        elif valor < UMIDADE_MIN:
            status = " ⚠ ABAIXO DO LIMITE"

        print(f"[{SENSOR_ID}] [{fase}] {valor}%{status}")

        # ── Montagem e envio do payload UDP ───────────────────────────────────
        payload = json.dumps({
            "id":      SENSOR_ID,
            "tipo":    "umidade",
            "umidade": valor
        }).encode("utf-8")

        sock.sendto(payload, (SERVER_IP, UDP_PORT))

        # Aguarda o intervalo configurado antes da próxima leitura
        time.sleep(INTERVALO_ENVIO)

except KeyboardInterrupt:
    # Ctrl+C: encerra graciosamente, fechando o socket antes de sair
    print(f"\n[{SENSOR_ID}] Encerrando...")
    sock.close()