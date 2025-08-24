# streamlit_dashboard.py
import streamlit as st
import folium
from streamlit.components.v1 import html
import paho.mqtt.client as mqtt
import json
import threading
import time
import math

# ---------- CONFIG ----------
MQTT_BROKER = "test.mosquitto.org"
MQTT_PORT = 1883
MQTT_TOPIC = "smart_ambulance/location"

# List of sample intersections (lat, lon) to simulate traffic lights
INTERSECTIONS = [
    {"name": "Intersection A", "lat": 12.9716, "lng": 77.5946},
    {"name": "Intersection B", "lat": 12.9750, "lng": 77.5900},
    {"name": "Intersection C", "lat": 12.9680, "lng": 77.6000},
]

# distance threshold in meters to trigger green light
GREEN_DISTANCE_METERS = 200.0

# ---------- HELPERS ----------
def haversine(lat1, lon1, lat2, lon2):
    # returns distance in meters between two lat/lon
    R = 6371000  # earth radius in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi/2)**2 + math.cos(phi1)*math.cos(phi2)*math.sin(dlambda/2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    return R * c

# ---------- SESSION STATE ----------
if "ambulance" not in st.session_state:
    # default location (Bengaluru) until we receive messages
    st.session_state.ambulance = {"lat": 12.9716, "lng": 77.5946, "time": None, "speed": None}
if "lights" not in st.session_state:
    # default red lights
    st.session_state.lights = {it["name"]: "red" for it in INTERSECTIONS}
if "mqtt_connected" not in st.session_state:
    st.session_state.mqtt_connected = False

# ---------- MQTT CALLBACKS ----------
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        client.subscribe(MQTT_TOPIC)
        st.session_state.mqtt_connected = True
        print("Connected to MQTT broker, subscribed to", MQTT_TOPIC)
    else:
        print("Failed to connect to MQTT broker. rc:", rc)

def on_message(client, userdata, msg):
    try:
        payload = msg.payload.decode("utf-8")
        data = json.loads(payload)
        lat = float(data.get("lat", st.session_state.ambulance["lat"]))
        lng = float(data.get("lng", st.session_state.ambulance["lng"]))
        ts = data.get("time", None)
        # update session state (thread-safe-ish via set)
        st.session_state.ambulance = {"lat": lat, "lng": lng, "time": ts}
        # update lights: if ambulance within threshold of an intersection -> that intersection green
        for inter in INTERSECTIONS:
            d = haversine(lat, lng, inter["lat"], inter["lng"])
            if d <= GREEN_DISTANCE_METERS:
                st.session_state.lights[inter["name"]] = "green"
            else:
                # only set to red if not near any ambulance (simple logic)
                st.session_state.lights[inter["name"]] = "red"
        # print debug
        print("Received:", st.session_state.ambulance)
    except Exception as e:
        print("Error parsing MQTT message:", e)

def mqtt_thread():
    client = mqtt.Client()
    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    except Exception as e:
        print("MQTT connect error:", e)
        return
    client.loop_forever()

# ---------- START MQTT IN BACKGROUND ----------
if "mqtt_thread_started" not in st.session_state:
    t = threading.Thread(target=mqtt_thread, daemon=True)
    t.start()
    st.session_state.mqtt_thread_started = True
    time.sleep(0.2)

# ---------- UI ----------
st.title("🚦 Smart Ambulance — Traffic Control Dashboard")
col1, col2 = st.columns([2,1])

with col1:
    st.subheader("Ambulance Location (OpenStreetMap)")
    # Create folium map
    amb = st.session_state.ambulance
    map_center = [amb["lat"], amb["lng"]]
    m = folium.Map(location=map_center, zoom_start=15)
    # Add ambulance marker
    folium.Marker(
        [amb["lat"], amb["lng"]],
        tooltip="Ambulance",
        popup=f"Ambulance\nlat:{amb['lat']:.6f}\nlng:{amb['lng']:.6f}\nTime:{amb['time']}",
        icon=folium.Icon(color="red", icon="plus-sign")
    ).add_to(m)
    # Add intersections and lights
    for it in INTERSECTIONS:
        color = "green" if st.session_state.lights[it["name"]] == "green" else "red"
        folium.CircleMarker([it["lat"], it["lng"]],
                            radius=12,
                            color=color,
                            fill=True,
                            fill_color=color,
                            fill_opacity=0.7,
                            tooltip=f'{it["name"]} ({st.session_state.lights[it["name"]]})').add_to(m)
    # Render folium map in Streamlit
    map_html = m._repr_html_()
    html(map_html, height=600)

with col2:
    st.subheader("Status & Controls")
    st.markdown(f"**MQTT Broker:** `{MQTT_BROKER}:{MQTT_PORT}`")
    st.markdown(f"**Topic:** `{MQTT_TOPIC}`")
    st.markdown("---")
    st.markdown("**Ambulance**")
    st.write(f"Latitude: `{amb['lat']:.6f}`")
    st.write(f"Longitude: `{amb['lng']:.6f}`")
    st.write(f"Last update: `{amb['time']}`")
    st.markdown("---")
    st.subheader("Traffic Lights")
    for it in INTERSECTIONS:
        status = st.session_state.lights[it["name"]]
        color_emoji = "🟢" if status == "green" else "🔴"
        st.write(f"{color_emoji} **{it['name']}** — {status}")

st.sidebar.title("Simulator helpers")
st.sidebar.write("If you don't have the Flutter app running you can run the simulator to publish locations.")
st.sidebar.write("Use the provided `mqtt_publisher_simulator.py` script in the same folder.")
st.sidebar.write("Dashboard refreshes automatically when messages arrive.")

# small heartbeat indicator
if st.session_state.mqtt_connected:
    st.success("Connected to MQTT broker ✅")
else:
    st.warning("Connecting to MQTT broker... (check console for errors)")

# keep app responsive; this small sleep allows background mqtt callbacks to update session_state
time.sleep(0.1)
