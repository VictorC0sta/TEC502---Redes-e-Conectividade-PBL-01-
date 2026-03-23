from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import random
import socket
from datetime import datetime

HISTORICO_FILE = "historico.json"
ATUADOR_IP = "127.0.0.1"
ATUADOR_PORT = 6000
SENSOR_IP = "127.0.0.1"
SENSOR_PORT = 7000

LIMITES = {
    "temperatura": {"max": 33, "min": 20},
    "umidade":     {"max": 80, "min": 45}
}

estado = {
    "sensor_01": {
        "tipo": "temperatura",
        "valor": round(random.uniform(20.0, 35.0), 2)
    },
    "sensor_02": {
        "tipo": "umidade",
        "valor": round(random.uniform(40.0, 90.0), 2)
    }
}

def carregar_historico():
    try:
        with open(HISTORICO_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def salvar_historico(atualizado):
    historico = carregar_historico()
    historico.append({
        **atualizado,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    with open(HISTORICO_FILE, "w") as f:
        json.dump(historico, f, indent=2)

def enviar_comando_atuador(sensor, valor, acao, nome_sensor):
    try:
        comando = json.dumps({
            "sensor": sensor,
            "nome_sensor": nome_sensor,
            "valor": valor,
            "acao": acao
        }).encode("utf-8")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((ATUADOR_IP, ATUADOR_PORT))
            s.sendall(comando)
            resposta = s.recv(1024)
            print(f"[SERVER] Atuador respondeu: {resposta.decode()}")
    except ConnectionRefusedError:
        print("[ERRO] Atuador não está rodando!")

def avisar_sensor_resfriamento():
    try:
        comando = json.dumps({"acao": "RESFRIAMENTO"}).encode("utf-8")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((SENSOR_IP, SENSOR_PORT))
            s.sendall(comando)
            s.recv(1024)
            print("[SERVER] Sensor avisado para resfriar!")
    except ConnectionRefusedError:
        print("[ERRO] Sensor TCP não está rodando!")

def verificar_risco(sensor, valor, nome_sensor):
    limites = LIMITES.get(sensor)
    if not limites:
        return

    if valor > limites["max"]:
        print(f"[SERVER] ⚠️  {sensor} alta: {valor}")
        enviar_comando_atuador(sensor, valor, "ALARME", nome_sensor)
        if valor > limites["max"] * 1.1:
            enviar_comando_atuador(sensor, valor, "RESFRIAMENTO", nome_sensor)
            avisar_sensor_resfriamento()

    elif valor < limites["min"]:
        print(f"[SERVER] ⚠️  {sensor} baixa: {valor}")
        enviar_comando_atuador(sensor, valor, "ALARME", nome_sensor)

class Handler(BaseHTTPRequestHandler):

    def responder(self, dados, status=200):
        json_str = json.dumps(dados) + "\n"
        body = json_str.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
            self.wfile.flush()
            print(f"[DEBUG] Enviado com sucesso: {json_str.strip()}")
        except Exception as e:
            print(f"[ERRO ao enviar] {e}")

    def do_GET(self):
        if self.path == "/historico":
            self.responder(carregar_historico())
        else:
            self.responder(estado)

    def do_POST(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length == 0:
                return self.responder({"erro": "Corpo vazio"}, 400)

            body = self.rfile.read(content_length)
            dados = json.loads(body.decode("utf-8"))

            atualizado = {}

            if "valor" in dados:
                estado["sensor_01"]["valor"] = dados["valor"]
                atualizado["sensor_01"] = dados["valor"]
                print(f"[SERVER] Temperatura atualizada: {dados['valor']}°C")
                verificar_risco("temperatura", dados["valor"], "sensor_01")

            if "umidade" in dados:
                estado["sensor_02"]["valor"] = dados["umidade"]
                atualizado["sensor_02"] = dados["umidade"]
                print(f"[SERVER] Umidade atualizada: {dados['umidade']}%")
                verificar_risco("umidade", dados["umidade"], "sensor_02")

            if atualizado:
                salvar_historico(atualizado)
                self.responder(estado)
            else:
                self.responder({"erro": "Nenhuma chave reconhecida"}, 400)

        except json.JSONDecodeError:
            self.responder({"erro": "JSON invalido"}, 400)
        except Exception as e:
            print(f"[ERRO] {e}")
            self.responder({"erro": str(e)}, 500)

if __name__ == "__main__":
    server_address = ("0.0.0.0", 5000)
    httpd = HTTPServer(server_address, Handler)
    print("[SERVER] Rodando em http://localhost:5000...")
    print(f"[SERVER] Limites de risco: {LIMITES}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[SERVER] Desligando...")
        httpd.server_close()