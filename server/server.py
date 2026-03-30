from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import socket
import os
import threading
from datetime import datetime, timezone, timedelta
from urllib.parse import urlparse, parse_qs

os.makedirs("dados", exist_ok=True)

HISTORICO_FILE    = "dados/historico.json"
FUSO_BRASIL       = timezone(timedelta(hours=-3))
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


def timestamp_br():
    return datetime.now(FUSO_BRASIL).strftime("%Y-%m-%d %H:%M:%S")


def carregar_historico():
    try:
        with open(HISTORICO_FILE, "r", encoding="utf-8") as f:
            dados = json.load(f)
            # Garante que só retorna lista de dicts válidos
            if isinstance(dados, list):
                return [e for e in dados if isinstance(e, dict)]
            return []
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def salvar_historico(sensor_id, tipo, valor):
    with lock:
        historico = carregar_historico()
        historico.append({
            "id":        sensor_id,
            "tipo":      tipo,
            "valor":     valor,
            "timestamp": timestamp_br()
        })
        if len(historico) > 10000:
            historico = historico[-10000:]
        with open(HISTORICO_FILE, "w", encoding="utf-8") as f:
            json.dump(historico, f, indent=2)


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


def verificar_risco(sensor, valor, nome_sensor):
    limites = LIMITES.get(sensor)
    if not limites:
        return
    if valor > limites["max"]:
        print(f"[SERVER] {sensor} alta ({nome_sensor}): {valor}")
        enviar_alarme(sensor, valor, nome_sensor)
        if valor > limites["max"] * 1.1:
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
            else:
                print(f"[SERVER] Tipo desconhecido de {sensor_id}: {dados}")
        except (json.JSONDecodeError, KeyError) as e:
            print(f"[SERVER] Erro ao processar pacote UDP: {e}")


def processar_sensor(dados, responder_fn):
    """Lógica compartilhada entre UDP, POST /sensor e POST raiz."""
    sensor_id = dados.get("id", "desconhecido")
    tipo      = dados.get("tipo")

    if tipo == "temperatura" and "valor" in dados:
        valor = dados["valor"]
        print(f"[SERVER] HTTP {sensor_id}: {valor}C")
        with lock:
            estado[sensor_id] = {"tipo": "temperatura", "valor": valor}
        salvar_historico(sensor_id, "temperatura", valor)
        verificar_risco("temperatura", valor, sensor_id)
        responder_fn({"status": "ok", "id": sensor_id})

    elif tipo == "umidade" and ("umidade" in dados or "valor" in dados):
        # Aceita tanto {"umidade": X} quanto {"valor": X} para flexibilidade
        valor = dados.get("umidade", dados.get("valor"))
        print(f"[SERVER] HTTP {sensor_id}: {valor}%")
        with lock:
            estado[sensor_id] = {"tipo": "umidade", "valor": valor}
        salvar_historico(sensor_id, "umidade", valor)
        verificar_risco("umidade", valor, sensor_id)
        responder_fn({"status": "ok", "id": sensor_id})

    else:
        responder_fn({"erro": "Payload invalido"}, 400)


class Handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass

    def responder(self, dados, status=200):
        json_str = json.dumps(dados) + "\n"
        body     = json_str.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type",   "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError) as e:
            print(f"[ERRO ao enviar] {e}")

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if parsed.path == "/historico":
            historico = carregar_historico()

            segundos = params.get("segundos", [None])[0]
            if segundos:
                try:
                    segundos = int(segundos)
                    corte = datetime.now(FUSO_BRASIL) - timedelta(seconds=segundos)
                    historico = [
                        h for h in historico
                        if isinstance(h, dict) and
                           datetime.strptime(h["timestamp"], "%Y-%m-%d %H:%M:%S")
                           .replace(tzinfo=FUSO_BRASIL) >= corte
                    ]
                except (ValueError, KeyError):
                    pass

            minutos = params.get("minutos", [None])[0]
            if minutos:
                try:
                    minutos = int(minutos)
                    corte = datetime.now(FUSO_BRASIL) - timedelta(minutes=minutos)
                    historico = [
                        h for h in historico
                        if isinstance(h, dict) and
                           datetime.strptime(h["timestamp"], "%Y-%m-%d %H:%M:%S")
                           .replace(tzinfo=FUSO_BRASIL) >= corte
                    ]
                except (ValueError, KeyError):
                    pass

            limite = params.get("limite", [None])[0]
            if limite:
                try:
                    historico = historico[-int(limite):]
                except ValueError:
                    pass

            self.responder(historico)

        elif parsed.path == "/estado":
            with lock:
                self.responder(dict(estado))

        else:
            self.responder({"erro": "Rota nao encontrada"}, 404)

    def do_POST(self):
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length == 0:
                return self.responder({"erro": "Corpo vazio"}, 400)

            body  = self.rfile.read(content_length)
            dados = json.loads(body.decode("utf-8"))

            # ── Atuadores manuais ──
            if self.path == "/ativar/alarme":
                sensor_id = dados.get("sensor", "manual")
                valor     = dados.get("valor", 0)
                threading.Thread(
                    target=enviar_alarme,
                    args=(sensor_id, valor, "cliente_manual"),
                    daemon=True
                ).start()
                return self.responder({"status": "ok", "acao": "alarme disparado"})

            if self.path == "/ativar/resfriamento":
                sensor_id = dados.get("sensor", "manual")
                valor     = dados.get("valor", 0)
                threading.Thread(
                    target=enviar_resfriamento,
                    args=(sensor_id, valor, "cliente_manual"),
                    daemon=True
                ).start()
                return self.responder({"status": "ok", "acao": "resfriamento disparado"})

            # ── Dados de sensores via HTTP ──
            # Aceita tanto /sensor (gateway) quanto / (compatibilidade)
            if self.path in ("/sensor", "/"):
                return processar_sensor(dados, self.responder)

            self.responder({"erro": "Rota nao encontrada"}, 404)

        except json.JSONDecodeError:
            self.responder({"erro": "JSON invalido"}, 400)
        except Exception as e:
            print(f"[ERRO inesperado] {e}")
            self.responder({"erro": "Erro interno"}, 500)


if __name__ == "__main__":
    t_udp = threading.Thread(target=escutar_sensores, daemon=True)
    t_udp.start()
    server_address = ("0.0.0.0", 5000)
    httpd = ThreadingHTTPServer(server_address, Handler)
    print("[SERVER] Rodando em http://localhost:5000...")
    print(f"[SERVER] Limites: {LIMITES}")
    print(f"[SERVER] Rotas POST aceitas: /sensor, /ativar/alarme, /ativar/resfriamento")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[SERVER] Desligando...")
        httpd.server_close()