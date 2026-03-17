from http.server import HTTPServer, BaseHTTPRequestHandler
import json

estado = {"temperatura": None}

class Handler(BaseHTTPRequestHandler):

    def responder(self, dados, status=200):  # <-- adiciona parâmetro status
        json_str = json.dumps(dados) + "\n"
        body = json_str.encode("utf-8")
        
        self.send_response(status)  # <-- usa o status recebido
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
        self.responder(estado)

    def do_POST(self):
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length == 0:
                return self.responder({"erro": "Corpo vazio"}, 400)  # <-- vírgula corrigida

            body = self.rfile.read(content_length)
            dados = json.loads(body.decode("utf-8"))

            if "valor" in dados:
                estado["temperatura"] = dados["valor"]
                print(f"[SERVER] Temperatura atualizada: {dados['valor']}°C")
                self.responder(estado)
            else:
                self.responder({"erro": "Chave 'valor' nao encontrada"}, 400)

        except json.JSONDecodeError:
            self.responder({"erro": "JSON invalido"}, 400)
        except Exception as e:
            print(f"[ERRO] {e}")
            self.responder({"erro": str(e)}, 500)

if __name__ == "__main__":
    server_address = ("0.0.0.0", 5000)
    httpd = HTTPServer(server_address, Handler)
    print("[SERVER] Rodando em http://localhost:5000...")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[SERVER] Desligando...")
        httpd.server_close()