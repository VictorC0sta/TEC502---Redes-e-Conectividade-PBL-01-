# =============================================================================
# SERVER.PY — Servidor Central de Monitoramento de Sensores IoT
# =============================================================================

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import os
import threading
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse
import queue

# Garante que o diretório de dados existe antes de qualquer leitura/escrita
os.makedirs("data", exist_ok=True)

# ── Arquivos de persistência ──────────────────────────────────────────────────
ATUADORES_FILE = "data/atuadores.json"   # Registro de todas as ações dos atuadores
HISTORICO_FILE = "data/historico.json"   # Histórico de leituras dos sensores

# Fuso horário UTC-3 (Brasília)
FUSO_BRASIL = timezone(timedelta(hours=-3))

# ── Endereços dos serviços externos (resolvidos via DNS no Docker) ────────────
ALARME_IP = os.environ.get("ALARME_IP", "localhost")
RESFRIAMENTO_IP = os.environ.get("RESFRIAMENTO_IP", "localhost")
ALARME_PORT       = 6000 
RESFRIAMENTO_PORT = 6001
# ── Limites aceitáveis para cada grandeza monitorada ─────────────────────────
# Valores fora dessa faixa acionam o alarme.
# Valores acima de max+2 acionam também o resfriamento.
LIMITES = {
    "temperatura": {"max": 33, "min": 20},  # graus Celsius
    "umidade":     {"max": 85, "min": 45}   # percentual
}

# ── Estado global em memória ──────────────────────────────────────────────────
# Guarda o último valor recebido de cada sensor, indexado por sensor_id.
estado = {}

# Rastreamento de borda para alarme: evita disparar repetidamente enquanto
# o sensor permanece fora dos limites (só aciona na transição False→True).
estado_limite: dict[str, bool] = {}

# Rastreamento de borda para resfriamento (mesmo princípio, threshold diferente).
estado_resfriamento: dict[str, bool] = {}

# Lock para proteger leituras/escritas no dicionário `estado` e nos arquivos JSON
lock = threading.Lock()

# ── Filas de escrita assíncrona (Bug 5 corrigido) ─────────────────────────────
# Em vez de escrever no disco a cada leitura,
# enfileiramos as entradas e deixamos threads dedicadas fazerem a escrita em lote
fila_disco     = queue.Queue()   # Entradas para historico.json
fila_atuadores = queue.Queue()   # Entradas para atuadores.json


# =============================================================================
# FUNÇÕES UTILITÁRIAS
# =============================================================================

def timestamp_br():
    # Retorna o instante atual formatado no fuso horário de Brasília
    return datetime.now(FUSO_BRASIL).strftime("%Y-%m-%d %H:%M:%S.%f")


