from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import os
import threading
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse
import queue

# Bug 6 corrigido: era "dados/", agora "data/" — consistente com o projeto
os.makedirs("data", exist_ok=True)

ATUADORES_FILE = "data/atuadores.json"
HISTORICO_FILE = "data/historico.json"

FUSO_BRASIL = timezone(timedelta(hours=-3))

ALARME_IP         = "alarme"
ALARME_PORT       = 6000
RESFRIAMENTO_IP   = "resfriamento"
RESFRIAMENTO_PORT = 6001

LIMITES = {
    "temperatura": {"max": 33, "min": 20},
    "umidade":     {"max": 85, "min": 45}
}

estado = {}
lock   = threading.Lock()

# Fila única para histórico E atuadores — sem race condition (Bug 5)
fila_disco         = queue.Queue()
fila_atuadores     = queue.Queue()


def timestamp_br():
    return datetime.now(FUSO_BRASIL).strftime("%Y-%m-%d %H:%M:%S.%f")


# Bug 4 corrigido: usa "timestamp" (igual aos serviços de alarme/resfriamento)
# Bug 5 corrigido: enfileira em vez de escrever direto no disco
def salvar_atuador(sensor, valor, acao, nome_sensor):
    fila_atuadores.put({
        "nome_sensor": nome_sensor,
        "sensor":      sensor,
        "valor":       valor,
        "acao":        acao,
        "timestamp":   timestamp_br()
    })


def carregar_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            dados = json.load(f)
            return dados if isinstance(dados, list) else []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def salvar_historico(sensor_id, tipo, valor):
    fila_disco.put({
        "id":      sensor_id,
        "tipo":    tipo,
        "valor":   valor,
        "horario": timestamp_br()
    })


def worker_historico():
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
            if len(historico) > 10000:
                historico = historico[-10000:]
            with open(HISTORICO_FILE, "w", encoding="utf-8") as f:
                json.dump(historico, f, indent=2)


def worker_atuadores():
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


def enviar_alarme(sensor, valor, nome_sensor):
    try:
        comando = json.dumps({
            "sensor":      sensor,
            "nome_sensor": nome_sensor,
            "valor":       valor,
            "acao":        "ALARME"
        }).encode("utf-8")

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((ALARME_IP, ALARME_PORT))
            s.sendall(comando)
            resposta = s.recv(1024)
            print(f"[SERVER] Alarme respondeu: {resposta.decode()}")

    except ConnectionRefusedError:
        print("[ERRO] Servico de alarme nao esta rodando!")

    salvar_atuador(sensor, valor, "ALARME", nome_sensor)


def enviar_resfriamento(sensor, valor, nome_sensor):
    try:
        comando = json.dumps({
            "sensor":      sensor,
            "nome_sensor": nome_sensor,
            "valor":       valor,
            "acao":        "RESFRIAMENTO"
        }).encode("utf-8")

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((RESFRIAMENTO_IP, RESFRIAMENTO_PORT))
            s.sendall(comando)
            resposta = s.recv(1024)
            print(f"[SERVER] Resfriamento respondeu: {resposta.decode()}")

    except ConnectionRefusedError:
        print("[ERRO] Servico de resfriamento nao esta rodando!")

    salvar_atuador(sensor, valor, "RESFRIAMENTO", nome_sensor)


# Bug 3 corrigido: threshold de resfriamento era max*1.1 (36.3°C),
# agora é max+2 (35°C) — janela muito mais atingível pelo sensor
def verificar_risco(sensor, valor, nome_sensor):
    limites = LIMITES.get(sensor)
    if not limites:
        return

    if valor > limites["max"]:
        print(f"[SERVER] {sensor} alta ({nome_sensor}): {valor}")
        enviar_alarme(sensor, valor, nome_sensor)

        if valor > limites["max"] + 2:
            enviar_resfriamento(sensor, valor, nome_sensor)

    elif valor < limites["min"]:
        print(f"[SERVER] {sensor} baixa ({nome_sensor}): {valor}")
        enviar_alarme(sensor, valor, nome_sensor)


def escutar_sensores():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 5001))
    print("[SERVER] Escutando sensores UDP na porta 5001...")

    while True:
        data, _ = sock.recvfrom(1024)

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
                valor = dados["umidade"]
                print(f"[SERVER] {sensor_id}: {valor}%")
                with lock:
                    estado[sensor_id] = {"tipo": "umidade", "valor": valor}
                salvar_historico(sensor_id, "umidade", valor)
                verificar_risco("umidade", valor, sensor_id)

        except (json.JSONDecodeError, KeyError) as e:
            print(f"[SERVER] Erro UDP: {e}")


def processar_sensor(dados, responder_fn):
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
        valor = dados.get("umidade", dados.get("valor"))
        with lock:
            estado[sensor_id] = {"tipo": "umidade", "valor": valor}
        salvar_historico(sensor_id, "umidade", valor)
        verificar_risco("umidade", valor, sensor_id)
        responder_fn({"status": "ok"})

    else:
        responder_fn({"erro": "invalido"}, 400)


class Handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass

    def responder(self, dados, status=200):
        body = (json.dumps(dados) + "\n").encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/historico":
            self.responder(carregar_json(HISTORICO_FILE))

        elif parsed.path == "/estado":
            with lock:
                self.responder(estado)

        elif parsed.path == "/atuadores":
            self.responder(carregar_json(ATUADORES_FILE))

        else:
            self.responder({"erro": "rota"}, 404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body   = self.rfile.read(length)

        try:
            dados = json.loads(body.decode())

            if self.path == "/sensor":
                processar_sensor(dados, self.responder)

            elif self.path == "/ativar/alarme":
                # Acionamento manual: dispara o serviço de alarme, salva em
                # atuadores.json e registra no histórico como evento manual.
                threading.Thread(
                    target=enviar_alarme,
                    args=("manual", 0, "acionamento_manual"),
                    daemon=True
                ).start()
                salvar_historico("acionamento_manual", "alarme_manual", 0)
                self.responder({"acao": "ALARME", "status": "ok"})

            elif self.path == "/ativar/resfriamento":
                # Acionamento manual: dispara o serviço de resfriamento, que
                # por sua vez notifica todos os sensores de temperatura via TCP
                # (Event resfriando fica ativo por TEMPO_RESFRIAMENTO segundos).
                threading.Thread(
                    target=enviar_resfriamento,
                    args=("manual", 0, "acionamento_manual"),
                    daemon=True
                ).start()
                salvar_historico("acionamento_manual", "resfriamento_manual", 0)
                self.responder({"acao": "RESFRIAMENTO", "status": "ok"})

            else:
                self.responder({"erro": "rota"}, 404)

        except Exception:
            self.responder({"erro": "json"}, 400)


if __name__ == "__main__":
    threading.Thread(target=escutar_sensores,  daemon=True).start()
    threading.Thread(target=worker_historico,  daemon=True).start()
    threading.Thread(target=worker_atuadores,  daemon=True).start()

    httpd = ThreadingHTTPServer(("0.0.0.0", 5000), Handler)
    print("[SERVER] Rodando em http://localhost:5000")
    httpd.serve_forever()