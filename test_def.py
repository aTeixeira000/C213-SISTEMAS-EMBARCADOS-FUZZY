import numpy as np
import skfuzzy as fuzz
from skfuzzy import control as ctrl
import matplotlib.pyplot as plt
import paho.mqtt.client as mqtt
import time
import json
import threading

# =====================================================================
# 0. CONFIGURAÇÃO E VARIÁVEIS GLOBAIS
# =====================================================================
mqttBroker = "test.mosquitto.org"
TOPIC_ESTADO = "c213/crac/estado"
TOPIC_SP = "c213/crac/setpoint"
TOPIC_COMANDO = "c213/crac/comando" # Tópico para comandos (iniciar/parar/limpar)
TOPIC_INJECAO = "c213/crac/injecao" # Novo tópico

# Variáveis para a injeção manual. Se True, a simulação usa 'erro_inj' em vez de 'erroatual'.
injecao_ativa = False 
erro_inj = 0.0
deltaErro_inj = 0.0
text_inj = 25.0
carga_inj = 40.0

# Variáveis de Estado (Simulação e Sistema)
sp = 25 # Setpoint inicial
tempatual = 25 # Temperatura inicial (movemos para o topo para facilitar o reset)
qest_atual = 40 # Carga térmica fixa
text_atual = 25 # Temperatura externa fixa
erroatual = tempatual - sp # Inicializa o erro
erroanterior = erroatual

# Variáveis de Controle da Simulação
simulacao_ativa = False # Estado inicial: Parado
reiniciar_simulacao = False

# Variável para controlar o ciclo de 24h
simulacao_24h_ativa = False

# --- ADICIONE ESTAS FUNÇÕES NO TOPO DO CÓDIGO FUZZY (APÓS AS VARIÁVEIS GLOBAIS) ---

def perturba_text_24h(iteracao):
    # Simula uma onda senoidal (ciclo de 24 horas)
    tempo_em_horas = iteracao * (24 / 288) 
    # Modelo T_ext: Média de 25°C, Amplitude de 10°C.
    return 25 + 10 * np.sin((tempo_em_horas - 8) * np.pi / 12)

def perturba_carga_24h(iteracao):
    # Simula a Carga Térmica com degraus (Alta durante o dia)
    tempo_em_horas = iteracao * (24 / 288)
    
    if 8 <= tempo_em_horas < 18:
        # Horário comercial/pico de uso: Carga Alta (90%)
        return 90
    else:
        # Noite/Madrugada: Carga Baixa (30%)
        return 30

# =====================================================================
# 1. FUNÇÕES FUZZY (FPs, REGRAS E SISTEMAS)
# =====================================================================
# --- VARIÁVEIS E FUNÇÕES DE PERTINÊNCIA ---
errotemp = ctrl.Antecedent(np.arange(-16, 16.5, 0.5), 'errotemp')
varerrotemp = ctrl.Antecedent(np.arange(-2, 2.05, 0.05), 'varerrotemp')
text = ctrl.Antecedent(np.arange(10, 41, 1), 'text')
cargatermica = ctrl.Antecedent(np.arange(0, 101, 1), 'cargatermica')
potencia_base = ctrl.Consequent(np.arange(0, 100.2, 0.2), 'potencia_base')
ajuste_potencia = ctrl.Consequent(np.arange(-20, 20.5, 0.5), 'ajuste_potencia')

# Erro (errotemp)
errotemp['MN'] = fuzz.trapmf(errotemp.universe, [-16, -16, -5, -2])
errotemp['PN'] = fuzz.trimf(errotemp.universe, [-5, -2, 0])
errotemp['ZE'] = fuzz.trimf(errotemp.universe, [-1, 0, 1])
errotemp['PP'] = fuzz.trimf(errotemp.universe, [0, 2, 5])
errotemp['MP'] = fuzz.trapmf(errotemp.universe, [2, 5, 16, 16])

errotemp.view()
#plt.show()

