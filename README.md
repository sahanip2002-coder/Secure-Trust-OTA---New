# **🛡️ Secure OTA Framework**

An advanced simulation framework for secure Over-The-Air (OTA) updates in IoT ecosystems. This project demonstrates a security-first approach to firmware updates, focusing on anomaly detection, device trustworthiness validation, and a "gating" mechanism to prevent compromised devices from receiving updates.

## **Key Features**

* **Anomaly Detection Engine:** Real-time monitoring of device telemetry (CPU, Memory, Disk, Temp) to detect instability or compromised states.  
* **Security Gating:** Automatically blocks firmware updates for devices flagged as "Anomalous" or "High Risk".  
* **Version Validation:** Prevents downgrade attacks and redundant updates by validating firmware versions server-side.  
* **Modular Architecture:** Clean separation of concerns with a scalable server structure (FastAPI), independent clients, and a TUI dashboard.  
* **Real-Time Dashboard:** A sophisticated Terminal User Interface (TUI) built with rich for live monitoring of network health, performance graphs, and security logs.  
* **State Persistence:** Maintains system state (logs, device status) across server restarts using JSON storage.

## **📂 Project Structure**

SECURE OTA NEW/  
├── server/                  \# The Core Brain  
│   ├── app/  
│   │   ├── routes/          \# API Endpoints (Telemetry, Admin, Public)  
│   │   ├── main.py          \# Server Entry & Config  
│   │   ├── services.py      \# Business Logic (Anomaly Check, OTA Trigger)  
│   │   ├── state.py         \# Persistence Layer (Save/Load)  
│   │   └── utils.py         \# Helpers (SSL, Config)  
│   ├── config/              \# JSON Configurations  
│   ├── firmware/            \# Firmware Binary Storage  
│   ├── TUI/                 \# Dashboard Code  
│   └── run.py               \# Server Launcher  
├── client1/                 \# IoT Device Simulator 1 
│   ├── client.py            \# Device Agent Code  
│   └── config.json          \# Identity & Port Config  
├── client2/                 \# IoT Device Simulator 2  
│   ├── client.py            \# Device Agent Code  
│   └── config.json          \# Identity & Port Config  
├── admin\_tool.py            \# CLI Tool for Admins to push updates  
├── dashboard.py             \# Legacy Dashboard (Optional)  
└── requirements.txt         \# Python Dependencies

## **🛠️ Installation & Setup**

### **Prerequisites**

* Python 3.10+ installed.  
* pip (Python package manager).

### **1\. Install Dependencies**

Open a terminal in the project root and run:

pip install \-r requirements.txt  
\# Or manually:  
pip install fastapi uvicorn requests psutil rich cryptography

### **2\. Generate SSL Certificates**

The server uses self-signed SSL certificates for secure communication. These are generated automatically on the first run of the server.

## **🚦 How to Run the Simulation**

Follow this specific order to start the entire ecosystem. You will need **4 separate terminal windows**.

### **Terminal 1: The Server**

This is the central command center.

cd server  
python run.py

*You should see:  SECURE OTA SERVER (MODULAR) Running at https://0.0.0.0:8443*

### **Terminal 2: The Dashboard (TUI)**

This is your monitoring interface.

cd server/TUI  
python main.py

* **Press 1:** Network Summary  
* **Press 2:** Live Graphs (CPU/Mem/Temp)  
* **Press 3:** Security Logs  
* **Press d:** Cycle through devices in Graph View

### **Terminal 3: Client 1 (Healthy Device)**

Simulates a standard, stable IoT device.

cd client1  
python client.py

*You should see: 📡 Client iot-001 started on port 8000*

### **Terminal 4: Client 2 (High Load / Anomaly)**

Simulates a device under stress or attack.

cd client2  
python client.py

*You should see: 📡 Client iot-002 started on port 8001*

## **Testing Scenarios**

### **Scenario A: Successful Update (Happy Path)**

1. Ensure **Client 1** is running and shows "Stable" on the Dashboard.  
2. Open a new terminal (Terminal 5\) in the root folder.  
3. Run the Admin Tool: python admin\_tool.py.  
4. Select **iot-001**.  
5. **Result:**  
   * Admin Tool: ✅ SUCCESS: Update to v2.1.5 initiated  
   * Client 1 Terminal: ✅ \[OTA\] Updated to v2.1.5  
   * Dashboard: Version updates to 2.1.5.

### **Scenario B: Security Block (Unhappy Path)**

1. Ensure **Client 2** is running. It generates high CPU/Memory load, so the Dashboard should flag it as **⚠️ CRITICAL / ANOMALY**.  
2. Run the Admin Tool: python admin\_tool.py.  
3. Select **iot-002**.  
4. **Result:**  
   * Admin Tool: 🛡️ BLOCKED: Anomaly Detected  
   * Dashboard Log (View 3): BLOCKED → OTA for iot-002 rejected (Risk: High Load)

### **Scenario C: Version Validation (Anti-Downgrade)**

1. Try to update **Client 1** *again* (after Scenario A).  
2. Run the Admin Tool and select **iot-001**.  
3. **Result:**  
   * Admin Tool: ⏭️ SKIPPED: Device already on v2.1.5  
   * Server saves bandwidth by not sending the file.

## **Configuration**

You can tweak the simulation behavior by editing the JSON files in server/config/:

* **thresholds.json**: Adjust cpu\_threshold or mem\_threshold to make the anomaly detection more or less sensitive.  
* **devices.json**: Add or remove allowed device IDs (Whitelist).  
* **ota\_settings.json**: Change the target firmware version string.

