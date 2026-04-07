# =============================================================================
# ALARME.PY — Serviço de Alarme (TCP, porta 6000)
# =============================================================================
# Responsabilidades:
#   - Aguarda comandos TCP enviados pelo servidor central (server.py)
#   - Verifica se o sensor está em período de cooldown antes de disparar
#   - Exibe alerta visual/sonoro no terminal quando um limite é ultrapassado
#   - Persiste cada acionamento em data/atuadores.json
#
# Fluxo resumido:
#   server.py detecta valor fora do limite
#       └→ envia JSON via TCP para este serviço na porta 6000
#           └→ alarme.py valida cooldown → exibe alerta → salva → responde
# =============================================================================

import socket
import json
import os
from datetime import datetime, timezone, timedelta

# ── Configuração do servidor TCP ──────────────────────────────────────────────
TCP_IP   = "0.0.0.0"   # Aceita conexões de qualquer interface (dentro do container)
TCP_PORT = 6000

# ── Persistência ──────────────────────────────────────────────────────────────
ATUADORES_FILE = "data/atuadores.json"

# Fuso horário UTC-3 (Brasília) — usado em todos os timestamps
FUSO_BRASIL = timezone(timedelta(hours=-3))

# ── Cooldown por sensor ───────────────────────────────────────────────────────
# Evita spam de alertas
COOLDOWN_SEGUNDOS = int(os.environ.get("ALARME_COOLDOWN", 30))

# Dicionário em memória que registra o instante do último alarme por sensor.
_ultimo_alarme: dict[str, datetime] = {}

# Garante que o diretório de dados existe antes de qualquer escrita
os.makedirs("data", exist_ok=True)


# =============================================================================
# FUNÇÕES UTILITÁRIAS
# =============================================================================

def timestamp_br() -> str:
    """Retorna o instante atual como string formatada no fuso de Brasília."""
    return datetime.now(FUSO_BRASIL).strftime("%Y-%m-%d %H:%M:%S.%f")


def agora() -> datetime:
    """Retorna o datetime atual com fuso horário de Brasília."""
    return datetime.now(FUSO_BRASIL)


# =============================================================================
# PERSISTÊNCIA
# =============================================================================

def carregar_atuadores() -> list:
    """
    Lê atuadores.json e retorna a lista de eventos.
    Retorna lista vazia se o arquivo não existir ou estiver corrompido.
    """
    try:
        with open(ATUADORES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []


def salvar_atuacao(evento: dict):
    
    # Acrescenta um evento de alarme ao arquivo atuadores.json.
    # o histórico existente, adiciona o novo evento e reescreve o arquivo(Single-threaded).
    
    historico = carregar_atuadores()
    historico.append(evento)
    with open(ATUADORES_FILE, "w", encoding="utf-8") as f:
        json.dump(historico, f, indent=2)


# =============================================================================
# LÓGICA DE COOLDOWN
# =============================================================================

def em_cooldown(nome_sensor: str) -> tuple[bool, float]:
    
    # Verifica se o sensor ainda está no período de silêncio pós-alarme.

    ultimo = _ultimo_alarme.get(nome_sensor)
    if ultimo is None:
        return False, 0.0  # Sensor nunca acionou alarme — liberado

    decorrido = (agora() - ultimo).total_seconds()
    restante  = COOLDOWN_SEGUNDOS - decorrido
    return restante > 0, max(0.0, restante)


# =============================================================================
# EXECUÇÃO DO ALARME
# =============================================================================

def executar_alarme(cmd: dict) -> str:
    # Processa um comando de alarme recebido via TCP.
    
    valor       = cmd.get("valor")
    sensor      = cmd.get("sensor")
    nome_sensor = cmd.get("nome_sensor", "desconhecido")

    # ── Validação dos campos obrigatórios ─────────────────────────────────────
    if not sensor or valor is None:
        print("[ALARME] Comando inválido recebido.")
        return "erro"

    # ── Verificação de cooldown ───────────────────────────────────────────────
    cooldown, restante = em_cooldown(nome_sensor)
    if cooldown:
        print(f"[ALARME] ⏳ Ignorado — {nome_sensor} em cooldown ({restante:.0f}s restantes)")
        return "cooldown"

    # ── Atualiza o registro do último alarme ANTES de exibir (evita re-entrada)
    _ultimo_alarme[nome_sensor] = agora()

    # ── Exibe alerta no terminal ──────────────────────────────────────────────
    print(f"\n{'='*42}")
    print(f"🚨 [ALARME] {sensor.upper()} = {valor} — fora do limite!")
    print(f"   Sensor  : {nome_sensor}")
    print(f"   Horário : {timestamp_br()}")
    print(f"   Cooldown: próximo alarme deste sensor em {COOLDOWN_SEGUNDOS}s")
    print(f"{'='*42}\n")

    # Alerta sonoro via caracter BEL — funciona em terminais Linux/macOS;
    # pode não funcionar em ambientes Docker sem TTY alocado.
    print("\a")

    return "ok"


# =============================================================================
# SERVIDOR TCP — loop principal
# =============================================================================

# Cria e configura o socket TCP
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

# SO_REUSEADDR: permite reutilizar a porta imediatamente após reiniciar o serviço,
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

sock.bind((TCP_IP, TCP_PORT))
sock.listen(5)  

print(f"[ALARME] Escutando TCP na porta {TCP_PORT}...")
print(f"[ALARME] Cooldown por sensor: {COOLDOWN_SEGUNDOS}s")

try:
    while True:
        # Bloqueia até uma nova conexão chegar (server.py conecta aqui)
        conn, addr = sock.accept()

        with conn:  # Garante fechamento do socket ao sair do bloco
            data = conn.recv(1024)  # Lê até 1024 bytes do comando enviado

            if not data:
                continue  # Conexão aberta mas sem dados — ignora

            try:
                # Desserializa o JSON recebido e processa o alarme
                comando   = json.loads(data.decode("utf-8"))
                resultado = executar_alarme(comando)

                # Responde ao server.py com o status do processamento:
                # "ok" | "cooldown" | "erro"
                conn.sendall(json.dumps({"status": resultado}).encode("utf-8"))

            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                # Dados corrompidos ou encoding inesperado — responde com erro
                print(f"[ALARME] Erro ao decodificar: {e}")
                conn.sendall(b'{"status": "erro"}')

except KeyboardInterrupt:
    # Ctrl+C: encerra, fechando o socket antes de sair
    print("\n[ALARME] Encerrando...")
    sock.close()