# Delta Erro (varerrotemp)
varerrotemp['MN'] = fuzz.trapmf(varerrotemp.universe, [-2, -2, -1.5, -1])
varerrotemp['PN'] = fuzz.trimf(varerrotemp.universe, [-1.5, -1, 0])
varerrotemp['ZE'] = fuzz.trimf(varerrotemp.universe, [-0.5, 0, 0.5])
varerrotemp['PP'] = fuzz.trimf(varerrotemp.universe, [0, 1, 1.5])
varerrotemp['MP'] = fuzz.trapmf(varerrotemp.universe, [1, 1.5, 2, 2])

varerrotemp.view()
plt.show()

# Potência base
potencia_base['MB'] = fuzz.trimf(potencia_base.universe, [0, 0, 25])
potencia_base['B']  = fuzz.trimf(potencia_base.universe, [0, 25, 50])
potencia_base['M']  = fuzz.trimf(potencia_base.universe, [25, 50, 75])
potencia_base['A']  = fuzz.trimf(potencia_base.universe, [50, 75, 100])
potencia_base['MA'] = fuzz.trimf(potencia_base.universe, [75, 100, 100])

#potencia_base.view()
#plt.show()

# Temperatura externa
text['Fria']   = fuzz.trapmf(text.universe, [10, 10, 18, 22])
text['Media']  = fuzz.trimf(text.universe, [20, 25, 30])
text['Quente'] = fuzz.trapmf(text.universe, [28, 32, 40, 40])

# Carga térmica
cargatermica['Baixa'] = fuzz.trapmf(cargatermica.universe, [0, 0, 25, 40])
cargatermica['Media'] = fuzz.trimf(cargatermica.universe, [30, 40, 70])
cargatermica['Alta']  = fuzz.trapmf(cargatermica.universe, [60, 80, 100, 100])

#cargatermica.view()
#plt.show()

# Ajuste de potência (delta P)
ajuste_potencia['MN'] = fuzz.trapmf(ajuste_potencia.universe, [-20, -20, -10, -5])
ajuste_potencia['N']  = fuzz.trimf(ajuste_potencia.universe, [-10, -5, 0])
ajuste_potencia['ZE'] = fuzz.trimf(ajuste_potencia.universe, [-5, 0, 5])
ajuste_potencia['P']  = fuzz.trimf(ajuste_potencia.universe, [0, 5, 10])
ajuste_potencia['MP'] = fuzz.trapmf(ajuste_potencia.universe, [5, 10, 20, 20])

#ajuste_potencia.view()
#plt.show()

# --- REGRAS E CONTROLADORES ---
Rule = ctrl.Rule
# === 2. SUBSISTEMA A: NÚCLEO PI-LIKE (25 REGRAS) ===
# As regras devem ser adaptadas para usar potencia_base
regra_a1 = Rule(errotemp['MN'] & varerrotemp['MN'], potencia_base['MB'])
regra_a2 = Rule(errotemp['PN'] & varerrotemp['MN'], potencia_base['B'])
regra_a3 = Rule(errotemp['ZE'] & varerrotemp['MN'], potencia_base['A'])
regra_a4 = Rule(errotemp['PP'] & varerrotemp['MN'], potencia_base['M'])
regra_a5 = Rule(errotemp['MP'] & varerrotemp['MN'], potencia_base['M'])
regra_a6 = Rule(errotemp['MN'] & varerrotemp['PN'], potencia_base['MB'])
regra_a7 = Rule(errotemp['PN'] & varerrotemp['PN'], potencia_base['M'])
regra_a8 = Rule(errotemp['ZE'] & varerrotemp['PN'], potencia_base['A'])
regra_a9 = Rule(errotemp['PP'] & varerrotemp['PN'], potencia_base['B'])
regra_a10 = Rule(errotemp['MP'] & varerrotemp['PN'], potencia_base['B'])
regra_a11 = Rule(errotemp['MN'] & varerrotemp['ZE'], potencia_base['B'])
regra_a12 = Rule(errotemp['PN'] & varerrotemp['ZE'], potencia_base['A'])
regra_a13 = Rule(errotemp['ZE'] & varerrotemp['ZE'], potencia_base['M']) # Ponto de equilíbrio
regra_a14 = Rule(errotemp['PP'] & varerrotemp['ZE'], potencia_base['B'])
regra_a15 = Rule(errotemp['MP'] & varerrotemp['ZE'], potencia_base['MB'])
regra_a16 = Rule(errotemp['MN'] & varerrotemp['PP'], potencia_base['M'])
regra_a17 = Rule(errotemp['PN'] & varerrotemp['PP'], potencia_base['A'])
regra_a18 = Rule(errotemp['ZE'] & varerrotemp['PP'], potencia_base['M'])
regra_a19 = Rule(errotemp['PP'] & varerrotemp['PP'], potencia_base['B'])
regra_a20 = Rule(errotemp['MP'] & varerrotemp['PP'], potencia_base['MB'])
regra_a21 = Rule(errotemp['MN'] & varerrotemp['MP'], potencia_base['M'])
regra_a22 = Rule(errotemp['PN'] & varerrotemp['MP'], potencia_base['M'])
regra_a23 = Rule(errotemp['ZE'] & varerrotemp['MP'], potencia_base['B'])
regra_a24 = Rule(errotemp['PP'] & varerrotemp['MP'], potencia_base['MB'])
regra_a25 = Rule(errotemp['MP'] & varerrotemp['MP'], potencia_base['MB'])


