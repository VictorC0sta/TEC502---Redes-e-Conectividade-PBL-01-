
---
# 🏭 Sistema IoT-Industrial — Monitoramento Distribuído em Tempo Real

> Projeto desenvolvido para a disciplina **TEC502 — Redes e Conectividade** | PBL 01  
> Universidade Estadual de Feira de Santana (UEFS)

---

## Sumário
<!--ts-->
* [Visão Geral](#visão-geral)
* [Arquitetura do Sistema](#arquitetura-do-sistema)
  * [Diagrama de Componentes](#diagrama-de-componentes)
  * [Separação Dual-Host](#separação-dual-host)
* [Comunicação entre Componentes](#comunicação-entre-componentes)
  * [UDP — Sensores → Gateway](#udp--sensores--gateway)
  * [HTTP — Gateway → Server](#http--gateway--server)
  * [TCP — Server → Atuadores](#tcp--server--atuadores)
* [Protocolo de Comunicação (API REST)](#protocolo-de-comunicação-api-rest)
  * [Endpoints disponíveis](#endpoints-disponíveis)
  * [Formato das mensagens](#formato-das-mensagens)
* [Encapsulamento e Tratamento de Dados](#encapsulamento-e-tratamento-de-dados)
* [Concorrência](#concorrência)
* [Qualidade de Serviço](#qualidade-de-serviço)
* [Interface do Usuário](#interface-do-usuário)
* [Confiabilidade](#confiabilidade)
* [Testes](#testes)
* [Execução com Docker — Passo a Passo](#execução-com-docker--passo-a-passo)
  * [Pré-requisitos](#pré-requisitos)
  * [Máquina A — Server e Gateway](#máquina-a--server-e-gateway)
  * [Máquina B — Sensores e Atuadores](#máquina-b--sensores-e-atuadores)
  * [Interface Gráfica](#interface-gráfica)
* [Estrutura de Arquivos](#estrutura-de-arquivos)
* [Referências](#referências)
<!--te-->

---

## Visão Geral

Este projeto implementa um sistema distribuído de monitoramento IoT com foco em **baixo acoplamento entre componentes**, utilizando exclusivamente protocolos nativos da Internet. A solução simula um ambiente realista de monitoramento industrial, onde múltiplos dispositivos geram dados continuamente e ações são tomadas automaticamente em tempo real.

O sistema é composto por cinco camadas independentes:

| Componente | Função |
|---|---|
| **Sensores** | Geram leituras de temperatura e umidade continuamente |
| **Gateway** | Recebe dados UDP e os encaminha via HTTP ao servidor (broker) |
| **Server** | Processa dados, verifica limites e aciona atuadores via TCP |
| **Atuadores** | Executam ações físicas (alarme e resfriamento) |
| **Interface** | Dashboard gráfico em tempo real para monitoramento e controle |

---

## Arquitetura do Sistema

A arquitetura segue um modelo em camadas, onde cada componente possui responsabilidade única e bem definida. Essa separação garante que falhas em um componente não comprometam os demais.

### Diagrama de Componentes

```text
[SENSOR TEMP 1]  [SENSOR TEMP 2]  [SENSOR TEMP 3]
[SENSOR UMID 1]  [SENSOR UMID 2]
        |
        | UDP (porta 5001) — telemetria leve, sem conexão
        ↓
   [GATEWAY]  ← converte UDP → HTTP (broker de protocolo)
        |
        | HTTP POST /sensor
        ↓
    [SERVER]  ← API REST, verifica limites, detecta bordas
        |
        ├─── TCP (porta 6000) ──→ [ALARME]
        └─── TCP (porta 6001) ──→ [RESFRIAMENTO] ──→ notifica sensores via TCP 7000

[INTERFACE] ←── HTTP GET/POST ──→ [SERVER]
```

### Separação Dual-Host

O sistema foi projetado para rodar em **duas máquinas físicas distintas**:

| Máquina | Componentes | Compose |
|---|---|---|
| **larsid05** (Máquina A) | Server + Gateway | `docker-compose-server.yml` |
| **larsid04** (Máquina B) | Sensores + Atuadores | `docker-compose-sa.yml` |

A conectividade entre as máquinas é feita via variáveis de ambiente (`CORE_HOST_IP` e `EDGE_HOST_IP`), sem nenhum IP fixo no código.

---

## Comunicação entre Componentes

A escolha de protocolo foi feita de acordo com a natureza de cada tipo de dado trafegado.

### UDP — Sensores → Gateway

Telemetria é um fluxo contínuo de dados onde pequenas perdas são toleráveis. O UDP oferece baixo overhead e alta velocidade, sendo ideal para esse cenário. Implementado com `SOCK_DGRAM`:

```python
sock.sendto(json.dumps(dado).encode(), (SERVER_IP, UDP_PORT))
```

### HTTP — Gateway → Server

O gateway converte os pacotes UDP em requisições HTTP POST ao servidor. Essa escolha facilita a integração com qualquer cliente HTTP externo e permite monitoramento direto via `curl` ou navegador.

```python
urllib.request.urlopen(req, timeout=TIMEOUT_S)
```

### TCP — Server → Atuadores

Comandos para atuadores exigem confiabilidade — não podem ser perdidos. O TCP garante entrega, ordem e integridade. Implementado com `SOCK_STREAM` e timeout configurado:

```python
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.settimeout(3)
    s.connect((ALARME_IP, ALARME_PORT))
    s.sendall(comando)
```

---

## Protocolo de Comunicação (API REST)

### Endpoints disponíveis

| Método | Rota | Descrição |
|---|---|---|
| `GET` | `/estado` | Último valor conhecido de cada sensor (memória) |
| `GET` | `/historico` | Todas as leituras persistidas em `historico.json` |
| `GET` | `/atuadores` | Log de todos os acionamentos em `atuadores.json` |
| `POST` | `/sensor` | Ingestão manual de leitura de sensor |
| `POST` | `/ativar/alarme` | Aciona alarme manualmente |
| `POST` | `/ativar/resfriamento` | Aciona resfriamento manualmente |

### Formato das mensagens

**Leitura de sensor (enviada pelo gateway):**
```json
{
  "id": "sensor_temp_1",
  "tipo": "temperatura",
  "valor": 36.5,
  "horario": "2026-04-08 17:28:49.394173"
}
```

**Comando para atuador (enviado pelo server via TCP):**
```json
{
  "sensor": "temperatura",
  "nome_sensor": "sensor_temp_1",
  "valor": 36.5,
  "acao": "ALARME"
}
```

**Resposta do atuador:**
```json
{ "status": "ok" }
```

---

## Encapsulamento e Tratamento de Dados

JSON é o formato padrão em todas as camadas do sistema. A conversão é feita com as bibliotecas padrão `json.loads()` e `json.dumps()`.

Para robustez, todos os pontos de entrada tratam dados inválidos de forma isolada:

```python
try:
    dados = json.loads(data.decode("utf-8"))
except (json.JSONDecodeError, UnicodeDecodeError) as e:
    print(f"[ERRO] Dados inválidos: {e}")
    conn.sendall(b'{"status": "erro"}')
```

Dados corrompidos são descartados sem interromper o fluxo — o sistema continua processando os demais pacotes normalmente.

---

## Concorrência

A concorrência está presente em todas as camadas do sistema.

**Gateway:** thread principal recebe UDP e enfileira; pool de 4 workers consome a fila e faz os POSTs HTTP em paralelo. Isso garante que o listener UDP nunca bloqueie por causa de chamadas HTTP lentas.

**Server:** usa `ThreadingHTTPServer` para atender múltiplas requisições simultaneamente. Threads daemon separadas gerenciam escrita em disco (`worker_historico`, `worker_atuadores`) usando filas assíncronas com escrita em lote de até 20 entradas. Um `threading.Lock` protege o estado compartilhado em memória.

**Interface:** thread de I/O separada busca dados do servidor; a thread principal da UI apenas consome uma fila de resultados, garantindo que a interface permaneça responsiva.

```
GATEWAY                   SERVER                   INTERFACE
  │                          │                          │
  ├─ UDP Listener (main)     ├─ ThreadingHTTPServer     ├─ UI Thread (tkinter)
  ├─ Worker 1 (HTTP)         ├─ Thread UDP 5001         └─ IO Thread (requests)
  ├─ Worker 2 (HTTP)         ├─ Worker Histórico
  ├─ Worker 3 (HTTP)         └─ Worker Atuadores
  └─ Worker 4 (HTTP)
```

---

## Qualidade de Serviço

| Estratégia | Onde | Detalhe |
|---|---|---|
| Fila com limite | Gateway | `maxsize=200` — descarta se servidor estiver inativo |
| Retry com backoff | Gateway | Até 2 tentativas com espera exponencial (0.2s, 0.4s) |
| Escrita em lote | Server | Lotes de 20 entradas por flush em disco |
| Janela deslizante | Server | Máximo 10.000 registros por arquivo JSON |
| Timeout em sockets | Server | `settimeout(3)` em conexões TCP com atuadores |
| Detecção de borda | Server | Alarme só dispara na transição normal→crítico (evita spam) |
| Cooldown | Alarme | Silencia re-acionamentos por `N` segundos (configurável) |

---

## Interface do Usuário

A interface é um dashboard Tkinter com tema escuro e três abas:

- **Tempo Real** — gráficos ao vivo de temperatura e umidade com linhas de limite
- **Histórico** — consulta por período com resumo estatístico por sensor
- **Acionamentos** — linha do tempo de alarmes e resfriamentos registrados

Botões de acionamento manual permitem disparar alarme e resfriamento diretamente pela interface, que envia `POST /ativar/alarme` e `POST /ativar/resfriamento` ao servidor.

---

## Confiabilidade

O sistema foi projetado para degradar de forma controlada diante de falhas:

- **Sensor offline:** servidor para de receber dados daquele sensor, mas os demais continuam normalmente
- **Atuador offline:** server captura a exceção (`ConnectionRefusedError`, `OSError`, `TimeoutError`), registra o erro e salva o acionamento em `atuadores.json` via `finally` — garantindo persistência mesmo sem resposta TCP
- **Gateway sobrecarregado:** pacotes além do limite da fila são descartados — o listener UDP nunca bloqueia
- **Interface sem conexão:** exibe "sem conexão" e continua tentando reconectar automaticamente a cada ciclo de polling

```python
try:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(3)
        s.connect((ALARME_IP, ALARME_PORT))
        s.sendall(comando)
except (ConnectionRefusedError, OSError, TimeoutError) as e:
    print(f"[ERRO] Alarme inacessível: {e}")
finally:
    salvar_atuador(sensor, valor, "ALARME", nome_sensor)
```

---

## Testes

Os testes cobrem as principais rotas e comportamentos do servidor. Execute com o sistema no ar:

```bash
cd interface
source venv/bin/activate
python testes.py
```

| Teste | O que valida |
|---|---|
| `teste_server_online` | Server responde na porta 5050 |
| `teste_historico` | `/historico` retorna lista válida |
| `teste_atuadores` | `/atuadores` retorna lista válida |
| `teste_alarme_manual` | POST `/ativar/alarme` retorna `status: ok` |
| `teste_resfriamento_manual` | POST `/ativar/resfriamento` retorna `status: ok` |
| `teste_sensor_via_http` | Ingestão de sensor via POST `/sensor` |
| `teste_rota_invalida` | Rota inexistente retorna 404 |
| `teste_json_invalido` | JSON mal formado retorna 400 |

---

## Execução com Docker — Passo a Passo

### Pré-requisitos

- Docker e Docker Compose instalados em ambas as máquinas
- As duas máquinas na mesma rede (laboratório larsid)
- Python 3.11+ com `tkinter`, `requests` e `matplotlib` na máquina que rodará a interface

### Máquina A — Server e Gateway

```bash
# 1. Entre na pasta docker do projeto
cd ~/victor/TEC502---Redes-e-Conectividade-PBL-01-/docker

# 2. Exporte o IP da Máquina B (onde estão os atuadores)
exemplo:
export EDGE_HOST_IP=172.16.103.5

# 3. Suba os containers
docker compose -f docker-compose-server.yml up --build
```

### Máquina B — Sensores e Atuadores

```bash
# 1. Entre na pasta docker do projeto
cd ~/Downloads/ultimoteste/TEC502---Redes-e-Conectividade-PBL-01-/docker

# 2. Exporte o IP da Máquina A (onde está o server/gateway)
exemplo:
export CORE_HOST_IP=172.16.103.4
export EDGE_HOST_IP=172.16.103.5

# 3. Suba os containers
docker compose -f docker-compose-sa.yml up --build
```

### Interface Gráfica

```bash
# Execute na Máquina A (ou qualquer máquina com acesso à rede)
cd ~/victor/TEC502---Redes-e-Conectividade-PBL-01-/interface

source venv/bin/activate

# Instale as dependências (apenas na primeira vez)
pip install requests matplotlib

# Exporte o endereço do servidor
export SERVER_URL=http://172.16.103.5:5050

python cliente.py
```

> **Ordem obrigatória:** primeiro Máquina A (server), depois Máquina B (sensores), depois a interface.

### Verificação rápida

```bash
# Confirmar que o server está respondendo
curl http://172.16.103.5:5050/estado

# Confirmar histórico
curl http://172.16.103.5:5050/historico

# Confirmar atuadores
curl http://172.16.103.5:5050/atuadores
```

---

## Estrutura de Arquivos

```
TEC502---Redes-e-Conectividade-PBL-01-/
├── data/
│   ├── atuadores.json        # Log de acionamentos (persistido pelo server)
│   └── historico.json        # Histórico de leituras dos sensores
├── docker/
│   ├── docker-compose-server.yml   # Máquina A: server + gateway
│   └── docker-compose-sa.yml       # Máquina B: sensores + atuadores
├── gateway/
│   ├── Dockerfile
│   └── gateway.py            # Bridge UDP→HTTP com pool de workers
├── interface/
│   ├── Dockerfile
│   ├── cliente.py            # Dashboard Tkinter
│   └── testes.py             # Testes de integração
├── server/
│   ├── Dockerfile
│   └── server.py             # API REST + lógica de limites + workers de disco
└── services/
    ├── atuadores/
    │   ├── Dockerfile
    │   ├── alarme.py         # Serviço TCP porta 6000
    │   └── resfriamento.py   # Serviço TCP porta 6001
    └── sensores/
        ├── Dockerfile
        ├── temperatura.py    # Sensor UDP com suporte a resfriamento TCP
        └── umidade.py        # Sensor UDP
```

---

## Referências

- TANENBAUM, Andrew S.; WETHERALL, David. *Computer Networks*. 5ª ed. Pearson, 2011.
- STEVENS, W. Richard. *UNIX Network Programming, Volume 1: The Sockets Networking API*. Addison-Wesley, 2003.
- GOETZ, Brian et al. *Java Concurrency in Practice*. Addison-Wesley, 2006.
- Python Software Foundation. *socket — Low-level networking interface*. Disponível em: https://docs.python.org/3/library/socket.html