def carregar_json(path):
    
    # Lê um arquivo JSON e retorna seu conteúdo como lista.
    try:
        with open(path, "r", encoding="utf-8") as f:
            dados = json.load(f)
            return dados if isinstance(dados, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


# =============================================================================
# ENFILEIRAMENTO PARA DISCO
# =============================================================================

def salvar_historico(sensor_id, tipo, valor):
    
    # Enfileira uma leitura de sensor para ser persistida em historico.json.
    # A escrita é feita pelo worker_historico.
    
    fila_disco.put({
        "id":      sensor_id,
        "tipo":    tipo,
        "valor":   valor,
        "horario": timestamp_br()
    })


def salvar_atuador(sensor, valor, acao, nome_sensor):
    
    # Enfileira um evento de atuação (alarme ou resfriamento) para ser
    # persistido em atuadores.json.

    fila_atuadores.put({
        "nome_sensor": nome_sensor,
        "sensor":      sensor,
        "valor":       valor,
        "acao":        acao,
        "timestamp":   timestamp_br()
    })


# =============================================================================
# WORKERS DE ESCRITA EM DISCO (threads dedicadas)
# =============================================================================

def worker_historico():
    
    # Consome a fila_disco em lotes de até 20 entradas e as grava em historico.json
    BATCH = 20
    while True:
        entradas = []
        try:
            entradas.append(fila_disco.get(timeout=5))
            while len(entradas) < BATCH:
                entradas.append(fila_disco.get_nowait())
        except queue.Empty:
            pass  

        if not entradas:
            continue  

        with lock:
            historico = carregar_json(HISTORICO_FILE)
            historico.extend(entradas)
            # Janela deslizante: descarta registros mais antigos se ultrapassar 10k
            if len(historico) > 10000:
                historico = historico[-10000:]
            with open(HISTORICO_FILE, "w", encoding="utf-8") as f:
                json.dump(historico, f, indent=2)


def worker_atuadores():
    
    #Consome a fila_atuadores em lotes de até 20 entradas e as grava em atuadores.json
    BATCH = 20
    while True:
        entradas = []
        try:
            entradas.append(fila_atuadores.get(timeout=5))
            while len(entradas) < BATCH:
                entradas.append(fila_atuadores.get_nowait())
        except queue.Empty:
            pass

        if not entradas:
            continue

        with lock:
            atuadores = carregar_json(ATUADORES_FILE)
            atuadores.extend(entradas)
            if len(atuadores) > 10000:
                atuadores = atuadores[-10000:]
            with open(ATUADORES_FILE, "w", encoding="utf-8") as f:
                json.dump(atuadores, f, indent=2)


# =============================================================================
# COMUNICAÇÃO COM SERVIÇOS EXTERNOS (TCP)
# =============================================================================

def enviar_alarme(sensor, valor, nome_sensor):
    
    # Envia um comando de ALARME ao serviço externo via TCP.
    # Após o envio (ou falha), registra a ação em atuadores.json
    
    try:
        comando = json.dumps({
            "sensor":      sensor,
            "nome_sensor": nome_sensor,
            "valor":       valor,
            "acao":        "ALARME"
        }).encode("utf-8")

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(5) 
            s.connect((ALARME_IP, ALARME_PORT))
            s.sendall(comando)
            resposta = s.recv(1024)
            print(f"[SERVER] Alarme respondeu: {resposta.decode()}")

    except (ConnectionRefusedError, OSError, TimeoutError) as e:
        print(f"[ERRO] Alarme inacessível: {e}")
    finally:
        salvar_atuador(sensor, valor, "ALARME", nome_sensor)


def enviar_resfriamento(sensor, valor, nome_sensor):
    
    # Envia um comando de RESFRIAMENTO ao serviço externo via TCP.
    # Após o envio (ou falha), registra a ação em atuadores.json.
    
    try:
        comando = json.dumps({
            "sensor":      sensor,
            "nome_sensor": nome_sensor,
            "valor":       valor,
            "acao":        "RESFRIAMENTO"
        }).encode("utf-8")

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(5) 
            s.connect((RESFRIAMENTO_IP, RESFRIAMENTO_PORT))
            s.sendall(comando)
            resposta = s.recv(1024)
            print(f"[SERVER] Resfriamento respondeu: {resposta.decode()}")

    except (ConnectionRefusedError, OSError, TimeoutError) as e:
        print(f"[ERRO] Resfriamento inacessível: {e}")
    finally:
        salvar_atuador(sensor, valor, "RESFRIAMENTO", nome_sensor)


# =============================================================================
# LÓGICA DE DETECÇÃO DE RISCO E ACIONAMENTO DE ATUADORES
# =============================================================================

def verificar_risco(sensor, valor, nome_sensor):
    
    # Avalia se o valor recebido de um sensor configura risco, usando
    # detecção de borda para evitar acionamentos repetidos.

    limites = LIMITES.get(sensor)
    if not limites:
        return  

    chave = f"{nome_sensor}_{sensor}"

    # ── Alarme: fora da faixa [min, max] ──────────────────────────────────────
    fora_agora  = valor > limites["max"] or valor < limites["min"]
    estava_fora = estado_limite.get(chave, False)

    if fora_agora and not estava_fora:
        # Borda de subida: acabou de sair da faixa segura → aciona alarme
        enviar_alarme(sensor, valor, nome_sensor)
    # Borda de descida (voltou ao normal): apenas atualiza o estado;
    # poderia logar aqui se necessário.
    estado_limite[chave] = fora_agora

    # Resfriamento: acima de max+2 
    precisa_resf    = valor > limites["max"] + 2
    estava_resfr    = estado_resfriamento.get(chave, False)

    if precisa_resf and not estava_resfr:
        # Borda de subida: temperatura excedeu o threshold de resfriamento
        enviar_resfriamento(sensor, valor, nome_sensor)
    estado_resfriamento[chave] = precisa_resf


# =============================================================================
# RECEPTOR UDP — escuta leituras dos sensores
# =============================================================================

def escutar_sensores():
    
    # Abre um socket UDP na porta 5001 e aguarda datagramas dos sensores.

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 5001))
    print("[SERVER] Escutando sensores UDP na porta 5001...")

    while True:
        data, _ = sock.recvfrom(1024)  # Bloqueia até receber um datagrama

        try:
            dados     = json.loads(data.decode("utf-8"))
            sensor_id = dados.get("id", "desconhecido")
            tipo      = dados.get("tipo")

            if tipo == "temperatura":
                valor = dados["valor"]
                print(f"[SERVER] {sensor_id}: {valor}C")
                with lock:
                    estado[sensor_id] = {"tipo": "temperatura", "valor": valor}
                salvar_historico(sensor_id, "temperatura", valor)
                verificar_risco("temperatura", valor, sensor_id)

            elif tipo == "umidade":
                # Nota: sensores de umidade usam a chave "umidade" (não "valor")
                valor = dados["umidade"]
                print(f"[SERVER] {sensor_id}: {valor}%")
                with lock:
                    estado[sensor_id] = {"tipo": "umidade", "valor": valor}
                salvar_historico(sensor_id, "umidade", valor)
                verificar_risco("umidade", valor, sensor_id)

        except (json.JSONDecodeError, KeyError) as e:
            print(f"[SERVER] Erro UDP: {e}")


