from http.server import HTTPServer, BaseHTTPRequestHandler
import json

estado = {
    "temperatura": None
}

class Handler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        pass

    def responder(self, dados):
        body = json.dumps(dados).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.responder(estado)

    def do_POST(self):
        tamanho = int(self.headers.get("Content-Length", 0))
        dados = json.loads(self.rfile.read(tamanho))
        estado["temperatura"] = dados["valor"]
        print(f"[SERVER] Temperatura recebida: {dados['valor']}°C")
        self.responder(estado)

httpd = HTTPServer(("0.0.0.0", 5000), Handler)
print("[SERVER] Rodando na porta 5000...")
httpd.serve_forever()