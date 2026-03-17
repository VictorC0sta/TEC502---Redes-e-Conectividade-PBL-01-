import json
import socket
import time
import random

UDP_IP = "127.0.0.1"
UDP_PORT = 5001

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

print(f"[SENSOR] Enviando dados para {UDP_IP}:{UDP_PORT}")

while True:
    dados = {
        "valor": round(random.uniform(20.0, 35.0), 2)
    }

    payload = json.dumps(dados).encode("utf-8")
    sock.sendto(payload, (UDP_IP, UDP_PORT))
    
    print(f"[SENSOR] Enviado: {dados}")
    time.sleep(2)