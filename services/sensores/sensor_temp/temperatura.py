import json
import socket
import time
import random
import threading

UDP_IP = "127.0.0.1"
UDP_PORT = 5001
TCP_PORT = 7000

TEMPO_RESFRIAMENTO = 10
resfriando = threading.Event()  

def desativar_resfriamento():
    time.sleep(TEMPO_RESFRIAMENTO)
    resfriando.clear()  
    print("\n[SENSOR TEMP] ✅ Resfriamento encerrado, voltando ao normal...")

def escutar_comandos_tcp():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", TCP_PORT))
    srv.listen(5)
    print(f"[SENSOR TEMP] Escutando comandos TCP na porta {TCP_PORT}...")

    while True:
        conn, _ = srv.accept()
        with conn:
            data = conn.recv(1024)
            if data:
                try:
                    cmd = json.loads(data.decode("utf-8"))
                    if cmd.get("acao") == "RESFRIAMENTO":
                        print(f"\n[SENSOR TEMP] 🌀 Resfriamento ativado por {TEMPO_RESFRIAMENTO}s...")
                        resfriando.set()  # ← equivale a RESFRIANDO = True
                        threading.Thread(target=desativar_resfriamento, daemon=True).start()
                    conn.sendall(b'{"status": "ok"}')
                except json.JSONDecodeError:
                    conn.sendall(b'{"status": "erro"}')

def enviar_temperatura():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print(f"[SENSOR TEMP] Enviando UDP para {UDP_IP}:{UDP_PORT}")

    try:
        while True:
            if resfriando.is_set():  # ← equivale a if RESFRIANDO:
                valor = round(random.uniform(18.0, 25.0), 2)
                print(f"[SENSOR TEMP] 🌀 Resfriando... valor={valor}")
            else:
                valor = round(random.uniform(20.0, 38.0), 2)
                print(f"[SENSOR TEMP] Enviado: {{'valor': {valor}}}")

            sock.sendto(json.dumps({"valor": valor}).encode("utf-8"), (UDP_IP, UDP_PORT))
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n[SENSOR TEMP] Encerrando...")
        sock.close()

try:
    t_tcp = threading.Thread(target=escutar_comandos_tcp, daemon=True)
    t_udp = threading.Thread(target=enviar_temperatura, daemon=True)

    t_tcp.start()
    t_udp.start()

    t_tcp.join()
    t_udp.join()

except KeyboardInterrupt:
    print("\n[SENSOR TEMP] Encerrando...")