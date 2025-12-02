import json
import threading

from flask import Flask, jsonify, render_template, request
import paho.mqtt.client as mqtt

BROKER = "test.mosquitto.org"
TOPIC_ESTADO = "c213/crac/estado"
TOPIC_SP = "c213/crac/setpoint"
TOPIC_COMANDO = "c213/crac/comando"
TOPIC_INJECAO = "c213/crac/injecao"
TOPIC_ALERTA = "datacenter/fuzzy/alert"

app = Flask(__name__)

estado_atual = {}
alerta_atual = None

# ---------- MQTT SUBSCRIBER (estado) ----------

def on_connect_sub(client, userdata, flags, rc):
    print("SUB conectado ao broker MQTT, rc =", rc)
    client.subscribe(TOPIC_ESTADO)
    print("Assinado no tópico de estado:", TOPIC_ESTADO)
    print("Assinado no tópico de alerta:", TOPIC_ALERTA)

def on_message_sub(client, userdata, msg):
    global estado_atual, alerta_atual
    try:
        payload = msg.payload.decode("utf-8")
        data = json.loads(payload)

        if msg.topic == TOPIC_ESTADO:
            estado_atual = data
            # print("Estado atualizado:", estado_atual)
        elif msg.topic == TOPIC_ALERTA:
            alerta_atual = data
            print("Alerta recebido via MQTT:", alerta_atual)
    except Exception as e:
        print("Erro ao processar mensagem MQTT:", e)


def mqtt_loop_sub():
    client = mqtt.Client(client_id="c213_dashboard_sub")
    client.on_connect = on_connect_sub
    client.on_message = on_message_sub
    client.connect(BROKER, 1883, 60)
    client.loop_forever()

# ---------- MQTT PUBLISHER (setpoint) ----------

pub_client = mqtt.Client(client_id="c213_dashboard_pub")
pub_client.connect(BROKER, 1883, 60)
pub_client.loop_start()

# ---------- ROTAS HTTP ----------

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/estado")
def estado():
    if not estado_atual:
        return jsonify({"status": "aguardando_dados"})
    return jsonify(estado_atual)

@app.route("/alerta")
def alerta():
    """Retorna o último alerta recebido via MQTT, se houver."""
    if alerta_atual is None:
        return jsonify({"temAlerta": False})
    return jsonify({"temAlerta": True, "dados": alerta_atual})

@app.route("/setpoint", methods=["POST"])
def setpoint():
    data = request.get_json(silent=True) or {}
    sp = data.get("setpoint")
    try:
        sp = int(sp)
    except (TypeError, ValueError):
        return jsonify({"status": "erro", "msg": "setpoint inválido"}), 400

    if sp not in (16, 22, 25, 32):
        return jsonify({"status": "erro", "msg": "setpoint fora da lista permitida"}), 400

    payload = json.dumps({"setpoint": sp})
    pub_client.publish(TOPIC_SP, payload)
    print(f"[HTTP] Setpoint enviado via MQTT: {sp}°C")
    return jsonify({"status": "ok", "setpoint": sp})

@app.route("/controle", methods=["POST"])
def controle():
    data = request.get_json(silent=True) or {}
    comando = data.get("comando")
    
    if comando not in ("iniciar", "parar", "limpar_grafico"):
        return jsonify({"status": "erro", "msg": "Comando inválido"}), 400

    payload = json.dumps({"comando": comando})
    pub_client.publish(TOPIC_COMANDO, payload)
    
    print(f"[HTTP] Comando enviado via MQTT: {comando}")
    return jsonify({"status": "ok", "comando": comando})

@app.route("/injetar", methods=["POST"])
def injetar():
    data = request.get_json(silent=True) or {}
    
    # Simplesmente publica todos os dados recebidos. A validação já foi feita no JS.
    payload = json.dumps({
        "erro": data.get("erro"),
        "deltaErro": data.get("deltaErro"),
        "text": data.get("text"),
        "carga": data.get("carga")
    })
    
    pub_client.publish(TOPIC_INJECAO, payload)
    print(f"[HTTP] Dados manuais injetados via MQTT: {payload}")
    return jsonify({"status": "ok", "dados": data})

# ---------- MAIN ----------

if __name__ == "__main__":
    t = threading.Thread(target=mqtt_loop_sub, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=5000, debug=False)
