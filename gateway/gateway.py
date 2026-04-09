# =============================================================================
# GATEWAY.PY — Gateway UDP → HTTP
# =============================================================================

import json
import socket
import urllib.request
import urllib.error
import threading
import queue
import time
import os

# ── Configuração de rede ──────────────────────────────────────────────────────
# Endereço base do servidor central — "server" é o hostname Docker do server.py
HTTP_URL = os.environ.get("HTTP_URL", "http://server:5000")
# Porta UDP onde este gateway escuta os pacotes dos sensores
UDP_PORT = int(os.environ.get("UDP_PORT", 5001))

# URL completa do endpoint que recebe leituras de sensores no server.py
SENSOR_ENDPOINT = f"{HTTP_URL}/sensor"

# ── Configuração do pool de workers ──────────────────────────────────────────
WORKERS   = 4    # Threads fixas para envio HTTP — ajuste conforme o número de sensores
QUEUE_MAX = 200  # Limite da fila; pacotes além disso são descartados (servidor inativo)
MAX_RETRIES = 2  # Tentativas por pacote antes de descartar permanentemente
TIMEOUT_S   = 5  # Timeout HTTP por tentativa em segundos (era 3s, aumentado)

# Fila compartilhada entre o listener UDP (produtor) e os workers HTTP (consumidores)
# maxsize evita crescimento ilimitado se o servidor ficar lento ou cair
_fila: queue.Queue = queue.Queue(maxsize=QUEUE_MAX)


# =============================================================================
# POOL DE WORKERS HTTP
# =============================================================================

# Worker que roda em loop infinito consumindo pacotes da fila e enviando via HTTP
def _worker():
    while True:
        # Bloqueia até haver um item na fila; retorna (dados, número_da_tentativa)
        dados, tentativa = _fila.get()
        try:
            _enviar_http(dados)
        except Exception as e:
            # Falha no POST — verifica se ainda há tentativas disponíveis
            if tentativa < MAX_RETRIES:
                # Backoff exponencial: 0.2s na 1ª falha, 0.4s na 2ª
                espera = 0.2 * (2 ** tentativa)
                time.sleep(espera)
                try:
                    # Reinsere na fila como nova tarefa com tentativa incrementada
                    _fila.put_nowait((dados, tentativa + 1))
                except queue.Full:
                    # Fila lotou enquanto aguardávamos o backoff — descarta
                    sid = dados.get("id", "?")
                    print(f"[GATEWAY] Fila cheia, descartando retry de {sid}")
            else:
                # Esgotou todas as tentativas — descarta definitivamente
                sid = dados.get("id", "?")
                print(f"[GATEWAY] Descartado após {MAX_RETRIES} tentativas: {sid} — {e}")
        finally:
            # Marca o item original como processado (independente de retry ou falha)
            _fila.task_done()


# Monta e dispara o HTTP POST para o server.py com os dados do sensor
def _enviar_http(dados):
    payload = json.dumps(dados).encode("utf-8")
    req = urllib.request.Request(
        SENSOR_ENDPOINT,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    # urlopen lança exceção em erros HTTP (4xx, 5xx) e de rede — capturada no _worker
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        resposta = resp.read().decode("utf-8")
        sid = dados.get("id", "?")
        print(f"[GATEWAY] OK {sid}: {resposta.strip()}")


# =============================================================================
# Thread principal
# =============================================================================

# Escuta datagramas UDP dos sensores e os enfileira para os workers HTTP
def escutar():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", UDP_PORT))
    print(f"[GATEWAY] Escutando UDP:{UDP_PORT} → {SENSOR_ENDPOINT}")
    print(f"[GATEWAY] Pool: {WORKERS} workers, fila máx {QUEUE_MAX}, timeout {TIMEOUT_S}s")

    while True:
        # Bloqueia até receber um datagrama de qualquer sensor
        data, addr = sock.recvfrom(1024)
        try:
            dados     = json.loads(data.decode("utf-8"))
            sensor_id = dados.get("id", "desconhecido")
            tipo      = dados.get("tipo", "?")
            print(f"[GATEWAY] {sensor_id} ({tipo}): {dados}")
            # put_nowait: não bloqueia — se a fila estiver cheia lança queue.Full
            _fila.put_nowait((dados, 0))  # tentativa=0 indica primeiro envio
        except queue.Full:
            # Servidor lento ou morto — descarta para não travar o listener
            print(f"[GATEWAY] Fila cheia — pacote de {addr} descartado")
        except json.JSONDecodeError:
            # Datagrama corrompido ou formato inesperado — ignora
            print(f"[ERRO] JSON inválido de {addr}")


# =============================================================================
# PONTO DE ENTRADA
# =============================================================================

if __name__ == "__main__":
    # Sobe o pool de workers antes de começar a receber pacotes
    for _ in range(WORKERS):
        # daemon=True: as threads morrem automaticamente quando o processo principal sair
        threading.Thread(target=_worker, daemon=True).start()

    # Thread principal — mantém o processo vivo
    try:
        escutar()
    except KeyboardInterrupt:
        # Ctrl+C: encerra sem forçar — workers daemon são finalizados pelo SO
        print("\n[GATEWAY] Encerrando...")