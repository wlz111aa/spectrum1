import network
import time
import machine
import uasyncio as asyncio
import json
import gc
import ubinascii
from machine import I2C, Pin
from umqtt.simple import MQTTClient
from as7341 import AS7341_Async

# ==========================================
#               CONFIGURATION
# ==========================================
# WiFi Settings
WIFI_SSID = "cc"
WIFI_PASS = "66666666"

# MQTT Settings
MQTT_BROKER = "be18721454da4600b14a92424bb1181c.s1.eu.hivemq.cloud"
MQTT_PORT = 8883  # SSL/TLS
MQTT_TOPIC = "meimefarm/Spectrum"
# MQTT_TOPIC_SECOND removed as per user request
MQTT_CLIENT_ID = None # Will be generated from unique_id
MQTT_USER = "meimeifarm"
MQTT_PASSWORD = "Meimei83036666"

# Static IP Settings
STATIC_IP_ENABLED = False
# STATIC_IP = '192.168.0.170'
# NETMASK = '255.255.255.0'
# GATEWAY = '192.168.0.1'
# DNS = '8.8.8.8'

# Hardware Settings
SCL_PIN = 8
SDA_PIN = 9
I2C_FREQ = 400000

# Application Settings
READ_INTERVAL_MS = 5000  # 5 seconds per user logic
MODBUS_PORT = 502        # Standard Modbus TCP port
MODBUS_SLAVE_ADDR = 7    # Modbus RTU Slave Address / TCP Unit ID
UNIT_ID = MODBUS_SLAVE_ADDR

# Modbus RTU Settings
MODBUS_RTU_ENABLED = False
UART_ID = 1
UART_BAUD = 9600
UART_TX_PIN = 4          # Adjust based on hardware
UART_RX_PIN = 5          # Adjust based on hardware
UART_DE_PIN = None       # Driver Enable Pin for RS485 (e.g. 2), set to None if auto or not used
DEBUG_MODBUS_RTU = True  # Enable verbose logging for RTU debugging

# Channel Mapping
CHANNEL_NODES = {
    'channel1': 'node0701', 'channel2': 'node0702', 'channel3': 'node0703',
    'channel4': 'node0704', 'channel5': 'node0705', 'channel6': 'node0706',
    'channel7': 'node0707', 'channel8': 'node0708', 'channel9': 'node0709',
    'channel10': 'node0710', 'channel11': 'node0711',
}

# ==========================================
#              GLOBAL STATE
# ==========================================
latest_payload = {}
modbus_registers = [0] * 11  # F1..F8, CLEAR, NIR, DARK
wifi_connected = False
device_ip = "0.0.0.0"

# ==========================================
#              ASYNC TASKS
# ==========================================

async def wifi_task():
    global wifi_connected, device_ip
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    
    # Set Static IP
    if STATIC_IP_ENABLED and STATIC_IP:
        try:
            wlan.ifconfig((STATIC_IP, NETMASK, GATEWAY, DNS))
            print('[WiFi] Static IP configured:', STATIC_IP)
        except Exception as e:
            print('[WiFi] Static IP fail:', e)

    while True:
        if wlan.isconnected():
            if not wifi_connected:
                # Connected but flag not set (e.g. soft reboot or just connected)
                wifi_connected = True
                cfg = wlan.ifconfig()
                device_ip = cfg[0]
                print("="*40)
                print(f"[WiFi] CONNECTED! IP: {device_ip}")
                print(f"[Modbus] Server listening on: {device_ip}:{MODBUS_PORT}")
                print("="*40)
        else:
            # Not connected
            wifi_connected = False
            print(f"[WiFi] Connecting to {WIFI_SSID}...")
            try:
                wlan.connect(WIFI_SSID, WIFI_PASS)
            except Exception as e:
                print(f"[WiFi] Connect fail: {e}")
        
        await asyncio.sleep(5)

async def mqtt_task():
    client = None
    ssl_params = {'server_hostname': MQTT_BROKER} if MQTT_PORT == 8883 else {}
    
    # Generate Client ID (Robust)
    try:
        cid = ubinascii.hexlify(machine.unique_id())
    except Exception:
        try:
            import os
            cid = ubinascii.hexlify(os.urandom(3))
        except Exception:
            cid = b'unknown'
    real_client_id = b'esp32s3-' + cid
    
    print(f"[MQTT] Client ID: {real_client_id}")

    last_publish_time = 0

    while True:
        if not wifi_connected:
            # print("[MQTT] Waiting for WiFi...") # Reduce noise
            await asyncio.sleep(2)
            continue

        if client is None:
            print(f"[MQTT] Connecting to {MQTT_BROKER}...")
            try:
                client = MQTTClient(real_client_id, MQTT_BROKER, port=MQTT_PORT, 
                                  user=MQTT_USER, password=MQTT_PASSWORD, keepalive=60,
                                  ssl=(MQTT_PORT==8883), ssl_params=ssl_params)
                client.connect()
                print("[MQTT] Connected!")
            except Exception as e:
                print(f"[MQTT] Connect fail: {e}")
                client = None
                await asyncio.sleep(5)
                continue
        
        # Publish every 5 seconds if data exists
        now = time.ticks_ms()
        if latest_payload:
            if time.ticks_diff(now, last_publish_time) > 5000:
                try:
                    payload_str = json.dumps(latest_payload)
                    print(f"[MQTT] Publishing to {MQTT_TOPIC}...")
                    client.publish(MQTT_TOPIC, payload_str)
                    # client.publish(MQTT_TOPIC_SECOND, payload_str)
                    print(f"[MQTT] Publish OK")
                    last_publish_time = now
                except Exception as e:
                    print(f"[MQTT] Publish fail: {e}")
                    client = None # Force reconnect
            
        await asyncio.sleep(0.1)

def build_payload(spectrum):
    if not spectrum: return {}
    # Spectrum is already a dict with channel1..channel11 keys from as7341.py
    # We just return it directly as the user wants "channel": value format
    return spectrum

async def sensor_task():
    global latest_payload
    print("[Sensor] Initializing I2C...")
    try:
        i2c = I2C(0, scl=Pin(SCL_PIN), sda=Pin(SDA_PIN), freq=I2C_FREQ)
        sensor = AS7341_Async(i2c)
        
        while True:
            data = await sensor.read_spectrum_async()
            if data:
                latest_payload = build_payload(data)
                print(f"[Sensor] Updated: {latest_payload}")
            else:
                print("[Sensor] Read failed (empty data)")
            
            await asyncio.sleep_ms(READ_INTERVAL_MS)
    except Exception as e:
        print("[Sensor] Fatal I2C/Sensor Error:", e)
        # Retry loop? Or just fail? For now, just wait loop
        while True: await asyncio.sleep(10)

async def main():
    asyncio.create_task(wifi_task())
    asyncio.create_task(mqtt_task())
    asyncio.create_task(sensor_task())
    
    while True:
        await asyncio.sleep(10)
        gc.collect()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print("Main loop error:", e)