# Sistema de Controle A
nucleo_ctrl = ctrl.ControlSystem([
    regra_a1, regra_a2, regra_a3, regra_a4, regra_a5,
    regra_a6, regra_a7, regra_a8, regra_a9, regra_a10,
    regra_a11, regra_a12, regra_a13, regra_a14, regra_a15,
    regra_a16, regra_a17, regra_a18, regra_a19, regra_a20,
    regra_a21, regra_a22, regra_a23, regra_a24, regra_a25
])
simulacao_nucleo = ctrl.ControlSystemSimulation(nucleo_ctrl)


# === 3. SUBSISTEMA B: COMPENSAÇÃO (9 REGRAS) ===
# As regras usam text e cargatermica para definir ajuste_potencia
regra_c1 = Rule(text['Fria'] & cargatermica['Baixa'], ajuste_potencia['MN'])
regra_c2 = Rule(text['Media'] & cargatermica['Baixa'], ajuste_potencia['N'])
regra_c3 = Rule(text['Quente'] & cargatermica['Baixa'], ajuste_potencia['ZE'])

regra_c4 = Rule(text['Fria'] & cargatermica['Media'], ajuste_potencia['N'])
regra_c5 = Rule(text['Media'] & cargatermica['Media'], ajuste_potencia['ZE'])
regra_c6 = Rule(text['Quente'] & cargatermica['Media'], ajuste_potencia['P'])

regra_c7 = Rule(text['Fria'] & cargatermica['Alta'], ajuste_potencia['ZE'])
regra_c8 = Rule(text['Media'] & cargatermica['Alta'], ajuste_potencia['P'])
regra_c9 = Rule(text['Quente'] & cargatermica['Alta'], ajuste_potencia['MP'])


# Sistema de Controle B
compensacao_ctrl = ctrl.ControlSystem([
    regra_c1, regra_c2, regra_c3, regra_c4, regra_c5, 
    regra_c6, regra_c7, regra_c8, regra_c9
])
simulacao_compensacao = ctrl.ControlSystemSimulation(compensacao_ctrl)

# ... (Seu código inicial, incluindo definições de FPs e Regras A e B) ...

# =====================================================================
# 2. FUNÇÕES MQTT
# =====================================================================

# Adicionar flag global para monitorar a conexão
mqtt_connected = False 

def on_connect(client, userdata, flags, rc):
    global mqtt_connected
    if rc == 0:
        mqtt_connected = True
        print("MQTT conectado, rc = 0. Assinando tópicos...")
        client.subscribe([(TOPIC_SP, 0), (TOPIC_COMANDO, 0), (TOPIC_INJECAO, 0)]) # Assina SP e COMANDO
        print(f"Assinado nos tópicos: {TOPIC_SP}, {TOPIC_COMANDO} e {TOPIC_INJECAO}")
    else:
        print(f"Falha na conexão MQTT, código {rc}")

