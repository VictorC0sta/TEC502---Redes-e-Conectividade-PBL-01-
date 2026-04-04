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

    # Valor inicial realista
    valor = random.uniform(22.0, 28.0)

    try:
        while True:
            if resfriando.is_set():
                alvo = 21.0   # puxa em direção ao alvo de resfriamento
                limite_min, limite_max = 18.0, 25.0
            else:
                alvo = 27.0   # temperatura ambiente "normal"
                limite_min, limite_max = 20.0, 38.0

            # Pequeno passo aleatório + leve atração ao alvo (mean reversion)
            delta = random.uniform(-0.3, 0.3) + (alvo - valor) * 0.05
            valor = round(max(limite_min, min(limite_max, valor + delta)), 2)

            payload = json.dumps({
                "id":    SENSOR_ID,
                "tipo":  "temperatura",
                "valor": valor
            }).encode("utf-8")
            sock.sendto(payload, (SERVER_IP, UDP_PORT))
            print(f"[{SENSOR_ID}] Enviado: {valor}°C")
            time.sleep(0.1)

    except KeyboardInterrupt:
        print(f"\n[{SENSOR_ID}] Encerrando...")
        sock.close()

t_tcp = threading.Thread(target=escutar_comandos_tcp, daemon=True)
t_udp = threading.Thread(target=enviar_temperatura,   daemon=True)
t_tcp.start()
t_udp.start()
t_tcp.join()
t_udp.join()