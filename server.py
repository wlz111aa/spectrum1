import json
import threading
import time
from mcp.server.fastmcp import FastMCP

import paho.mqtt.client as mqtt

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import urllib.parse
import os
import argparse
import sys

# --- Configuration (edit as needed) ---
MQTT_BROKER = "be18721454da4600b14a92424bb1181c.s1.eu.hivemq.cloud"
MQTT_PORT = 8883
MQTT_TOPIC = "meimefarm/Spectrum"
MQTT_USER = "meimeifarm"
MQTT_PASSWORD = "Meimei83036666"
AWS_ACCESS_KEY_ID = "AKIAIOSFODNN7EXAMPLE"
AWS_SECRET_ACCESS_KEY = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"

# Shared state updated by MQTT callback
latest_spectrum = {}
http_server = None

def _on_connect(client, userdata, flags, rc):
    if rc == 0:
        client.subscribe(MQTT_TOPIC)
        print(f"[MQTT] Connected, subscribed to {MQTT_TOPIC}")
    else:
        print(f"[MQTT] Connect failed rc={rc}")

def _on_message(client, userdata, msg):
    global latest_spectrum
    try:
        payload = msg.payload.decode('utf-8')
        data = json.loads(payload)
        if isinstance(data, dict):
            latest_spectrum = data
            # small log
            print(f"[MQTT] Received spectrum: {list(data.keys())}")
    except Exception as e:
        print("[MQTT] Message parse error:", e)

def start_mqtt():
    client = mqtt.Client()
    if MQTT_USER:
        client.username_pw_set(MQTT_USER, MQTT_PASSWORD)
    # If using TLS port, enable TLS (use default CA certs)
    if MQTT_PORT == 8883:
        try:
            client.tls_set()
        except Exception:
            pass

    client.on_connect = _on_connect
    client.on_message = _on_message

    try:
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
    except Exception as e:
        print("[MQTT] Connect error:", e)
        return None

    client.loop_start()
    return client


# --- FastMCP server exposing spectrum ---
mcp = FastMCP("Spectrum")

@mcp.resource("spectrum://latest")
def get_latest_spectrum() -> dict:
    """Return the latest spectrum payload received over MQTT."""
    return latest_spectrum

@mcp.tool()
def get_channel(name: str) -> int:
    """Get an individual channel value by key, e.g. 'channel1'."""
    return int(latest_spectrum.get(name, 0))
@mcp.resource("spectrum://channels")
def get_all_channels() -> dict:
    """Return all channel values as ints when possible.

    This resource returns the full latest spectrum payload. It will try to
    convert numeric-looking values to `int`, and leave other values as-is.
    """
    out = {}
    for k, v in latest_spectrum.items():
        try:
            out[k] = int(v)
        except Exception:
            out[k] = v
    return out
@mcp.tool()
def get_all_spectrum() -> dict:
    """Tool to return the full latest spectrum payload.

    Tries to convert numeric-looking values to `int`, leaves others as-is.
    """
    out = {}
    for k, v in latest_spectrum.items():
        try:
            out[k] = int(v)
        except Exception:
            out[k] = v
    return out
def start_http_server(bind_host: str = '0.0.0.0', port: int = 8000):
    web_dir = os.path.join(os.path.dirname(__file__), 'web')

    class WebHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, directory=web_dir, **kwargs):
            super().__init__(*args, directory=directory, **kwargs)

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            # serve API
            if parsed.path == '/api/latest':
                self.send_response(200)
                # CORS - allow access from browser pages
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', 'Content-Type')
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(latest_spectrum).encode('utf-8'))
                return

            # explicitly serve index for root
            if parsed.path in ('', '/', '/index.html'):
                try:
                    index_path = os.path.join(web_dir, 'index.html')
                    with open(index_path, 'rb') as f:
                        content = f.read()
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/html; charset=utf-8')
                    self.send_header('Content-Length', str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                    return
                except Exception:
                    pass

            return super().do_GET()

        def do_OPTIONS(self):
            # respond to CORS preflight
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == '/api/latest':
                self.send_response(204)
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
                self.send_header('Access-Control-Allow-Headers', 'Content-Type')
                self.end_headers()
                return
            return super().do_OPTIONS()

    server = ThreadingHTTPServer((bind_host, port), WebHandler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    print(f"[HTTP] Serving web UI on http://{bind_host}:{port}/")
    return server


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Spectrum MCP + simple web UI')
    parser.add_argument('--http-host', default=os.environ.get('HTTP_BIND', '0.0.0.0'),
                        help='HTTP bind host (default from HTTP_BIND or 0.0.0.0)')
    parser.add_argument('--http-port', type=int, default=int(os.environ.get('HTTP_PORT', '8000')),
                        help='HTTP port (default from HTTP_PORT or 8000)')
    parser.add_argument('--no-mqtt', action='store_true', help='Do not start MQTT client (for testing)')
    args = parser.parse_args()

    print("Starting spectrum MCP server...")
    mqtt_client = None
    if not args.no_mqtt:
        mqtt_client = start_mqtt()

    # start a small static HTTP server to serve the web UI and provide /api/latest
    http_server = start_http_server(args.http_host, args.http_port)

    try:
        mcp.run(transport="stdio")
    except KeyboardInterrupt:
        pass
    finally:
        if mqtt_client:
            mqtt_client.loop_stop()
            try:
                mqtt_client.disconnect()
            except Exception:
                pass
        if http_server:
            try:
                http_server.shutdown()
                http_server.server_close()
            except Exception:
                pass
