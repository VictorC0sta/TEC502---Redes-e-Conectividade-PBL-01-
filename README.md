# 🚀 Sistema IoT Distribuído — Rota das Coisas

## 📌 Visão Geral

Este projeto implementa um sistema distribuído de monitoramento IoT com **baixo acoplamento**, baseado em sensores, atuadores e um middleware intermediário (gateway), utilizando apenas protocolos nativos da Internet.

A solução simula um ambiente industrial com:

- Sensores de temperatura e umidade
- Atuadores (alarme e resfriamento)
- Servidor central
- Gateway de integração
- Interface cliente gráfica

O sistema foi projetado com foco em:

- Concorrência
- Desacoplamento
- Escalabilidade
- Comunicação distribuída

---

# 🧠 1. Arquitetura do Sistema

## 🔷 Componentes

| Componente | Função |
|----------|--------|
| Sensores | Geram dados continuamente (UDP) |
| Gateway | Ponte entre UDP e HTTP |
| Servidor | Processamento central |
| Atuadores | Executam ações (TCP) |
| Cliente | Interface de monitoramento |

---

## 🔷 Diagrama 1 — Arquitetura Geral


[SENSORES]
|
| UDP
↓
[GATEWAY]
|
| HTTP
↓
[SERVER]
|
| TCP
↓
[ATUADORES]

[CLIENTE] ← HTTP → [SERVER]


---

## 🔷 Desacoplamento

- Sensores não conhecem o servidor
- Servidor não conhece sensores diretamente
- Gateway atua como middleware

✔ Reduz acoplamento  
✔ Aumenta escalabilidade  

---

# 🌐 2. Comunicação

## 🔷 Protocolos utilizados

| Comunicação | Protocolo | Uso |
|------------|----------|-----|
| Sensor → Gateway | UDP | Telemetria |
| Gateway → Server | HTTP | Integração |
| Server → Atuadores | TCP | Controle |
| Cliente → Server | HTTP | Interface |

---

## 🔷 Justificativa

- UDP: rápido e leve
- HTTP: padronização
- TCP: confiável para comandos críticos

---

## 🔷 Diagrama 2 — Fluxo de Dados


Sensor
↓ UDP
Gateway
↓ HTTP
Server
↓ TCP
Atuador

Cliente ← HTTP → Server


---

# 📡 3. Protocolo (API Remota)

## 🔷 Formato das mensagens

### Sensor → Gateway

```json
{
  "id": "sensor_temp_1",
  "tipo": "temperatura",
  "valor": 24.5
}
Gateway → Server

POST /sensor

{
  "id": "sensor_temp_1",
  "tipo": "temperatura",
  "valor": 24.5
}
Server → Atuadores
{
  "sensor": "temperatura",
  "nome_sensor": "sensor_temp_1",
  "valor": 35,
  "acao": "ALARME"
}
Endpoints disponíveis
GET /estado
GET /historico
GET /atuadores
POST /ativar/alarme
POST /ativar/resfriamento
📦 4. Encapsulamento
Uso de JSON como padrão
Independente de linguagem
Tratamento de erros:
Erro	Tratamento
JSON inválido	descartado
dados incompletos	ignorados
⚙️ 5. Concorrência
🔷 Gateway
Thread principal → recebe UDP
Pool de threads → envia HTTP
Fila para desacoplamento
🔷 Servidor
Thread UDP
Thread HTTP
Workers de escrita em disco
🔷 Cliente
Thread de coleta
Thread de interface
Buffer de dados
🔷 Diagrama 3 — Modelo de Concorrência
           +------------------+
           |   SENSOR (UDP)   |
           +--------+---------+
                    |
                    ↓
           +------------------+
           |  GATEWAY         |
           |------------------|
           | UDP Listener     |
           | Queue            |
           | Worker Threads   |
           +--------+---------+
                    |
                    ↓
           +------------------+
           |  SERVER          |
           |------------------|
           | Thread UDP       |
           | Thread HTTP      |
           | Workers Disco    |
           +--------+---------+
                    |
                    ↓
           +------------------+
           |  ATUADORES (TCP) |
           +------------------+
🚀 6. Qualidade de Serviço
🔷 Estratégias
Fila limitada
Retry automático
Timeout
Controle de carga
🔷 Tipos de tráfego
Tipo	Tratamento
Telemetria	UDP
Controle	TCP
🖥️ 7. Interação

A aplicação cliente permite:

Monitoramento em tempo real
Visualização de histórico
Controle manual de atuadores
🛡️ 8. Confiabilidade
🔷 Tratamento de falhas
Problema	Solução
Sensor offline	ignorado
Gateway cheio	descarta
Server lento	fila
Atuador offline	exceção
🧪 9. Testes
Execução com múltiplos sensores
Alta frequência de dados
Testes simultâneos

✔ Validação de concorrência
✔ Teste de estabilidade

🐳 10. Emulação com Docker
🔷 Componentes
Edge
sensores
atuadores
Core
server
gateway
🔷 Benefícios
Isolamento
Escalabilidade
Teste distribuído
📊 11. Exemplo de Dados
{
  "id": "sensor_temp_3",
  "tipo": "temperatura",
  "valor": 22.42,
  "horario": "2026-04-08 17:28:49"
}
🎯 Conclusão

O sistema atende aos requisitos do problema:

Arquitetura desacoplada
Comunicação distribuída
Concorrência eficiente
Tolerância a falhas
Execução em ambiente distribuído
📚 Referências
TANENBAUM, Andrew S.; WETHERALL, David. Computer Networks. 5ª ed. Pearson, 2011.
STEVENS, W. Richard. UNIX Network Programming, Volume 1: The Sockets Networking API. Addison-Wesley, 2003.
GOETZ, Brian et al. Java Concurrency in Practice. Addison-Wesley, 2006.
