import json
import socket
import urllib.request
import urllib.error
import threading
import os

HTTP_URL  = os.environ.get("HTTP_URL", "http://server:5000")
UDP_PORT  = int(os.environ.get("UDP_PORT", 5001))

# Rota correta para envio de dados de sensores
SENSOR_ENDPOINT = f"{HTTP_URL}/sensor"


def enviar_http(dados):
    try:
        payload = json.dumps(dados).encode("utf-8")
        req = urllib.request.Request(
            SENSOR_ENDPOINT,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            resposta = resp.read().decode("utf-8")
            print(f"[GATEWAY] Resposta HTTP: {resposta}")
    except urllib.error.URLError as e:
        print(f"[ERRO] Falha ao contatar servidor HTTP: {e}")


def escutar():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", UDP_PORT))
    print(f"[GATEWAY] Escutando todos os sensores na porta UDP:{UDP_PORT}")
    print(f"[GATEWAY] Encaminhando dados para {SENSOR_ENDPOINT}")

    while True:
        data, addr = sock.recvfrom(1024)
        try:
            dados     = json.loads(data.decode("utf-8"))
            sensor_id = dados.get("id", "desconhecido")
            tipo      = dados.get("tipo", "desconhecido")
            print(f"[GATEWAY] Recebido de {sensor_id} ({tipo}) em {addr}: {dados}")
            threading.Thread(target=enviar_http, args=(dados,), daemon=True).start()
        except json.JSONDecodeError:
            print(f"[ERRO] JSON inválido de {addr}")


try:
    t = threading.Thread(target=escutar, daemon=True)
    t.start()
    t.join()
except KeyboardInterrupt:
    print("\n[GATEWAY] Encerrando...")