def resetar_estado():
    global tempatual, erroatual, erroanterior, reiniciar_simulacao
    
    tempatual = 25.0
    erroatual = tempatual - sp
    erroanterior = erroatual
    reiniciar_simulacao = False
    
    # Publicar o payload com a flag de reset para o dashboard limpar o gráfico
    estado_reset = {
        "temperatura": tempatual, "erro": 0.0, "varErro": 0.0,
        "potencia": 0.0, "setpoint": sp, 
        "simulacao_rodando": False, # Estado final de parada
        "reset": True # CHAVE CRUCIAL PARA LIMPEZA NO FRONT-END
    }
    client.publish(TOPIC_ESTADO, json.dumps(estado_reset))
    print("\n--- Estado da Simulação RESETADO ---\n")

def on_message(client, userdata, msg):
    global sp, simulacao_ativa, reiniciar_simulacao, injecao_ativa, erro_inj, deltaErro_inj, text_inj, carga_inj, simulacao_24h_ativa
    
    try:
        payload = msg.payload.decode("utf-8")
        data = json.loads(payload)
        
        if msg.topic == TOPIC_SP:
            novo_sp = int(data.get("setpoint"))
            if novo_sp in (16, 22, 25, 32):
                sp = novo_sp
                print(f"[MQTT] Setpoint atualizado para {sp}°C")
            
        elif msg.topic == TOPIC_COMANDO:
            comando = data.get("comando")
            
            if comando == "iniciar":
                simulacao_ativa = True
                if reiniciar_simulacao: resetar_estado() # Começa limpo, se pedido
                
            elif comando == "parar":
                simulacao_ativa = False
                
            elif comando == "limpar_grafico":
                reiniciar_simulacao = True # Sinaliza reset no próximo loop ativo

            elif comando == "iniciar_24h": # <--- NOVO COMANDO AQUI
                simulacao_24h_ativa = True
                print("[MQTT] Simulação de 24h solicitada.")
        
        if msg.topic == TOPIC_INJECAO:
            try:
                data = json.loads(msg.payload.decode("utf-8"))
            
                # Atualiza as variáveis de injeção
                erro_inj = float(data.get("erro"))
                deltaErro_inj = float(data.get("deltaErro"))
                text_inj = float(data.get("text"))
                carga_inj = float(data.get("carga"))
            
                # Ativa o modo de injeção
                injecao_ativa = True
            
                # Parar a simulação é recomendado, pois a injeção é um teste estático.
                simulacao_ativa = False 
            
                print("[MQTT] DADOS INJETADOS. Simulação pausada.")
            except Exception as e:
                print(f"Erro ao processar injeção MQTT: {e}")
                
    except Exception as e:
        print(f"Erro ao processar mensagem MQTT: {e}")
    
# Inicializa e começa o loop MQTT
client = mqtt.Client(client_id="c213_fuzzy_pubsub")
client.on_connect = on_connect
client.on_message = on_message
client.connect(mqttBroker, 1883, 60)
client.loop_start() 

# ⚠️ LOOP DE CHECAGEM: Garante que a thread MQTT se conecte antes de prosseguir
print("Aguardando conexão MQTT...")
while not mqtt_connected:
    time.sleep(0.1)

# =====================================================================
# 3. LAÇO DE SIMULAÇÃO PRINCIPAL
# =====================================================================

# Limites para saturação
ERRO_MAX = 16.5
VARERRO_MAX = 2.05

print(f"Sistema Fuzzy Iniciado. SP={sp}°C. Aguardando comando INICIAR via MQTT...")

# =====================================================================
# 4. FUNÇÃO DE SIMULAÇÃO DE 24H (BLOCO ÚNICO)
# =====================================================================

