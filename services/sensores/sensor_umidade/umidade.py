import json
import socket
import time
import random

UDP_IP = "127.0.0.1"
UDP_PORT = 5002

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
print(f"[SENSOR UMIDADE] Enviando UDP para {UDP_IP}:{UDP_PORT}")

try:
    while True:
        dados = {"umidade": round(random.uniform(40.0, 90.0), 2)}
        sock.sendto(json.dumps(dados).encode("utf-8"), (UDP_IP, UDP_PORT))
        print(f"[SENSOR UMIDADE] Enviado: {dados}")
        time.sleep(1)

except KeyboardInterrupt:
    print("\n[SENSOR UMIDADE] Encerrando...")
    sock.close()