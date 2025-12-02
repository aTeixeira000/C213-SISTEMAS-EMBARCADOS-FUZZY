import paho.mqtt.client as mqtt

BROKER = "test.mosquitto.org"
TOPIC = "c213/crac/estado"

def on_connect(client, userdata, flags, rc):
    print("Conectado ao broker, código rc =", rc)
    client.subscribe(TOPIC)
    print(f"Assinado no tópico: {TOPIC}")

def on_message(client, userdata, msg):
    try:
        payload = msg.payload.decode("utf-8")
    except UnicodeDecodeError:
        payload = msg.payload
    print(f"[MQTT] {msg.topic} -> {payload}")

client = mqtt.Client(client_id="c213_teste_sub")
client.on_connect = on_connect
client.on_message = on_message

client.connect(BROKER, 1883, 60)
print("Conectando ao broker MQTT...")
client.loop_forever()
