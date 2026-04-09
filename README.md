
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
* [Encapsulamento e Tratamento de Dados](#encapsulamento-e-tratamento-de-dados)
* [Concorrência](#concorrência)
* [Interface do Usuário](#interface-do-usuário)
* [Confiabilidade](#confiabilidade)
* [Escalabilidade](#escalabilidade)
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
[SENSORES-UMIDADE/TEMPERATURA]
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
| (Máquina A) | Server + Gateway | `docker-compose-server.yml` |
| (Máquina B) | Sensores + Atuadores | `docker-compose-sa.yml` |

A conectividade entre as máquinas é feita via variáveis de ambiente (`CORE_HOST_IP` e `EDGE_HOST_IP`), sem nenhum IP fixo no código.

---

## Comunicação entre Componentes

A escolha de protocolo foi feita de acordo com a natureza de cada tipo de dado trafegado.

### UDP — Sensores → Gateway

Telemetria é um fluxo contínuo de dados onde pequenas perdas são toleráveis. O UDP oferece baixo overhead e alta velocidade, sendo ideal para esse cenário.

### HTTP — Gateway → Server

O gateway converte os pacotes UDP em requisições HTTP POST ao servidor. Essa escolha facilita a integração com qualquer cliente HTTP externo e permite monitoramento direto via `curl` ou navegador.


### TCP — Server → Atuadores

Comandos para atuadores exigem confiabilidade — não podem ser perdidos. O TCP garante entrega, ordem e integridade. 

---

## Encapsulamento e Tratamento de Dados

JSON é o formato padrão em todas as camadas do sistema. A conversão é feita com as bibliotecas padrão `json.loads()` e `json.dumps()`.

Para robustez, todos os pontos de entrada tratam dados inválidos de forma isolada:


Dados corrompidos são descartados sem interromper o fluxo — o sistema continua processando os demais pacotes normalmente.

---

## Concorrência

A concorrência está presente em todas as camadas do sistema.

**Gateway:** thread principal recebe UDP e enfileira; pool de 4 workers consome a fila e faz os POSTs HTTP em paralelo. Isso garante que o listener UDP nunca bloqueie por causa de chamadas HTTP lentas.

**Server:** usa `ThreadingHTTPServer` para atender múltiplas requisições simultaneamente. Threads daemon separadas gerenciam escrita em disco (`worker_historico`, `worker_atuadores`) usando filas assíncronas com escrita em lote de até 20 entradas. Um `threading.Lock` protege o estado compartilhado em memória.

**Interface:** thread de I/O separada busca dados do servidor; a thread principal da UI apenas consome uma fila de resultados, garantindo que a interface permaneça responsiva.

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
- **Atuador offline:** server captura a exceção, registra o erro e salva o acionamento em atuadores.json via finally — garantindo persistência mesmo sem resposta TCP
- **Gateway sobrecarregado:** pacotes além do limite da fila são descartados — o listener UDP nunca bloqueia
- **Interface sem conexão:** exibe "sem conexão" e continua tentando reconectar automaticamente a cada ciclo de polling

## Escalabilidade

A arquitetura permite escalar horizontalmente:

- Múltiplos sensores podem ser adicionados sem alteração no servidor
- Atuadores adicionais podem ser integrados via novas portas TCP
- O gateway pode ser replicado para balanceamento de carga

O desacoplamento entre componentes facilita a expansão do sistema.

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
# Exemplo:
cd ~/Sua_Pasta/TEC502---Redes-e-Conectividade-PBL-01-/docker

# 2. Exporte o IP da Máquina B (onde estão os atuadores)
# Exemplo:
export EDGE_HOST_IP=172.16.103.5

# 3. Suba os containers
docker compose -f docker-compose-server.yml up --build
```

### Máquina B — Sensores e Atuadores

```bash
# 1. Entre na pasta docker do projeto
cd ~/Sua_Pasta/TEC502---Redes-e-Conectividade-PBL-01-/docker

# 2. Exporte o IP da Máquina A (onde está o server/gateway)
# exemplo:
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
