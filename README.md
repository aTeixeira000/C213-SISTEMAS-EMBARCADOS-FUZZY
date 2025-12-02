# Sistema de Controle Fuzzy para Data Center  
Dashboard Web, Simulação Contínua, Injeção de Dados, Alertas Críticos e Monitoramento via MQTT

Este projeto implementa um controlador fuzzy MISO para regular a temperatura de uma sala de dados/Data Center através da atuação do sistema de resfriamento (CRAC).  

O sistema inclui:

- **Simulação contínua** do comportamento térmico da sala.  
- **Controlador fuzzy em dois estágios** (núcleo PI-like + compensação por temperatura externa e carga térmica).  
- **Dashboard Web** em Flask + HTML/JS com gráficos em tempo quase real.  
- **Injeção manual de dados** para debug da inferência fuzzy.  
- **Geração de alertas críticos** quando a temperatura sai da faixa segura.  
- **Comunicação via MQTT** para desacoplamento entre simulador e interface de monitoramento.

---

## Estrutura do Projeto

```text
C213_PROJETO_2/
├── test_def.py           # Núcleo: controlador fuzzy + modelo físico + laço de simulação + MQTT (inclui alertas)
├── dashboard_server.py   # Servidor Flask + cliente MQTT (ponte HTTP ↔ MQTT, inclui rota de alerta)
/├── templates/
│   └── index.html        # Dashboard Web (gráficos, setpoint, comandos, injeção manual e banner de alerta)
├── subscriber.py         # Cliente MQTT simples para debug (terminal)
├── requirements.txt      # Dependências do projeto
└── 2Trabalho.pdf         # Especificação do trabalho (referência)
```

---

## Como Executar

1. **Instale as dependências**

   ```bash
   pip install -r requirements.txt
   ```

   (Opcional, mas recomendado: criar um ambiente virtual antes.)

2. **Inicie o simulador fuzzy**

   Em um terminal:

   ```bash
   python test_def.py
   ```

   Esse script:
   - conecta ao broker MQTT (`test.mosquitto.org`);
   - assina os tópicos de controle (`c213/crac/setpoint`, `c213/crac/comando`, `c213/crac/injecao`);
   - executa o laço de simulação térmica;
   - publica continuamente o estado no tópico `c213/crac/estado`;
   - publica alertas críticos no tópico `datacenter/fuzzy/alert` quando a temperatura sai da faixa segura (18–26 °C).

3. **Inicie o servidor do dashboard**

   Em outro terminal:

   ```bash
   python dashboard_server.py
   ```

   O Flask sobe em `http://localhost:5000`.

4. **Abra o dashboard no navegador**

   - Acesse: `http://localhost:5000`
   - A interface mostra:
     - gráfico de temperatura e setpoint;
     - cartões com temperatura, potência, erro, temperatura externa e carga;
     - botões de setpoint (16, 22, 25, 32 °C);
     - botões de **Iniciar / Parar / Limpar gráfico**;
     - formulário para **injeção manual** de erro, Δerro, Text e carga térmica;
     - um **banner de alerta** que aparece quando o sistema detecta alta ou baixa temperatura e publica em `datacenter/fuzzy/alert`.

5. **(Opcional) Usar o subscriber para debug**

   ```bash
   python subscriber.py
   ```

   Mostra no terminal tudo que é publicado em `c213/crac/estado` (e pode ser adaptado para ler outros tópicos).

---

## 1. Relatório de Design

### 1.1 Justificativa do Design das Funções de Pertinência

O controlador fuzzy utiliza um esquema **MISO (múltiplas entradas, uma saída)** com dois subsistemas:

- **Subsistema A – Núcleo PI-like**
  - Entradas:
    - **Erro de temperatura (errotemp)**: intervalo de −16 a 16 °C  
      Conjuntos: `MN` (Muito Negativo), `PN` (Pouco Negativo), `ZE` (Zero), `PP` (Pouco Positivo), `MP` (Muito Positivo).  
    - **Delta erro (varerrotemp)**: intervalo de −2 a 2 °C  
      Conjuntos: `MN`, `PN`, `ZE`, `PP`, `MP`.  
  - Saída intermediária:
    - **Potência base do CRAC (potencia_base)**: 0 a 100 %  
      Conjuntos: `MB` (Muito Baixa), `B` (Baixa), `M` (Média), `A` (Alta), `MA` (Muito Alta).

- **Subsistema B – Compensação por condições externas**
  - Entradas:
    - **Temperatura externa (text)**: 10 a 40 °C  
      Conjuntos: `Fria`, `Media`, `Quente`.  
    - **Carga térmica (cargatermica)**: 0 a 100 %  
      Conjuntos: `Baixa`, `Media`, `Alta`.  
  - Saída:
    - **Ajuste de potência (ajuste_potencia)**: −20 a 20 %  
      Conjuntos: `MN`, `N`, `ZE`, `P`, `MP`.

