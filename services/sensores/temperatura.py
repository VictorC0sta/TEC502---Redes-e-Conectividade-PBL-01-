# =============================================================================
# SENSOR_TEMP.PY — Simulador de Sensor de Temperatura (UDP + TCP)
# =============================================================================

import json
import socket
import time
import random
import threading
import os

# Identificador único deste sensor, configurável via variável de ambiente
SENSOR_ID          = os.environ.get("SENSOR_ID", "sensor_temp_1")
# Endereço do servidor central que recebe as leituras UDP
SERVER_IP          = os.environ.get("SERVER_IP", "server")
# Porta UDP do servidor (destino dos pacotes de temperatura)
UDP_PORT           = int(os.environ.get("UDP_PORT", 5001))
# Porta TCP local onde este sensor escuta comandos do serviço de resfriamento
TCP_PORT           = int(os.environ.get("TCP_PORT", 7000))
# Duração em segundos que o modo resfriamento permanece ativo após acionamento
TEMPO_RESFRIAMENTO = int(os.environ.get("TEMPO_RESFRIAMENTO", 15))
# Bug 5 corrigido: era 0.1s (10 leituras/s, sobrecarregava o servidor), agora 0.3s
INTERVALO_ENVIO    = float(os.environ.get("INTERVALO_ENVIO", 0.3))

# Limites de alarme — usados apenas para colorir o log local, não para lógica de disparo
TEMP_LIMITE_MAX = 33.0
TEMP_LIMITE_MIN = 20.0

# Evento de sincronização entre threads: True = resfriamento ativo, False = operação normal
resfriando = threading.Event()


# Desativa o resfriamento após TEMPO_RESFRIAMENTO segundos (roda em thread separada)
def desativar_resfriamento():
    time.sleep(TEMPO_RESFRIAMENTO)
    # Limpa o evento, fazendo enviar_temperatura() voltar ao modo normal
    resfriando.clear()
    print(f"\n[{SENSOR_ID}] ✅ Resfriamento encerrado, voltando ao normal...")


# Aguarda comandos TCP enviados pelo serviço de resfriamento (resfriamento.py)
def escutar_comandos_tcp():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # SO_REUSEADDR: permite reutilizar a porta imediatamente após reiniciar o container
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", TCP_PORT))
    # Fila de até 5 conexões pendentes enquanto a anterior é processada
    srv.listen(5)
    print(f"[{SENSOR_ID}] Escutando comandos TCP na porta {TCP_PORT}...")

    while True:
        # Bloqueia até o serviço de resfriamento conectar
        conn, _ = srv.accept()
        with conn:
            data = conn.recv(1024)
            if data:
                try:
                    cmd = json.loads(data.decode("utf-8"))
                    # Único comando suportado: ativa o modo resfriamento
                    if cmd.get("acao") == "RESFRIAMENTO":
                        print(f"[{SENSOR_ID}] 🌀 Resfriamento ativado por {TEMPO_RESFRIAMENTO}s...")
                        # Sinaliza para enviar_temperatura() entrar no modo resfriamento
                        resfriando.set()
                        # Dispara o temporizador de desativação sem bloquear esta thread
                        threading.Thread(target=desativar_resfriamento, daemon=True).start()
                    conn.sendall(b'{"status": "ok"}')
                except json.JSONDecodeError:
                    conn.sendall(b'{"status": "erro"}')


# Gera leituras de temperatura e as envia ao servidor via UDP continuamente
def enviar_temperatura():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print(f"[{SENSOR_ID}] Enviando UDP para {SERVER_IP}:{UDP_PORT}")

    # Valor inicial dentro da faixa segura, longe dos limites de alarme
    valor = round(random.uniform(22.0, 26.0), 2)

    # Bug 4 corrigido: todos iniciavam em "subindo", criando picos sincronizados
    fase             = random.choice(["subindo", "descendo"])
    passos_restantes = random.randint(120, 250)

    try:
        while True:
            # ── Modo resfriamento: puxa o valor em direção a 26°C ──────────────
            if resfriando.is_set():
                alvo  = 26.0
                # Termo proporcional: quanto mais longe de 26°C, maior o empurrão
                delta = random.uniform(-0.15, 0.02) + (alvo - valor) * 0.02
                # Bug 3 corrigido: sem ruído a convergência era perfeita e irreal
                delta += random.uniform(-0.05, 0.05)
                # Hard limit físico: impede valores absurdos mesmo resfriando
                valor = round(max(20.0, min(38.0, valor + delta)), 2)
                print(f"[{SENSOR_ID}] 🌀 [RESFRIANDO] {valor}°C")

            # ── Modo normal: oscilação orgânica sobe/desce ────────────────────
            else:
                passos_restantes -= 1

                if fase == "subindo":
                    # Delta positivo com pequeno ruído para variação natural
                    delta = random.uniform(0.05, 0.20) + random.uniform(-0.05, 0.05)

                    # Desacelera apenas perto do hard limit (38°C), não antes —
                    # garante que o sensor consiga cruzar 35°C e acionar resfriamento
                    if valor > 37.0:
                        delta *= 0.4

                    # Troca de fase ao esgotar os passos planejados
                    if passos_restantes <= 0:
                        fase             = "descendo"
                        passos_restantes = random.randint(100, 200)
                        print(f"[{SENSOR_ID}] 🔁 Iniciando fase de descida em {valor}°C")

                else:
                    delta = random.uniform(-0.10, -0.02) + random.uniform(-0.04, 0.04)

                    # Troca de fase ao esgotar passos ou ao se aproximar do piso
                    if passos_restantes <= 0 or valor < 23.0:
                        fase             = "subindo"
                        passos_restantes = random.randint(120, 250)
                        print(f"[{SENSOR_ID}] 🔁 Iniciando fase de subida em {valor}°C")

                # Aplica o delta respeitando os extremos físicos absolutos
                valor = round(max(18.0, min(38.0, valor + delta)), 2)

                # Indicador visual de violação de limite apenas no log local
                status = ""
                if valor > TEMP_LIMITE_MAX:
                    status = " ⚠ ACIMA DO LIMITE"
                elif valor < TEMP_LIMITE_MIN:
                    status = " ⚠ ABAIXO DO LIMITE"

                print(f"[{SENSOR_ID}] [{fase}] {valor}°C{status}")

            # Monta o payload JSON no formato esperado pelo server.py
            payload = json.dumps({
                "id":    SENSOR_ID,
                "tipo":  "temperatura",
                "valor": valor
            }).encode("utf-8")

            # Envia a leitura — UDP não garante entrega, mas é suficiente para telemetria
            sock.sendto(payload, (SERVER_IP, UDP_PORT))
            time.sleep(INTERVALO_ENVIO)

    except KeyboardInterrupt:
        print(f"\n[{SENSOR_ID}] Encerrando...")
        sock.close()


# Inicia as duas threads: TCP (recebe comandos) e UDP (envia leituras)
t_tcp = threading.Thread(target=escutar_comandos_tcp, daemon=True)
t_udp = threading.Thread(target=enviar_temperatura,   daemon=True)
t_tcp.start()
t_udp.start()
# join() mantém o processo principal vivo enquanto as threads rodam
t_tcp.join()
t_udp.join()