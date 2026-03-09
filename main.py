import os
from pathlib import Path

# --- DEFINITIONS OF ALL FILES ---

FILES = {
    # 1. SERVER ENTRY POINT
    "server/run.py": r"""
import uvicorn
from app.utils import create_ssl_cert

if __name__ == "__main__":
    # 1. Ensure SSL is ready before server start
    key_path, cert_path = create_ssl_cert()
    
    print("\n" + "="*60)
    print("   IOTFW SECURE OTA SERVER (MODULAR)")
    print("   Running at https://0.0.0.0:8443")
    print("="*60 + "\n")

    # 2. Start Uvicorn
    uvicorn.run(
        "app.main:app", 
        host="0.0.0.0", 
        port=8443, 
        ssl_keyfile=str(key_path), 
        ssl_certfile=str(cert_path),
        reload=True
    )
""",

    # 2. SERVER MAIN APP
    "server/app/main.py": r"""
from fastapi import FastAPI
from app.utils import setup_directories, load_json, CONFIG_DIR
from app.routes import telemetry, admin, public
import json

app = FastAPI(title="IOTFW Secure OTA Server (Modular)")

# Include Routers
app.include_router(telemetry.router)
app.include_router(admin.router)
app.include_router(public.router)

# Event: On Startup
@app.on_event("startup")
async def startup_event():
    setup_directories()
    
    # Create default config files if missing
    defaults = {
        "thresholds.json": {"global": {"cpu_threshold": 85.0, "mem_threshold": 90.0}},
        "devices.json": {"allowed_devices": ["iot-001", "iot-002", "sensor-03"]},
        "ota_settings.json": {"target_firmware_version": "2.1.5"}
    }
    for f, d in defaults.items():
        if not load_json(f): 
            (CONFIG_DIR / f).write_text(json.dumps(d, indent=4))
            
    print("✅ Server Modules Loaded Successfully")
""",

    # 3. SHARED STATE
    "server/app/state.py": r"""
# This file holds the in-memory database so all modules share the SAME data
devices = {}
ota_log = []
anomaly_count = 0

def increment_anomaly():
    global anomaly_count
    anomaly_count += 1
""",

    # 4. UTILITIES
    "server/app/utils.py": r"""
import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography import x509
from cryptography.x509.oid import NameOID

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
FIRMWARE_DIR = BASE_DIR / "firmware"

def setup_directories():
    CONFIG_DIR.mkdir(exist_ok=True)
    FIRMWARE_DIR.mkdir(exist_ok=True)

def load_json(filename, default=None):
    path = CONFIG_DIR / filename
    if path.exists():
        try: return json.loads(path.read_text())
        except: pass
    return default if default is not None else {}

def create_ssl_cert():
    key_path = BASE_DIR / "key.pem"
    cert_path = BASE_DIR / "cert.pem"
    
    if key_path.exists() and cert_path.exists(): 
        return key_path, cert_path

    print("Generating SSL cert...")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "peera-server")])
    cert = x509.CertificateBuilder().subject_name(name).issuer_name(name)\
        .public_key(key.public_key()).serial_number(x509.random_serial_number())\
        .not_valid_before(datetime.now(timezone.utc))\
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=3650))\
        .sign(key, hashes.SHA256())
    
    key_path.write_text(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()).decode())
    cert_path.write_text(cert.public_bytes(serialization.Encoding.PEM).decode())
    
    return key_path, cert_path
""",

    # 5. SERVICES (BUSINESS LOGIC)
    "server/app/services.py": r"""
import requests
from app.state import devices, ota_log, increment_anomaly
from app.utils import load_json

# --- ANOMALY ENGINE ---
def check_telemetry_health(data):
    cfg = load_json("thresholds.json", {"global": {}}).get("global", {})
    cpu_th = cfg.get("cpu_threshold", 85.0)
    mem_th = cfg.get("mem_threshold", 90.0)

    if data.cpu > cpu_th or data.mem > mem_th:
        increment_anomaly()
        return "ANOMALY (High Load)", False
    
    return "Stable", True

def log_security_events(device_id, is_anomaly, cpu_val):
    prev_device = devices.get(device_id, {})
    prev_status = prev_device.get("status", "Unknown")

    if is_anomaly and "ANOMALY" not in prev_status:
        ota_log.append(f"⚠️ ALERT → {device_id} entered ANOMALY state (CPU:{cpu_val}%)")
    elif not is_anomaly and "ANOMALY" in prev_status:
        ota_log.append(f"ea RECOVERY → {device_id} returned to Stable state")

# --- OTA SERVICE ---
async def trigger_device_update(device_id, ip_address):
    try:
        requests.post(f"http://{ip_address}:8000/ota-trigger", timeout=5)
        ota_log.append(f"✅ SUCCESS → {device_id} updated successfully")
    except Exception as e:
        ota_log.append(f"⚠️ FAILED → Connection error with {device_id}")
""",

    # 6. ROUTES: TELEMETRY
    "server/app/routes/telemetry.py": r"""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel
from datetime import datetime
from app.state import devices
from app.utils import load_json
from app.services import check_telemetry_health, log_security_events

router = APIRouter()

class TelemetryModel(BaseModel):
    device_id: str
    cpu: float
    mem: float
    temp: float
    version: str
    timestamp: int

@router.post("/telemetry")
async def receive_telemetry(data: TelemetryModel, request: Request):
    allowed = load_json("devices.json", {}).get("allowed_devices", [])
    if allowed and data.device_id not in allowed:
        print(f"⛔ BLOCKED unauthorized device: {data.device_id}")
        raise HTTPException(status_code=403, detail="Unauthorized")

    status, is_stable = check_telemetry_health(data)
    log_security_events(data.device_id, not is_stable, data.cpu)

    devices[data.device_id] = {
        **data.dict(),
        "ip": request.client.host,
        "last_seen": datetime.now().strftime("%H:%M:%S"),
        "status": status,
        "is_stable": is_stable
    }
    return {"status": "ok"}
""",

    # 7. ROUTES: ADMIN
    "server/app/routes/admin.py": r"""
import asyncio
from fastapi import APIRouter, HTTPException
from app.state import devices, ota_log
from app.services import trigger_device_update

router = APIRouter()

@router.post("/admin/deploy/{device_id}")
async def deploy_ota_manual(device_id: str):
    device = devices.get(device_id)
    if not device: raise HTTPException(404, "Device not found")
    if not device.get("ip"): raise HTTPException(400, "IP unknown")

    # SECURITY GATING
    if not device.get("is_stable", True):
        msg = f"🛑 BLOCKED → OTA for {device_id} rejected (Risk: High Load)"
        ota_log.append(msg)
        return {"status": "blocked", "reason": "Anomaly Detected"}

    msg = f"🚀 DEPLOYING → {device_id} (Stable). Sending trigger..."
    ota_log.append(msg)
    asyncio.create_task(trigger_device_update(device_id, device["ip"]))
    
    return {"status": "initiated", "target_ip": device["ip"]}
""",

    # 8. ROUTES: PUBLIC
    "server/app/routes/public.py": r"""
from fastapi import APIRouter
from fastapi.responses import FileResponse
from app.state import devices, ota_log, anomaly_count
from app.utils import FIRMWARE_DIR

router = APIRouter()

@router.get("/firmware/latest.bin")
async def get_firmware():
    fw_path = FIRMWARE_DIR / "firmware.bin"
    if not fw_path.exists():
        fw_path.write_bytes(b"IOTFW-MODULAR-FIRMWARE-v2.1.5")
    return FileResponse(fw_path)

@router.get("/api/devices")
async def get_devices(): return devices

@router.get("/api/stats")
async def get_stats():
    return {"total": len(devices), "anomalies": anomaly_count, "log": ota_log[-20:]}
""",

    # 9. INIT FILES
    "server/app/__init__.py": "",
    "server/app/routes/__init__.py": "",

    # 10. CLIENT SCRIPT
    "client/client.py": r"""
import json, time, random, requests, urllib3
from threading import Thread
from http.server import BaseHTTPRequestHandler, HTTPServer

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    with open("config.json") as f: cfg = json.load(f)
except:
    cfg = {"device_id": "iot-001", "server_url": "https://127.0.0.1:8443", "telemetry_interval": 5}

ID = cfg.get("device_id", "iot-001")
URL = cfg.get("server_url", "https://127.0.0.1:8443")
INT = cfg.get("telemetry_interval", 5)
VER = "1.0.0"

def send_loop():
    session = requests.Session()
    session.verify = False
    print(f"📡 Client {ID} started. Target: {URL}")
    
    while True:
        try:
            is_high_load = "002" in ID
            data = {
                "device_id": ID, "version": VER,
                "cpu": round(random.uniform(86, 99) if is_high_load else random.uniform(20, 60), 1),
                "mem": round(random.uniform(80, 95) if is_high_load else random.uniform(30, 50), 1),
                "temp": round(random.uniform(35, 75), 1), "timestamp": int(time.time())
            }
            resp = session.post(f"{URL}/telemetry", json=data, timeout=5)
            if resp.status_code == 200: print(f"   [Sent] CPU: {data['cpu']}% | Status: OK")
            elif resp.status_code == 403: print(f"❌ Access Denied: Not whitelisted!")
        except: print("❌ Connection Failed")
        time.sleep(INT)

class OTAHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/ota-trigger":
            self.send_response(200); self.end_headers()
            print(f"\n⚡ [OTA] Trigger received! Updating..."); Thread(target=perform_update).start()
    def log_message(self, format, *args): return

def perform_update():
    global VER
    try:
        r = requests.get(f"{URL}/firmware/latest.bin", verify=False, timeout=10)
        if r.status_code == 200:
            time.sleep(2); VER = "2.1.5"; print(f"✅ [OTA] SUCCESS: Updated to v{VER}")
    except: print("❌ Update Failed")

if __name__ == "__main__":
    try:
        httpd = HTTPServer(("", 8000), OTAHandler)
        Thread(target=httpd.serve_forever, daemon=True).start()
        send_loop()
    except: pass
""",
    "client/config.json": r"""{ "device_id": "iot-001", "server_url": "https://127.0.0.1:8443", "telemetry_interval": 5 }""",

    # 11. ADMIN TOOL
    "admin_tool.py": r"""
import requests, urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
SERVER_URL = "https://127.0.0.1:8443"
session = requests.Session(); session.verify = False

try:
    devs = session.get(f"{SERVER_URL}/api/devices").json()
    print(f"\n{'ID':<15} {'Status':<20}")
    print("-" * 40)
    d_list = list(devs.items())
    for i, (did, d) in enumerate(d_list):
        icon = "🟢" if d['status'] == "Stable" else "🔴"
        print(f"{i+1}. {did:<11} {icon} {d['status']:<17}")
    
    sel = input("\nSelect device # to update: ")
    if sel.isdigit():
        target = d_list[int(sel)-1][0]
        res = session.post(f"{SERVER_URL}/admin/deploy/{target}").json()
        if res['status'] == 'blocked': print(f"🛡️  BLOCKED: {res['reason']}")
        else: print(f"✅ SUCCESS: Initiated")
except Exception as e: print(f"Error: {e}")
"""
}

# --- INSTALLER LOGIC ---

def install():
    base_path = Path.cwd()
    print(f"📦 Installing Modular IoT Project to: {base_path}\n")

    for file_path, content in FILES.items():
        full_path = base_path / file_path
        
        # Create directories
        full_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write file
        full_path.write_text(content.strip(), encoding="utf-8")
        print(f"  + Created: {file_path}")

    print("\n✅ Installation Complete!")
    print("------------------------------------------------")
    print("1. Run Server:  cd server && python run.py")
    print("2. Run Client:  cd client && python client.py")
    print("3. Run Admin:   python admin_tool.py")
    print("------------------------------------------------")

if __name__ == "__main__":
    install()