# =============================================================================
# RESFRIAMENTO.PY — Serviço de Resfriamento (TCP, porta 6001)
# =============================================================================

import socket
import json
import os
from datetime import datetime, timezone, timedelta

# ── Configuração do servidor TCP ──────────────────────────────────────────────
TCP_IP   = "0.0.0.0"  # Aceita conexões de qualquer interface de rede
TCP_PORT = 6001       # Porta onde este serviço aguarda comandos do server.py

# Persistência 
ATUADORES_FILE = "data/atuadores.json"

# Fuso horário UTC-3 (Brasília) — usado em todos os timestamps
FUSO_BRASIL = timezone(timedelta(hours=-3))

# Garante que o diretório de dados existe antes de qualquer escrita
os.makedirs("data", exist_ok=True)

# ── Lista de sensores de temperatura a notificar ──────────────────────────────
# Lida de variável de ambiente — facilita adicionar/remover sensores no Docker
SENSORES_TEMP = os.environ.get("SENSORES_TEMP", "sensor_temp_1,sensor_temp_2,sensor_temp_3")

# Converte a string separada por vírgulas em lista, removendo espaços extras
SENSORES_LIST = [s.strip() for s in SENSORES_TEMP.split(",")]

# Porta TCP onde cada sensor_temp.py escuta comandos de resfriamento
TCP_SENSOR_PORT = int(os.environ.get("TCP_SENSOR_PORT", 7000))


# =============================================================================
# FUNÇÕES UTILITÁRIAS
# =============================================================================

# Retorna o instante atual formatado no fuso horário de Brasília
def timestamp_br():
    return datetime.now(FUSO_BRASIL).strftime("%Y-%m-%d %H:%M:%S.%f")


# Lê atuadores.json e retorna a lista de eventos; retorna [] se não existir
def carregar_atuadores():
    try:
        with open(ATUADORES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


# Acrescenta um evento de resfriamento ao arquivo atuadores.json
def salvar_atuacao(evento):
    historico = carregar_atuadores()
    historico.append(evento)
    with open(ATUADORES_FILE, "w", encoding="utf-8") as f:
        json.dump(historico, f, indent=2)


# =============================================================================
# NOTIFICAÇÃO DOS SENSORES
# =============================================================================

# Conecta em cada sensor_temp via TCP e envia o comando de resfriamento
def notificar_sensores():
    for sensor_id in SENSORES_LIST:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                # Timeout de 3s: se o sensor não responder, segue para o próximo
                s.settimeout(3)
                # sensor_id é o hostname Docker — resolve para o IP do container
                s.connect((sensor_id, TCP_SENSOR_PORT))
                s.sendall(json.dumps({"acao": "RESFRIAMENTO"}).encode("utf-8"))
                # Aguarda confirmação antes de fechar a conexão
                s.recv(1024)
                print(f"[RESFRIAMENTO] ✅ {sensor_id} notificado!")
        except (socket.error, OSError) as e:
            # Sensor offline ou inacessível — loga e continua para os demais
            print(f"[RESFRIAMENTO] ⚠️  Não foi possível notificar {sensor_id}: {e}")


# =============================================================================
# EXECUÇÃO DO RESFRIAMENTO
# =============================================================================

# Processa o comando recebido: exibe alerta no terminal e notifica os sensores
def executar_resfriamento(cmd):
    valor       = cmd.get("valor")        # Temperatura que disparou o resfriamento
    nome_sensor = cmd.get("nome_sensor")  # Sensor que detectou a temperatura crítica
    sensor      = cmd.get("sensor")       # Grandeza medida (sempre "temperatura" aqui)

    # Alerta visual no terminal simulando ações físicas de um sistema real
    print(f"\n{'='*40}")
    print(f"🌀 [RESFRIAMENTO] Temperatura crítica: {valor}°C")
    print(f"   Sensor: {nome_sensor} | Grandeza: {sensor}")
    # Dois alertas sonoros BEL — pode não funcionar em Docker sem TTY alocado
    print("\a\a")

    # Propaga o comando para todos os sensores de temperatura registrados
    notificar_sensores()


# =============================================================================
# SERVIDOR TCP — loop principal
# =============================================================================

# Cria e configura o socket TCP
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
# SO_REUSEADDR: evita erro "address already in use" ao reiniciar o container
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
sock.bind((TCP_IP, TCP_PORT))
# Fila de até 5 conexões pendentes enquanto a anterior é processada
sock.listen(5)

print(f"[RESFRIAMENTO] Escutando TCP na porta {TCP_PORT}...")
print(f"[RESFRIAMENTO] Sensores a notificar: {SENSORES_LIST}")

try:
    while True:
        # Bloqueia até o server.py conectar para enviar um comando
        conn, addr = sock.accept()
        with conn:
            data = conn.recv(1024)
            if data:
                try:
                    comando = json.loads(data.decode("utf-8"))
                    # Processa o resfriamento e notifica os sensores
                    executar_resfriamento(cmd=comando)
                    # Responde ao server.py confirmando o processamento
                    conn.sendall(b'{"status": "ok"}')
                except (json.JSONDecodeError, UnicodeDecodeError):
                    # Dados corrompidos ou encoding inesperado
                    conn.sendall(b'{"status": "erro"}')

except KeyboardInterrupt:
    # Ctrl+C: encerra, fechando o socket antes de sair
    print("\n[RESFRIAMENTO] Encerrando...")
    sock.close()