# =============================================================================
# PROCESSADOR COMPARTILHADO
# =============================================================================

def processar_sensor(dados, responder_fn):

    # Processa uma leitura de sensor recebida via HTTP POST /sensor.
    # Essa função é chamada pelo Handler HTTP e compartilha a mesma lógica de processamento dos dados recebidos via UDP.

    
    sensor_id = dados.get("id", "desconhecido")
    tipo      = dados.get("tipo")

    if tipo == "temperatura":
        valor = dados["valor"]
        with lock:
            estado[sensor_id] = {"tipo": "temperatura", "valor": valor}
        salvar_historico(sensor_id, "temperatura", valor)
        verificar_risco("temperatura", valor, sensor_id)
        responder_fn({"status": "ok"})

    elif tipo == "umidade":
        # Aceita tanto "umidade" quanto "valor" como chave do campo
        valor = dados.get("umidade", dados.get("valor"))
        with lock:
            estado[sensor_id] = {"tipo": "umidade", "valor": valor}
        salvar_historico(sensor_id, "umidade", valor)
        verificar_risco("umidade", valor, sensor_id)
        responder_fn({"status": "ok"})

    else:
        responder_fn({"erro": "invalido"}, 400)


# =============================================================================
# SERVIDOR HTTP — API REST
# =============================================================================

class Handler(BaseHTTPRequestHandler):
    
    # Handler HTTP com suporte a múltiplas threads simultâneas.
    def log_message(self, format, *args):
        pass

    def responder(self, dados, status=200):
        # Serializa `dados` para JSON e envia a resposta HTTP.
        body = (json.dumps(dados) + "\n").encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # ── Rotas GET ─────────────────────────────────────────────────────────────

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/historico":
            # Retorna o arquivo completo de histórico 
            self.responder(carregar_json(HISTORICO_FILE))

        elif parsed.path == "/estado":
            # Retorna o último valor conhecido de cada sensor (estado em memória)
            with lock:
                self.responder(estado)

        elif parsed.path == "/atuadores":
            # Retorna o log de ações dos atuadores
            self.responder(carregar_json(ATUADORES_FILE))

        else:
            self.responder({"erro": "rota"}, 404)

    # ── Rotas POST ────────────────────────────────────────────────────────────

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length)

        try:
            dados = json.loads(body.decode())

            if self.path == "/sensor":
                processar_sensor(dados, self.responder)

            elif self.path == "/ativar/alarme":
                # Acionamento manual do alarme (ex: botão no painel de controle).
                # Dispara em thread separada para não bloquear a resposta HTTP.
                threading.Thread(
                    target=enviar_alarme,
                    args=("manual", 0, "A.M"),  # "A.M" = Acionamento Manual
                    daemon=True
                ).start()
                salvar_historico("A.M", "alarme_manual", 0)
                self.responder({"acao": "ALARME", "status": "ok"})

            elif self.path == "/ativar/resfriamento":
                # Acionamento manual do resfriamento.
                # O serviço de resfriamento mantém o estado ativo por
                # alguns segundos.
                threading.Thread(
                    target=enviar_resfriamento,
                    args=("manual", 0, "A.M"),
                    daemon=True
                ).start()
                salvar_historico("A.M", "resfriamento_manual", 0)
                self.responder({"acao": "RESFRIAMENTO", "status": "ok"})

            else:
                self.responder({"erro": "rota"}, 404)

        except Exception:
            # Captura qualquer falha de parsing JSON ou campo ausente
            self.responder({"erro": "json"}, 400)


# =============================================================================
# PONTO DE ENTRADA
# =============================================================================

if __name__ == "__main__":
    # Zera os arquivos de persistência a cada inicialização do container,
    # evitando que dados de sessões anteriores poluam os dashboards.
    for path in (HISTORICO_FILE, ATUADORES_FILE):
        with open(path, "w", encoding="utf-8") as f:
            json.dump([], f)

    # ── Threads daemon — encerram automaticamente quando o processo principal sai
    threading.Thread(target=escutar_sensores, daemon=True).start()  # UDP 5001
    threading.Thread(target=worker_historico, daemon=True).start()  # Escrita histórico
    threading.Thread(target=worker_atuadores, daemon=True).start()  # Escrita atuadores

    # ── Servidor HTTP multi-thread na porta 5000
    httpd = ThreadingHTTPServer(("0.0.0.0", 5000), Handler)
    print("[SERVER] Rodando em http://localhost:5000")
    httpd.serve_forever()
