import json
import socket
import time
import random
import threading

UDP_IP = "127.0.0.1"
TCP_PORT = 7000

resfriando = False
tempo_resfriamento = 30 

def escutar_comandos_tcp():
    global resfriando
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("0.0.0.0", TCP_PORT))
    srv.listen(5)
    print(f"[SENSOR] Escutando comando TCP na porta {TCP_PORT}...")

    while True:
        conn, addr = srv.accept()
        with conn:
            data = conn.recv(1024)
            if data: 
                try: 
                    cmd = json.loads(data.decode("uft-8"))
                    if cmd.get("acao") == "RESFRIAMENTO"
                        print(f"\n[SENSOR] 🌀 Resfriamento ativado! Temperatura vai cair por {tempo_resfriamento}s...")
                        resfriando = True
                        threading.Thread(target=desativar_resfriamento, daemon = True)
                    conn.sendall(b'{"status": "ok"}')
                except json.JSONDecodeError: 
                    conn.sendall(b'{"status": "erro"}')


def desativar_resfriamento():
    global resfriando
    time.sleep(tempo_resfriamento)
    resfriando = False
    print(f"\n[SENSOR] ✅ Resfriamento encerrado, voltando ao normal...")  

def enviar_temperatura():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print(f"[SENSOR] Enviando dados para {UDP_IP}: 5001")
    try:
        while True:

            if resfriando: 
                valor = round(random.uniforme(18.0, 25.0), 2)
                print(f"[SENSOR TEMPERATURA] 🌀 Resfriando... Enviado: {{'valor': {valor}}}")
            else:
                valor = round(random.uniform(18.0, 38.0), 2)
                print(f"[SENSOR TEMPERATURA] Enviado: {{'valor': {valor}}}")

            dados = {
                "valor": valor
            }
            payload = json.dumps(dados).encode("utf-8")
            sock.sendto(payload, (UDP_IP, 5001))
            print(f"[SENSOR] Enviado: {dados}")
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n[SENSOR] de Temperatura Encerrando...")
        sock.close()

def enviar_umidade():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print(f"[SENSOR DE UMIDADE] Enviando dados para {UDP_IP}: 5002")
    try:
        while True:
            dados = {"valor": round(random.uniform(40.0, 100), 2)}
            payload = json.dumps(dados).encode("utf-8")
            sock.sendto(payload, (UDP_IP, 5002))
            print(f"[SENSOR UMIDADE] enviado: {dados}")
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[SENSOR UMIDADE] de Umidade Encerrando...")
        sock.close()

try:
    t_tcp = threading.Thread(target=escutar_comandos_tcp, daemon=True)
    t1 = threading.Thread(target=enviar_temperatura, daemon = True)
    t2 = threading.Thread(target= enviar_umidade, daemon = True)

    t_tcp.start()
    t1.start()
    t2.start()

    t_tcp.join()
    t1.join()
    t2.join()

except KeyboardInterrupt:
    print("\n [SENSOR] Encerrando...")