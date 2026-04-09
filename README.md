---

# 🚀 Sistema IoT-Industrial 

## 📌 Visão Geral

Este projeto apresenta a implementação de um sistema distribuído de monitoramento IoT com foco em **baixo acoplamento entre os componentes**, utilizando exclusivamente protocolos nativos da Internet. A solução foi projetada para simular um ambiente realista de monitoramento industrial, onde múltiplos dispositivos geram dados continuamente e ações precisam ser tomadas em tempo real.

O sistema é composto por sensores, atuadores, um gateway intermediário, um servidor central e uma interface cliente. Cada um desses elementos possui responsabilidades bem definidas e se comunica por meio de diferentes protocolos de rede, escolhidos de acordo com a natureza do dado transmitido.

Do ponto de vista técnico, o projeto busca demonstrar conceitos fundamentais de sistemas distribuídos, como concorrência, desacoplamento, tolerância a falhas e escalabilidade. Além disso, o uso de containers permite simular múltiplos dispositivos operando simultaneamente, aproximando o comportamento do sistema de um cenário real de IoT.

---

# 🧠 1. Arquitetura do Sistema

A arquitetura adotada segue um modelo em camadas, onde cada componente desempenha um papel específico e independente. Essa separação permite que o sistema seja facilmente expandido ou modificado sem impacto direto nos demais elementos.

Os sensores são responsáveis por gerar dados continuamente, simulando medições de temperatura e umidade. Esses dados são enviados ao gateway, que atua como uma camada intermediária responsável por transformar e encaminhar as informações para o servidor central. O servidor, por sua vez, processa os dados recebidos e decide se alguma ação deve ser executada, como acionar um atuador. Por fim, os atuadores executam comandos recebidos e o cliente permite a interação do usuário com o sistema.

```text
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
```

Essa arquitetura evidencia claramente o uso de um middleware (gateway), cuja função principal é desacoplar os produtores de dados (sensores) dos consumidores (servidor). Isso significa que sensores não precisam conhecer a existência do servidor, o que reduz dependências diretas e aumenta a flexibilidade do sistema.

---

# 🌐 2. Comunicação entre Componentes

A comunicação entre os elementos do sistema foi cuidadosamente projetada para utilizar diferentes protocolos de acordo com os requisitos de cada tipo de interação.

Os sensores enviam dados ao gateway utilizando UDP. Essa escolha se deve ao fato de que a telemetria é um fluxo contínuo de dados onde pequenas perdas não comprometem o funcionamento geral do sistema. O UDP permite uma comunicação leve e rápida, sem overhead de conexão.

No código, isso é implementado com sockets do tipo `SOCK_DGRAM`, onde o sensor simplesmente envia pacotes sem necessidade de estabelecer conexão:

```python
sock.sendto(json.dumps(dado).encode(), (gateway_ip, porta))
```

O gateway, ao receber esses dados, realiza uma conversão de protocolo, encaminhando as informações para o servidor via HTTP. Essa escolha facilita a padronização da comunicação e permite que o servidor seja acessado por diferentes tipos de clientes, incluindo navegadores e aplicações externas.

Já a comunicação entre o servidor e os atuadores utiliza TCP. Nesse caso, a confiabilidade é essencial, pois comandos não podem ser perdidos. O TCP garante entrega, ordem e integridade dos dados, sendo ideal para esse tipo de operação.

---

# 📡 3. Protocolo de Comunicação (API)

O sistema utiliza JSON como formato padrão de troca de dados, garantindo interoperabilidade entre diferentes componentes e linguagens.

Quando um sensor envia dados, ele utiliza uma estrutura simples contendo identificador, tipo e valor. Esse formato é interpretado pelo gateway e posteriormente encaminhado ao servidor via uma requisição HTTP POST.

No servidor, esses dados são recebidos e processados. O código responsável por isso geralmente extrai os campos do JSON e aplica regras de negócio, como verificar limites de temperatura.

Por exemplo, ao receber um valor elevado, o servidor pode gerar um comando para um atuador:

```python
if dado["valor"] > 30:
    acionar_atuador("ALARME")
```

Esse comando é então enviado via TCP para o atuador, que permanece escutando continuamente por novas instruções.

Além disso, o servidor expõe endpoints HTTP que permitem ao cliente consultar o estado atual do sistema, visualizar histórico e enviar comandos manualmente.

---

# 📦 4. Encapsulamento e Tratamento de Dados

O uso de JSON como formato de encapsulamento permite que os dados sejam facilmente manipulados e compreendidos. No código, a conversão entre string e estrutura de dados é feita utilizando bibliotecas padrão, como `json.loads()` e `json.dumps()`.

Para garantir robustez, o sistema implementa tratamento de erros ao receber mensagens. Caso um JSON inválido seja recebido, ele é simplesmente descartado, evitando que o sistema seja comprometido por dados corrompidos.

