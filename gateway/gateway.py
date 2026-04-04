import json
import socket
import urllib.request
import urllib.error
import threading
import queue
import time
import os

HTTP_URL  = os.environ.get("HTTP_URL", "http://server:5000")
UDP_PORT  = int(os.environ.get("UDP_PORT", 5001))

SENSOR_ENDPOINT = f"{HTTP_URL}/sensor"

# ── Configuração do pool ───────────────────────────────────────────────────────
WORKERS      = 4     # threads fixas — ajuste conforme o número de sensores
QUEUE_MAX    = 200   # descarta se a fila encher (servidor está morto)
MAX_RETRIES  = 2     # tentativas por pacote antes de descartar
TIMEOUT_S    = 5     # timeout HTTP por tentativa (era 3 — aumentado)

# Fila compartilhada entre o listener UDP e o pool de workers
_fila: queue.Queue = queue.Queue(maxsize=QUEUE_MAX)


# ── Worker HTTP — roda em thread fixa, consome da fila ───────────────────────
def _worker():
    while True:
        dados, tentativa = _fila.get()
        try:
            _enviar_http(dados)
        except Exception as e:
            # Retry com backoff exponencial leve
            if tentativa < MAX_RETRIES:
                espera = 0.2 * (2 ** tentativa)   # 0.2s, 0.4s
                time.sleep(espera)
                try:
                    _fila.put_nowait((dados, tentativa + 1))
                except queue.Full:
                    sid = dados.get("id", "?")
                    print(f"[GATEWAY] Fila cheia, descartando retry de {sid}")
            else:
                sid = dados.get("id", "?")
                print(f"[GATEWAY] Descartado após {MAX_RETRIES} tentativas: {sid} — {e}")
        finally:
            _fila.task_done()


def _enviar_http(dados):
    payload = json.dumps(dados).encode("utf-8")
    req = urllib.request.Request(
        SENSOR_ENDPOINT,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        resposta = resp.read().decode("utf-8")
        sid = dados.get("id", "?")
        print(f"[GATEWAY] OK {sid}: {resposta.strip()}")


# ── Listener UDP — só recebe e enfileira, nunca bloqueia ─────────────────────
def escutar():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", UDP_PORT))
    print(f"[GATEWAY] Escutando UDP:{UDP_PORT} → {SENSOR_ENDPOINT}")
    print(f"[GATEWAY] Pool: {WORKERS} workers, fila máx {QUEUE_MAX}, timeout {TIMEOUT_S}s")

    while True:
        data, addr = sock.recvfrom(1024)
        try:
            dados     = json.loads(data.decode("utf-8"))
            sensor_id = dados.get("id", "desconhecido")
            tipo      = dados.get("tipo", "?")
            print(f"[GATEWAY] {sensor_id} ({tipo}): {dados}")
            _fila.put_nowait((dados, 0))
        except queue.Full:
            print(f"[GATEWAY] Fila cheia — pacote de {addr} descartado")
        except json.JSONDecodeError:
            print(f"[ERRO] JSON inválido de {addr}")


# ── Inicialização ─────────────────────────────────────────────────────────────
if __name__ == "__main__":
    # Sobe o pool de workers
    for _ in range(WORKERS):
        threading.Thread(target=_worker, daemon=True).start()

    # Listener UDP na thread principal
    try:
        escutar()
    except KeyboardInterrupt:
        print("\n[GATEWAY] Encerrando...")