def executar_simulacao_24h():
    global tempatual, erroatual, erroanterior, simulacao_24h_ativa
    
    MAX_ITERACOES = 288
    iteracao = 0 
    
    print(f"\n--- INICIANDO SIMULAÇÃO DE 24H (Ciclo Fechado) ---")
    
    # ⚠️ RESET INICIAL OBRIGATÓRIO PARA 24H
    resetar_estado() 
    tempatual = 25.0 

    while iteracao < MAX_ITERACOES:
        
        # O ciclo de 24h é sempre um cálculo dinâmico, sem injeção manual.
        injecao_ativa = False
        
        # 1. ATUALIZAÇÃO DAS PERTURBAÇÕES
        text_calc = perturba_text_24h(iteracao)
        carga_calc = perturba_carga_24h(iteracao)
        
        # 2. CÁLCULO DE ERRO
        erro_calc = tempatual - sp
        varerroTemp_calc = erroatual - erroanterior
        
        # --- CÁLCULO DE FLUXO (COPIADO DO while True) ---
        
        # Atualiza o erroanterior (necessário para a próxima iteração dinâmica)
        erroanterior = erroatual # Mantemos a variável para o modo dinâmico
        erroatual = erro_calc # Atualiza o erroatual para o print
        
        # Saturação das entradas (APLICADA ÀS VARIÁVEIS DE CÁLCULO)
        erro_input = np.clip(erro_calc, -ERRO_MAX, ERRO_MAX)
        varerro_input = np.clip(varerroTemp_calc, -VARERRO_MAX, VARERRO_MAX)

        # --- 3.3. GANHO KP CONDICIONAL (Mapa Otimizado) ---
        if sp == 16: Kp = 0.75
        elif sp == 22: Kp = 0.45
        elif sp == 25: Kp = 0.45
        elif sp == 32: Kp = 0.3
        else: Kp = 0.35

        # --- 3.4. CÁLCULO FUZZY ---
        simulacao_nucleo.input['errotemp'] = erro_input
        simulacao_nucleo.input['varerrotemp'] = varerro_input
        simulacao_nucleo.compute()

        if 'potencia_base' in simulacao_nucleo.output:
            P_base = simulacao_nucleo.output['potencia_base']
        else:
            P_base = 100.0
        simulacao_nucleo.reset()

        simulacao_compensacao.input['text'] = text_calc 
        simulacao_compensacao.input['cargatermica'] = carga_calc
        simulacao_compensacao.compute()
        Delta_P = simulacao_compensacao.output['ajuste_potencia']
        simulacao_compensacao.reset()

        # --- 3.5. INTEGRAÇÃO E CLIPPING ---
        P_base_atenuada = P_base * Kp
        P_final = P_base_atenuada + Delta_P
        P_crac_final = np.clip(P_final, 0, 100)
        
        # --- 3.6. MODELO TÉRMICO ---
        T_anterior = tempatual
        tempatual = (0.9 * T_anterior - 0.08 * P_crac_final + 0.05 * carga_calc + 0.02 * text_calc + 0.35)

        # PUBLICAÇÃO DO ESTADO
        estado = {
            "temperatura": round(float(tempatual), 2),
            "erro": round(float(erroatual), 2),
            "varErro": round(float(varerroTemp_calc), 2),
            "potencia": round(float(P_crac_final), 2),
            "setpoint": sp,
            "qest": round(float(carga_calc), 1), # Publica o valor da perturbação
            "text": round(float(text_calc), 1),  # Publica o valor da perturbação
            "simulacao_rodando": True, # A simulação está rodando no modo 24h
            "injecao_ativa": False,
             "tempo_horas": round(iteracao * (24 / MAX_ITERACOES), 2)
        }
        client.publish(TOPIC_ESTADO, json.dumps(estado))
        
        time.sleep(0.05) 
        iteracao += 1
    
    print("\n--- SIMULAÇÃO DE 24H CONCLUÍDA! ---")
    simulacao_24h_ativa = False # Desliga a flag no final