```python
try:
    data = json.loads(msg)
except:
    return
```

Esse tipo de abordagem é comum em sistemas distribuídos, onde a tolerância a falhas é mais importante do que a precisão absoluta de cada mensagem individual.

---

# ⚙️ 5. Concorrência

A concorrência é um dos pilares do sistema, permitindo que múltiplos eventos sejam processados simultaneamente sem bloqueios.

No gateway, a concorrência é implementada utilizando uma combinação de fila e múltiplas threads. Uma thread principal é responsável por receber dados via UDP e colocá-los em uma fila compartilhada. Em paralelo, várias threads trabalhadoras consomem essa fila e enviam requisições HTTP ao servidor.

Esse modelo evita que o recebimento de dados seja bloqueado por operações mais lentas, como chamadas HTTP.

No servidor, a concorrência também está presente. Enquanto uma thread gerencia as requisições HTTP, outra pode estar lidando com conexões TCP dos atuadores. Além disso, workers podem ser utilizados para tarefas como processamento de dados ou armazenamento.

No cliente, a separação entre thread de interface e thread de coleta de dados garante que a interface permaneça responsiva mesmo durante atualizações constantes.

```text
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
           | Thread HTTP      |
           | Thread TCP       |
           | Workers          |
           +--------+---------+
                    |
                    ↓
           +------------------+
           |  ATUADORES (TCP) |
           +------------------+
```

---

# 🚀 6. Qualidade de Serviço

Para garantir estabilidade, o sistema implementa diversas estratégias de controle.

O uso de filas com tamanho limitado impede que o gateway seja sobrecarregado em cenários de alta taxa de dados. Caso a fila atinja seu limite, novos dados podem ser descartados, priorizando a continuidade do sistema.

Além disso, timeouts são configurados em sockets para evitar bloqueios indefinidos. Em caso de falha no envio de dados, mecanismos de retry podem ser utilizados para tentar novamente a operação.

Essas estratégias são fundamentais em sistemas distribuídos reais, onde falhas são esperadas e devem ser tratadas de forma controlada.

---

# 🖥️ 7. Interação com o Usuário

A aplicação cliente permite ao usuário monitorar o estado do sistema em tempo real, visualizar dados históricos e enviar comandos manualmente.

Essa interação é feita por meio de requisições HTTP ao servidor, que responde com dados atualizados. A separação entre cliente e servidor permite que diferentes interfaces sejam desenvolvidas, como aplicações web ou mobile.

---

# 🛡️ 8. Confiabilidade

O sistema foi projetado para continuar operando mesmo diante de falhas parciais.

Sensores podem ficar offline sem impactar o restante do sistema. O gateway pode descartar mensagens caso esteja sobrecarregado, evitando colapso. O servidor utiliza filas para lidar com picos de processamento, e atuadores desconectados são tratados por meio de exceções.

Essa abordagem segue o princípio de sistemas distribuídos resilientes, onde falhas são tratadas como parte do funcionamento normal.

---

# 🧪 9. Testes

Os testes foram realizados simulando múltiplos sensores enviando dados simultaneamente em alta frequência. Isso permitiu validar o comportamento concorrente do sistema e sua capacidade de lidar com cargas elevadas.

Os resultados demonstraram que o sistema mantém estabilidade e não apresenta bloqueios, confirmando a eficácia das estratégias adotadas.

---

# 🐳 10. Execução com Docker

O uso de Docker permite a execução isolada de cada componente, simulando um ambiente distribuído real.

Cada sensor, atuador, gateway e servidor pode ser executado como um container independente, possibilitando a criação de múltiplas instâncias e testes em larga escala.

Essa abordagem facilita a replicação do ambiente e a validação do sistema em diferentes cenários.

---

# 📊 11. Exemplo de Dados

```json
{
  "id": "sensor_temp_3",
  "tipo": "temperatura",
  "valor": 22.42,
  "horario": "2026-04-08 17:28:49"
}
```

Esse exemplo representa uma leitura real gerada por um sensor e processada pelo sistema.

---

# 🎯 Conclusão

O sistema desenvolvido atende plenamente aos objetivos propostos, demonstrando na prática conceitos essenciais de sistemas distribuídos. A arquitetura desacoplada, aliada ao uso adequado de protocolos e mecanismos de concorrência, resulta em uma solução robusta, escalável e tolerante a falhas.

Além disso, a presença do gateway como middleware evidencia uma abordagem moderna de integração, permitindo maior flexibilidade e facilidade de expansão.

---

# 📚 Referências

* TANENBAUM, Andrew S.; WETHERALL, David. Computer Networks. 5ª ed. Pearson, 2011.
* STEVENS, W. Richard. UNIX Network Programming, Volume 1: The Sockets Networking API. Addison-Wesley, 2003.
* GOETZ, Brian et al. Java Concurrency in Practice. Addison-Wesley, 2006.

---
