"""
==============================================================
  IoT OTA ADMIN TOOL
  - View connected devices and their status
  - Upload real firmware (.bin) to server/firmware/latest.bin
  - Trigger OTA update on selected device
==============================================================
USAGE:
  python admin_tool.py
  (Run from project root — same folder as server/)
==============================================================
"""

import os
import shutil
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SERVER_URL    = "https://127.0.0.1:8443"
FIRMWARE_DIR  = os.path.join("server", "firmware")   # server/firmware/latest.bin

session = requests.Session()
session.verify = False


# -------------------------------------------------------
# LIST DEVICES
# -------------------------------------------------------
def list_devices():
    try:
        resp = session.get(f"{SERVER_URL}/api/devices", timeout=5)
        if resp.status_code != 200:
            print(f"❌ Failed to fetch devices: HTTP {resp.status_code}")
            return {}
        return resp.json()
    except Exception as e:
        print(f"❌ Cannot reach server: {e}")
        return {}


def print_devices(devices: dict):
    if not devices:
        print("⚠️  No devices connected yet.")
        return

    print(f"\n{'#':<4} {'Device ID':<22} {'Status':<22} {'CPU':>6} {'MEM':>6} {'Temp':>7} {'Version':<10} {'IP'}")
    print("─" * 95)
    for i, (did, d) in enumerate(devices.items()):
        # ✅ Correct field names from actual server response
        status = d.get("status", "Unknown")
        icon   = "🟢" if status == "Stable" else "🔴"
        cpu    = f"{d.get('cpu',  0):.1f}%"
        mem    = f"{d.get('mem',  0):.1f}%"
        temp   = f"{d.get('temp', 0):.1f}°C"
        ver    = d.get("version", "?")
        ip     = d.get("ip", "?")
        print(f"{i+1:<4} {did:<22} {icon} {status:<19} {cpu:>6} {mem:>6} {temp:>7} {ver:<10} {ip}")
    print()


# -------------------------------------------------------
# COPY FIRMWARE TO SERVER FOLDER
# No upload endpoint needed — directly copy .bin to
# server/firmware/latest.bin which server serves via
# GET /firmware/latest.bin
# -------------------------------------------------------
def copy_firmware(bin_path: str) -> bool:
    if not os.path.exists(bin_path):
        print(f"❌ File not found: {bin_path}")
        return False

    os.makedirs(FIRMWARE_DIR, exist_ok=True)
    dest = os.path.join(FIRMWARE_DIR, "latest.bin")

    file_size = os.path.getsize(bin_path)
    print(f"📦 Copying firmware: {bin_path} ({file_size / 1024:.1f} KB)")

    try:
        shutil.copy2(bin_path, dest)
        print(f"✅ Firmware ready at: {dest}")
        return True
    except Exception as e:
        print(f"❌ Copy failed: {e}")
        return False


# -------------------------------------------------------
# TRIGGER OTA ON DEVICE
# Server → POST http://{device_ip}:{ota_port}/ota-trigger
# ESP32  → Downloads /firmware/latest.bin → flashes → reboots
# -------------------------------------------------------
def trigger_ota(device_id: str):
    print(f"\n⚡ Triggering OTA on: {device_id}")
    try:
        resp = session.post(
            f"{SERVER_URL}/admin/deploy/{device_id}",
            timeout=10
        )
        if resp.status_code == 200:
            result = resp.json()
            if result.get("status") == "blocked":
                print(f"🛡️  BLOCKED: {result.get('reason', 'Unknown reason')}")
            else:
                print(f"✅ OTA trigger sent!")
                print(f"   ESP32 will download firmware and reboot automatically.")
        else:
            print(f"❌ Deploy failed: HTTP {resp.status_code} — {resp.text}")
    except Exception as e:
        print(f"❌ Trigger error: {e}")


# -------------------------------------------------------
# MAIN
# -------------------------------------------------------
def main():
    print("\n" + "=" * 55)
    print("   IoT OTA ADMIN TOOL")
    print(f"   Server : {SERVER_URL}")
    print(f"   FW Dir : {os.path.abspath(FIRMWARE_DIR)}")
    print("=" * 55)

    devices = list_devices()
    if not devices:
        return

    print_devices(devices)
    device_list = list(devices.items())

    sel = input("Select device # to manage (or 'q' to quit): ").strip()
    if sel.lower() == 'q' or not sel.isdigit():
        print("Exiting.")
        return

    idx = int(sel) - 1
    if idx < 0 or idx >= len(device_list):
        print("❌ Invalid selection.")
        return

    target_id, target_info = device_list[idx]
    print(f"\n📡 Selected : {target_id}")
    print(f"   Status   : {target_info.get('status', '?')}")
    print(f"   Version  : {target_info.get('version', '?')}")
    print(f"   IP       : {target_info.get('ip', '?')}")
    print(f"   CPU/MEM  : {target_info.get('cpu', 0):.1f}% / {target_info.get('mem', 0):.1f}%")

    print("\nWhat do you want to do?")
    print("  1. Copy new firmware (.bin) to server + trigger OTA")
    print("  2. Trigger OTA only (use firmware already on server)")
    print("  3. Cancel")

    action = input("\nChoice: ").strip()

    if action == "1":
        bin_path = input("Enter path to .bin file: ").strip().strip('"')
        if copy_firmware(bin_path):
            confirm = input(f"Trigger OTA on '{target_id}' now? (y/n): ")
            if confirm.lower() == 'y':
                trigger_ota(target_id)
            else:
                print("Firmware copied. Trigger manually when ready.")

    elif action == "2":
        fw_path = os.path.join(FIRMWARE_DIR, "latest.bin")
        if not os.path.exists(fw_path):
            print(f"❌ No firmware found at {fw_path}")
            print("   Use option 1 to copy a .bin file first.")
            return
        fw_size = os.path.getsize(fw_path) / 1024
        print(f"   Using existing firmware: {fw_path} ({fw_size:.1f} KB)")
        confirm = input(f"Trigger OTA on '{target_id}'? (y/n): ")
        if confirm.lower() == 'y':
            trigger_ota(target_id)
        else:
            print("Cancelled.")

    elif action == "3":
        print("Cancelled.")
    else:
        print("❌ Invalid choice.")


if __name__ == "__main__":
    main()