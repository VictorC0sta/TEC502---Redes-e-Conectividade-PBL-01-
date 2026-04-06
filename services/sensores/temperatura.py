import json
import socket
import time
import random
import threading
import os

SENSOR_ID          = os.environ.get("SENSOR_ID", "sensor_temp_1")
SERVER_IP          = os.environ.get("SERVER_IP", "server")
UDP_PORT           = int(os.environ.get("UDP_PORT", 5001))
TCP_PORT           = int(os.environ.get("TCP_PORT", 7000))
TEMPO_RESFRIAMENTO = int(os.environ.get("TEMPO_RESFRIAMENTO", 15))
INTERVALO_ENVIO    = float(os.environ.get("INTERVALO_ENVIO", 0.3))  # Bug 5: era 0.1s (10pts/s), agora 0.3s

# Limites do servidor — usados só para log local
TEMP_LIMITE_MAX = 33.0
TEMP_LIMITE_MIN = 20.0

resfriando = threading.Event()


def desativar_resfriamento():
    time.sleep(TEMPO_RESFRIAMENTO)
    resfriando.clear()
    print(f"\n[{SENSOR_ID}] ✅ Resfriamento encerrado, voltando ao normal...")


def escutar_comandos_tcp():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", TCP_PORT))
    srv.listen(5)
    print(f"[{SENSOR_ID}] Escutando comandos TCP na porta {TCP_PORT}...")

    while True:
        conn, _ = srv.accept()
        with conn:
            data = conn.recv(1024)
            if data:
                try:
                    cmd = json.loads(data.decode("utf-8"))
                    if cmd.get("acao") == "RESFRIAMENTO":
                        print(f"[{SENSOR_ID}] 🌀 Resfriamento ativado por {TEMPO_RESFRIAMENTO}s...")
                        resfriando.set()
                        threading.Thread(target=desativar_resfriamento, daemon=True).start()
                    conn.sendall(b'{"status": "ok"}')
                except json.JSONDecodeError:
                    conn.sendall(b'{"status": "erro"}')


def enviar_temperatura():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print(f"[{SENSOR_ID}] Enviando UDP para {SERVER_IP}:{UDP_PORT}")

    valor = round(random.uniform(22.0, 26.0), 2)

    # Bug 4: todos iniciavam em "subindo" → sensores sincronizados demais
    # Correção: fase inicial aleatória
    fase             = random.choice(["subindo", "descendo"])
    passos_restantes = random.randint(120, 250)

    try:
        while True:
            if resfriando.is_set():
                alvo  = 26.0
                delta = random.uniform(-0.15, 0.02) + (alvo - valor) * 0.02
                # Bug 3: resfriamento convergia perfeitamente para 26°C (muito scriptado)
                # Correção: adicionar ruído real para parecer mais natural
                delta += random.uniform(-0.05, 0.05)
                valor = round(max(20.0, min(38.0, valor + delta)), 2)
                print(f"[{SENSOR_ID}] 🌀 [RESFRIANDO] {valor}°C")

            else:
                passos_restantes -= 1

                if fase == "subindo":
                    delta = random.uniform(0.05, 0.20) + random.uniform(-0.05, 0.05)

                    # Desacelera só perto do hard limit (38°C), não antes —
                    # assim o sensor consegue cruzar 35°C e acionar o resfriamento
                    if valor > 37.0:
                        delta *= 0.4

                    if passos_restantes <= 0:
                        fase             = "descendo"
                        passos_restantes = random.randint(100, 200)
                        print(f"[{SENSOR_ID}] 🔁 Iniciando fase de descida em {valor}°C")

                else:  # descendo
                    # Bug 2: delta de descida era -0.30 a -0.05 → queda quase vertical
                    # Correção: suavizado para -0.10 a -0.02
                    delta = random.uniform(-0.10, -0.02) + random.uniform(-0.04, 0.04)

                    if passos_restantes <= 0 or valor < 23.0:
                        fase             = "subindo"
                        passos_restantes = random.randint(120, 250)
                        print(f"[{SENSOR_ID}] 🔁 Iniciando fase de subida em {valor}°C")

                valor = round(max(18.0, min(38.0, valor + delta)), 2)

                status = ""
                if valor > TEMP_LIMITE_MAX:
                    status = " ⚠ ACIMA DO LIMITE"
                elif valor < TEMP_LIMITE_MIN:
                    status = " ⚠ ABAIXO DO LIMITE"

                print(f"[{SENSOR_ID}] [{fase}] {valor}°C{status}")

            payload = json.dumps({
                "id":    SENSOR_ID,
                "tipo":  "temperatura",
                "valor": valor
            }).encode("utf-8")

            sock.sendto(payload, (SERVER_IP, UDP_PORT))
            time.sleep(INTERVALO_ENVIO)

    except KeyboardInterrupt:
        print(f"\n[{SENSOR_ID}] Encerrando...")
        sock.close()


t_tcp = threading.Thread(target=escutar_comandos_tcp, daemon=True)
t_udp = threading.Thread(target=enviar_temperatura,   daemon=True)
t_tcp.start()
t_udp.start()
t_tcp.join()
t_udp.join()