while True:

    if simulacao_24h_ativa:
        executar_simulacao_24h()
        # Após a simulação de 24h, ele volta a ser uma simulação parada.
    
    # 1. VERIFICAÇÃO DE CONTROLE E RESET (PRIORIDADE MÁXIMA)
    if reiniciar_simulacao:
        resetar_estado()
        injecao_ativa = False # Desativa injeção após reset
        simulacao_ativa = False # Garante que o estado seja PAUSADO após o reset.
    
    # 2. CONTROLE DO ESTADO ATIVO/PARADO
    if not simulacao_ativa:
        # Se a simulação está parada, publica o estado de PAUSA (apenas a temperatura atual)
        # e dorme significativamente para liberar CPU para a thread MQTT (on_message).
        
        estado = {
            "temperatura": round(float(tempatual), 2),
            "erro": 0.0, "varErro": 0.0,
            "potencia": 0.0, "setpoint": sp,
            "qest": qest_atual, "text": text_atual,
            "simulacao_rodando": simulacao_ativa,
        }
        client.publish(TOPIC_ESTADO, json.dumps(estado))
        
        time.sleep(0.5) 
        continue # Retorna ao topo do loop

    # --- 3.2. CÁLCULO DE ERRO E SATURAÇÃO ---
    # Determinar qual erro, delta erro, temperatura e carga usar (CALC = CÁLCULO/INJEÇÃO)
    if injecao_ativa:
        erro_calc = erro_inj
        varerroTemp_calc = deltaErro_inj
        text_calc = text_inj
        carga_calc = carga_inj
    else:
        # Usa o cálculo dinâmico da simulação
        erro_calc = tempatual - sp
        varerroTemp_calc = erroatual - erroanterior
        text_calc = text_atual # (valor fixo original)
        carga_calc = qest_atual # (valor fixo original)
    
    # Atualiza o erroanterior (necessário para a próxima iteração dinâmica)
    erroanterior = erroatual # Mantemos a variável para o modo dinâmico
    erroatual = erro_calc # Atualiza o erroatual para o print
    
    # Saturação das entradas (APLICADA ÀS VARIÁVEIS DE CÁLCULO)
    erro_input = np.clip(erro_calc, -ERRO_MAX, ERRO_MAX)
    varerro_input = np.clip(varerroTemp_calc, -VARERRO_MAX, VARERRO_MAX)

    # --- 3.3. GANHO KP CONDICIONAL (Mapa Otimizado) ---
    if sp == 16:
        Kp = 0.56
    elif sp == 22:
        Kp = 0.28
    elif sp == 25:
        Kp = 0.09
    elif sp == 32:
        Kp = 0.01
    else:
        Kp = 0.35

    # --- 3.4. CÁLCULO FUZZY ---
    simulacao_nucleo.input['errotemp'] = erro_input
    simulacao_nucleo.input['varerrotemp'] = varerro_input
    simulacao_nucleo.compute()

    if 'potencia_base' in simulacao_nucleo.output:
        P_base = simulacao_nucleo.output['potencia_base']
    else:
        P_base = 100.0
    simulacao_nucleo.reset()

    simulacao_compensacao.input['text'] = text_calc 
    simulacao_compensacao.input['cargatermica'] = carga_calc
    simulacao_compensacao.compute()
    Delta_P = simulacao_compensacao.output['ajuste_potencia']
    simulacao_compensacao.reset()

    # --- 3.5. INTEGRAÇÃO E CLIPPING ---
    P_base_atenuada = P_base * Kp
    P_final = P_base_atenuada + Delta_P
    P_crac_final = np.clip(P_final, 0, 100)

    # --- 3.6. MODELO TÉRMICO ---
    # O modelo térmico só é atualizado se a simulação NÃO estiver em modo de injeção estática.
    if not injecao_ativa:
        T_anterior = tempatual
        tempatual = (
            0.9 * T_anterior
            - 0.08 * P_crac_final
            + 0.05 * carga_calc # Usando carga injetada/calculada
            + 0.02 * text_calc  # Usando temperatura injetada/calculada
            + 0.35
        )
    
    # --- 3.7. PUBLICAÇÃO ---
    estado = {
        "temperatura": round(float(tempatual), 2),
        "erro": round(float(erroatual), 2),
        "varErro": round(float(varerroTemp_calc), 2),
        "potencia": round(float(P_crac_final), 2),
        "setpoint": sp,
        "qest": round(float(carga_calc), 1),
        "text": round(float(text_calc), 1),
        "simulacao_rodando": simulacao_ativa,
        "injecao_ativa": injecao_ativa
    }
    client.publish(TOPIC_ESTADO, json.dumps(estado))

    # --- 3.8. DEBUG E INTERVALO ---
    # print(f"SP: {sp:2d} | T: {tempatual:.2f} °C | Erro: {erroatual:.2f} | Potência: {P_crac_final:.2f}")
    time.sleep(0.05)