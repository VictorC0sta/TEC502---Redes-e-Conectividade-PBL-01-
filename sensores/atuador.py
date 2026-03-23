import socket
import json 
from datetime import datetime 

TCP_IP = "0.0.0.0"
TCP_PORT = 6000
ATUADORES_FILE = "atuadores.json"

LIMITES = {
    "temperatura": {"max": 33, "min": 20},
    "umidade":     {"max": 80, "min": 45}
}

def carregar_atuadores():
    try: 
        with open(ATUADORES_FILE, "r") as f: 
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def salvar_atuacao(evento):
    historico = carregar_atuadores
    historico.append(evento)
    with open(ATUADORES_FILE, "w") as f:
        json.dump(historico, f, indent=2)

def executar_acao(comando): 
    valor = comando.get("valor")
    sensor = comando.get("sensor")
    nome_sensor = comando.get("nome_sensor")
    acao = comando.get("acao")

    print(f"\n{'='*40}")
    if acao == "ALARME":
        print(f"🚨 [ALARME] {sensor.upper()} em {valor} — fora do limite!")
        print(f"   → Capturado por: {nome_sensor}")
        print("\a")

    elif acao == "RESFRIAMENTO":
        print(f"🌀 [RESFRIAMENTO] Temperatura crítica: {valor}°C")
        print(f"   → Capturado por: {nome_sensor}")
        print("   → Ventiladores industriais ativados")
        print("   → Válvula de água gelada aberta")
        print("   → Redução de carga na máquina iniciada")
        print("\a\a")

    print(f"{'='*40}\n")
    evento = {
        "nome_sensor": nome_sensor,
        "sensor": sensor,
        "valor": valor,
        "acao": acao,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    salvar_atuacao(evento)

sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind((TCP_IP, TCP_PORT))
sock.listen(5)

print(f"[ATUADOR] Escutando TCP na porta {TCP_PORT}...")
print(f"[ATUADOR] Limites: {LIMITES}")

try:
    while True:
        conn, addr = sock.accept()
        with conn:
            data = conn.recv(1024)
            if data:
                try:
                    comando = json.loads(data.decode("utf-8"))
                    executar_acao(comando)
                    conn.sendall(b'{"status": "ok"}')
                except json.JSONDecodeError:
                    conn.sendall(b'{"status": "erro"}')

except KeyboardInterrupt:
    print("\n[ATUADOR] Encerrando...")
    sock.close()