As funções de pertinência são majoritariamente **triangulares** e **trapezoidais**, escolhidas por:

- simplicidade de implementação com `scikit-fuzzy`;
- transições suaves entre faixas de operação;
- boa interpretação física em sistemas térmicos (variação gradual de temperatura).

O intervalo das variáveis foi definido com base em:

- faixa típica de operação da sala de dados (em torno de 16–32 °C de setpoint);
- margens realistas para erro de temperatura e sua derivada;
- faixas plausíveis de temperatura externa e carga térmica (0–100%).

### 1.2 Explicação da Base de Regras Desenvolvida

A base fuzzy é dividida em dois conjuntos de regras Mamdani:

#### a) Núcleo PI-like (erro × delta erro → potência base)

- Combina **5 níveis de erro** com **5 níveis de delta erro**, resultando em **25 regras**.
- Exemplos (em linguagem natural):
  - Se o **erro é muito positivo** e o **delta erro é positivo**, então `potencia_base` é **Muito Alta**.  
  - Se o **erro é zero** e o **delta erro é zero**, então `potencia_base` é **Média** (ponto de equilíbrio).  
  - Se o **erro é negativo** (sala fria) e o **delta erro é negativo** (ainda esfriando), então `potencia_base` é **Baixa** ou **Muito Baixa**.

Esse subconjunto de regras faz o papel de um **controlador do tipo PI**:  
responde ao erro atual e à sua variação, aumentando ou reduzindo a potência do CRAC de forma suave.

#### b) Compensação por Text e Carga (temp_ext × carga → ajuste_potencia)

- Regras de alto nível que ajustam a potência base conforme as condições externas:
  - Se **temperatura externa é Quente** e **carga térmica é Alta**, aplicar ajuste **MP** (aumentar bastante a potência).  
  - Se **temperatura externa é Fria** e **carga é Baixa**, aplicar ajuste **MN** ou **N** (reduzir potência).  
  - Situações intermediárias resultam em ajustes `ZE` (nenhuma correção) ou `P`.

Esse bloco funciona como uma camada de **robustez**: corrige a ação principal do controlador quando o ambiente está desfavorável ou muito favorável, sem precisar alterar a base principal.

### 1.3 Estratégia de Controle Implementada

O fluxo de controle em cada iteração é:

1. **Cálculo das entradas efetivas**  
   - Em modo normal, o sistema calcula:
     - erro = temperatura_atual − setpoint  
     - delta erro = erro_atual − erro_anterior  
     - usa `text` e `carga` fixos definidos no simulador.
   - Em modo de **injeção manual**, os valores de erro, delta erro, temperatura externa e carga térmica vêm diretamente do tópico MQTT `c213/crac/injecao`, permitindo debugar a inferência fuzzy com entradas arbitrárias.

2. **Inferência fuzzy em dois estágios**
   - Subsistema A → gera `P_base`.  
   - Subsistema B → gera `Delta_P`.  

3. **Combinação e saturação**

   ```python
   P_base_atenuada = P_base * Kp   # ganho Kp depende do setpoint (16, 22, 25 ou 32 °C)
   P_final = P_base_atenuada + Delta_P
   P_crac_final = np.clip(P_final, 0, 100)
   ```

   O ganho **Kp condicional por setpoint** foi ajustado empiricamente para reduzir oscilações dependendo da temperatura alvo.

4. **Modelo térmico discreto**

   A nova temperatura da sala é calculada a partir da anterior:

   - termo proporcional à temperatura anterior (inércia térmica);
   - termo de remoção de calor proporcional à potência do CRAC;
   - termo de aquecimento devido à carga térmica e à temperatura externa;
   - termo constante representando ganhos/perdas residuais.

   Isso emula a dinâmica de uma sala de dados ao longo do tempo.

5. **Publicação do estado**

   Em cada ciclo, o simulador publica no tópico `c213/crac/estado` um JSON com:

   ```json
   {
     "temperatura": ...,
     "erro": ...,
     "varErro": ...,
     "potencia": ...,
     "setpoint": ...,
     "qest": ...,
     "text": ...,
     "simulacao_rodando": true/false,
     "injecao_ativa": true/false
   }
   ```

6. **Geração de alertas críticos**

   Após atualizar a temperatura, o simulador verifica se o valor está dentro da faixa segura:

   - `TEMP_MIN_SEGURA = 18.0 °C`  
   - `TEMP_MAX_SEGURA = 26.0 °C`

   Se a temperatura exceder esses limites, é publicado um alerta no tópico `datacenter/fuzzy/alert` com informações como:

   ```json
   {
     "tipo": "ALTA_TEMPERATURA" ou "BAIXA_TEMPERATURA",
     "mensagem": "...",
     "temperatura": ...,
     "limite_superior" ou "limite_inferior": ...,
     "setpoint": ...
   }
   ```

