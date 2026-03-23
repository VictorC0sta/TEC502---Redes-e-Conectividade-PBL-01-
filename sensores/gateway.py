import json
import socket
import urllib.request
import urllib.error
import threading

HTTP_URL = "http://127.0.0.1:5000"

def enviar_http(dados):
    try:
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
    except urllib.error.URLError as e:
        print(f"[ERRO] Falha ao contatar servidor HTTP: {e}")

def escutar(porta, label):
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", porta))
    print(f"[GATEWAY] Escutando {label} na porta UDP:{porta}")
    while True:
        data, addr = sock.recvfrom(1024)
        try:
            dados = json.loads(data.decode("utf-8"))
            print(f"[GATEWAY] Recebido {label} de {addr}: {dados}")
            enviar_http(dados)
        except json.JSONDecodeError:
            print(f"[ERRO] JSON inválido de {addr}")

try:
    t1 = threading.Thread(target=escutar, args=(5001, "TEMPERATURA"), daemon=True)
    t2 = threading.Thread(target=escutar, args=(5002, "UMIDADE"), daemon=True)

    t1.start()
    t2.start()

    t1.join()
    t2.join()

except KeyboardInterrupt:
    print("\n[GATEWAY] Encerrando...")