import json
import socket
import urllib.request
import urllib.error

UDP_IP = "0.0.0.0"
UDP_PORT = 5001
HTTP_URL = "http://127.0.0.1:5000"

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind((UDP_IP,UDP_PORT))

print(f"[GATEWAY] UDP:{UDP_PORT} → HTTP:{HTTP_URL}")

while True:
    data, addr = sock.recvfrom(1024)
    try:
        dados = json.loads(data.decode("utf-8"))
        print(f"[GATEWAY] Recebido UDP de {addr}: {dados}")

        # Repassa via POST ao servidor HTTP existente
        payload = json.dumps(dados).encode("utf-8")
        req = urllib.request.Request(
            HTTP_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req) as resp:
            resposta = resp.read().decode("utf-8")
            print(f"[GATEWAY] Resposta HTTP: {resposta}")

    except json.JSONDecodeError:
        print(f"[ERRO] JSON inválido de {addr}")
    except urllib.error.URLError as e:
        print(f"[ERRO] Falha ao contatar servidor HTTP: {e}")