---

## 2. Análise de Resultados

> Os pontos abaixo descrevem o comportamento esperado e observado em testes de simulação conduzidos com o modelo implementado.

### 2.1 Testes de Validação

O simulador executa um laço contínuo (passo de ~0,05 s) que representa a operação do Data Center ao longo de um dia. Nos testes foram avaliados cenários com:

- diferentes **valores de setpoint** (16, 22, 25 e 32 °C);
- mudanças bruscas de setpoint durante a simulação;
- alterações na carga térmica e temperatura externa;
- injeção manual de erro/Δerro para verificar a resposta isolada do controlador.

Os resultados mostraram:

- manutenção da temperatura interna próxima ao setpoint após um regime transitório;
- ação coerente do CRAC (aumento de potência quando a sala aquece, redução quando esfria);
- ausência de oscilações instáveis ou comportamento divergente;
- geração de alertas quando a temperatura ultrapassa a faixa considerada segura.

### 2.2 Análise da Resposta em Diferentes Cenários

Foram observados, entre outros, os seguintes contextos:

- **Setpoint baixo (16 °C)** com alta carga térmica  
  → o controlador aumenta a potência do CRAC e a mantém em valores elevados, respeitando o limite de 100%.

- **Setpoint típico (22–25 °C)** com condições externas moderadas  
  → o sistema apresenta boa estabilidade, com pequenas correções de potência conforme variações de carga.

- **Setpoint alto (32 °C)** ou ambiente externo frio  
  → o esforço do CRAC é reduzido, o que seria compatível com estratégias de economia de energia.

O dashboard permite visualizar esses comportamentos em tempo quase real via gráfico de temperatura e setpoint, além de cartões com potência, erro, temperatura externa e carga.  
Quando a temperatura sai da faixa [18, 26] °C, um banner de alerta é apresentado na interface.

### 2.3 Avaliação de Robustez e Estabilidade

O controlador se mantém estável mesmo quando sujeito a:

- variações rápidas de setpoint (por exemplo, mudar de 16 → 25 → 22 °C);
- alterações bruscas de carga térmica e temperatura externa;
- entradas artificiais de erro/Δerro via injeção MQTT.

A saturação da potência em 0–100% e o ajuste Kp por setpoint evitam overshoots excessivos e mantêm o sistema dentro de faixas operacionais seguras para o Data Center.  
A lógica de alerta reforça a supervisão, permitindo identificar rapidamente situações fora da faixa desejada.

---

## 3. Comunicação MQTT

A comunicação MQTT é responsável por desacoplar o **núcleo de simulação fuzzy** da **interface Web** e de outros clientes externos.

Durante a simulação, são utilizados os seguintes tópicos:

- `c213/crac/estado`  
  - Publicado pelo **simulador** (`test_def.py`).  
  - Carrega a telemetria completa: temperatura, erro, Δerro, potência, setpoint, temperatura externa, carga térmica e flags de estado.  
  - É consumido pelo **dashboard Flask** e pode ser lido também pelo `subscriber.py` ou qualquer cliente MQTT externo.

- `c213/crac/setpoint`  
  - Publicado pelo **dashboard** (`dashboard_server.py`) quando o usuário escolhe um novo setpoint no navegador.  
  - Consumido pelo simulador, que atualiza o valor de referência.

- `c213/crac/comando`  
  - Publicado pelo dashboard quando o usuário clica em **Iniciar**, **Parar** ou **Limpar gráfico**.  
  - O simulador interpreta esses comandos para ativar/desativar o laço de simulação ou resetar o estado.

- `c213/crac/injecao`  
  - Publicado pelo dashboard ao enviar entradas manuais.  
  - Permite injetar erro, delta erro, temperatura externa e carga térmica diretamente no controlador para fins de debug da inferência fuzzy.

- `datacenter/fuzzy/alert`  
  - Publicado pelo simulador quando a temperatura interna sai da faixa segura definida (18–26 °C).  
  - Consumido pelo dashboard através do broker MQTT e exposto via rota `/alerta`, permitindo exibir um banner de alerta na interface Web.

### Relação com os tópicos da especificação

Na especificação original do trabalho são mencionados tópicos como:

- `datacenter/fuzzy/temp` – temperatura atual  
- `datacenter/fuzzy/control` – dados de controle  
- `datacenter/fuzzy/alert` – alertas críticos  

No projeto atual:

- `c213/crac/estado` cumpre o papel de **temp + control**, pois reúne temperatura, potência e demais variáveis relevantes.  
- `c213/crac/setpoint`, `c213/crac/comando` e `c213/crac/injecao` detalham os canais de **controle** de forma mais granular.  
- O tópico `datacenter/fuzzy/alert` foi implementado conforme a especificação, sendo utilizado para publicar alertas críticos sempre que a temperatura interna sai da faixa de operação segura.
