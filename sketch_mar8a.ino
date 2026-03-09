#include <WiFi.h>
#include <HTTPClient.h>
#include <WiFiClientSecure.h>
#include <ArduinoJson.h>
#include <HTTPUpdate.h>
#include <WiFiServer.h>
#include <Preferences.h>
#include "ota_report.h"

// ---------------- CONFIG ----------------
const char* ssid       = "Galaxy A22 5G3803";
const char* password   = "abc@1234";
const char* device_id  = "ESP32_DEVICE_01";
const char* ota_server = "https://10.118.205.6:8443";
const int   telemetry_interval_ms = 5000;
const int   OTA_PORT   = 8000;
char firmware_version[16] = "1.0.0";

// ---------------- RAM UTILITIES ----------------
uint32_t getTotalRAM() { return ESP.getHeapSize(); }
uint32_t getFreeRAM()  { return ESP.getFreeHeap(); }
uint32_t getUsedRAM()  { return ESP.getHeapSize() - ESP.getFreeHeap(); }
float pct(uint32_t v, uint32_t t) { return (float)v / t * 100.0f; }
float _lastCpu = 0, _lastMem = 0, _lastTemp = 0;

// ---------------- GLOBALS ----------------
Preferences   prefs;
OTAReport     ota_snap;
unsigned long ota_start_ms   = 0;
int           _last_milestone = 0;
const int     MILESTONES[]   = {25, 50, 75, 100};

// -------------------------------------------------------
// OPERATIONAL METRICS STATE
// -------------------------------------------------------
uint32_t  _errorCount      = 0;   // total telemetry/HTTP errors since boot
uint32_t  _telemetryCount  = 0;   // total successful sends
uint32_t  _bootTime        = 0;   // Unix timestamp of boot (set in setup)
float     _lastLatencyMs   = 0;   // round-trip time of last telemetry POST

// Battery simulation (ESP32 has no battery ADC by default)
// Replace with analogRead(BATT_PIN) / voltage divider if hardware present
float getBatteryLevel() {
  // Simulates slow discharge 100% → 20% over ~8 hours of uptime
  if (_bootTime == 0) return 100.0f;
  uint32_t uptimeSec = (uint32_t)time(nullptr) - _bootTime;
  float discharged = (uptimeSec / 28800.0f) * 80.0f;  // 28800s = 8h
  return constrain(100.0f - discharged, 20.0f, 100.0f);
}

// Storage: ESP32 sketch partition used vs total
float getStorageUsedPct() {
  uint32_t total = ESP.getFlashChipSize();
  uint32_t used  = ESP.getSketchSize() + ESP.getFreeSketchSpace();
  // used = total partition allocated to sketches
  // report consumed sketch space as % of total flash
  if (total == 0) return 0;
  return pct(ESP.getSketchSize(), total);
}

// Network latency: measured as POST round-trip time (set after each send)
float measureLatency() {
  if (WiFi.status() != WL_CONNECTED) return -1;
  WiFiClientSecure* client = new WiFiClientSecure();
  client->setInsecure();
  client->setTimeout(5);
  HTTPClient http;
  http.begin(*client, String(ota_server) + "/health");
  http.setTimeout(3000);
  unsigned long t = millis();
  int code = http.GET();
  float latency = (code > 0) ? (float)(millis() - t) : -1;
  http.end();
  delete client;
  return latency;
}

// ---------------- WIFI ----------------
void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);
  Serial.print("📶 Connecting");
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED) {
    Serial.print(".");
    delay(500);
    if (++attempts > 40) ESP.restart();
  }
  Serial.printf(" ✅ %s\n", WiFi.localIP().toString().c_str());
}

// ---------------- TELEMETRY ----------------
String generateTelemetry() {
  static float simCpu = 75.0f;
  simCpu += (random(-10, 10) / 10.0f);
  simCpu = constrain(simCpu, 60.0f, 95.0f);
  _lastCpu  = simCpu;
  _lastMem  = pct(getUsedRAM(), getTotalRAM());
  _lastTemp = 35.0f + (_lastCpu / 2.5f);

  // ── New operational metrics ──────────────────────────
  float battery     = getBatteryLevel();
  float storage_pct = getStorageUsedPct();
  uint32_t uptime   = (_bootTime > 0)
                      ? (uint32_t)time(nullptr) - _bootTime : 0;

  DynamicJsonDocument doc(768);  // increased from 512 for new fields
  doc["device_id"]       = device_id;
  doc["version"]         = firmware_version;

  // Core metrics
  doc["cpu"]             = round(_lastCpu  * 10) / 10.0f;
  doc["mem"]             = round(_lastMem  * 10) / 10.0f;
  doc["temp"]            = round(_lastTemp * 10) / 10.0f;

  // ── New: battery, storage, latency, error_count ──────
  doc["battery"]         = round(battery     * 10) / 10.0f;  // %
  doc["storage"]         = round(storage_pct * 10) / 10.0f;  // % flash used
  doc["latency_ms"]      = round(_lastLatencyMs);             // ms
  doc["error_count"]     = _errorCount;                       // cumulative
  doc["uptime_sec"]      = uptime;                            // seconds since boot

  // Device info
  doc["device_ip"]       = WiFi.localIP().toString();
  doc["ota_port"]        = OTA_PORT;
  doc["connectivity"]    = "Connected";
  doc["cpu_freq_mhz"]    = ESP.getCpuFreqMHz();
  doc["free_memory"]     = getFreeRAM();
  doc["used_memory"]     = getUsedRAM();
  doc["rssi"]            = WiFi.RSSI();                       // WiFi signal dBm
  doc["timestamp"]       = (uint32_t)time(nullptr);

  String out; serializeJson(doc, out); return out;
}

// ---------------- SEND TELEMETRY ----------------
void sendTelemetry() {
  if (WiFi.status() != WL_CONNECTED) { connectWiFi(); return; }

  WiFiClientSecure* client = new WiFiClientSecure();
  client->setInsecure();
  client->setTimeout(15);

  HTTPClient http;
  http.begin(*client, String(ota_server) + "/telemetry");
  http.addHeader("Content-Type", "application/json");
  http.setTimeout(10000);

  unsigned long t0   = millis();
  int           code = http.POST(generateTelemetry());
  _lastLatencyMs     = (float)(millis() - t0);  // measure actual POST RTT

  if (code == 200) {
    _telemetryCount++;
    Serial.printf("📊 CPU:%.1f%% MEM:%.1f%% BAT:%.0f%% LAT:%.0fms ERR:%u v%s 🟢\n",
      _lastCpu, _lastMem, getBatteryLevel(), _lastLatencyMs,
      _errorCount, firmware_version);
  } else if (code > 0) {
    _errorCount++;
    Serial.printf("📊 CPU:%.1f%% MEM:%.1f%% ⚠️ HTTP %d ERR:%u\n",
      _lastCpu, _lastMem, code, _errorCount);
  } else {
    _errorCount++;
    Serial.printf("❌ Telemetry failed (%d) ERR:%u\n", code, _errorCount);
  }

  http.end();
  delete client;
}

// ---------------- SEND OTA EVENT ----------------
void sendOTAEvent(const char* event) {
  if (WiFi.status() != WL_CONNECTED) return;

  DynamicJsonDocument doc(768);
  doc["device_id"] = device_id;
  doc["version"]   = firmware_version;
  doc["event"]     = event;
  doc["timestamp"] = (uint32_t)time(nullptr);

  if (ota_snap.cpu_before > 0) {
    doc["cpu_before"]       = ota_snap.cpu_before;
    doc["mem_before"]       = ota_snap.mem_before;
    doc["heap_free_before"] = ota_snap.heap_before;
    doc["cpu_peak"]         = ota_snap.cpu_peak;
    doc["mem_peak"]         = ota_snap.mem_peak;
    doc["heap_free_peak"]   = ota_snap.heap_peak;
    doc["cpu_delta"]        = ota_snap.cpu_peak - ota_snap.cpu_before;
    doc["mem_delta"]        = ota_snap.mem_peak - ota_snap.mem_before;
    doc["heap_consumed"]    = (int32_t)ota_snap.heap_before - (int32_t)ota_snap.heap_peak;
    doc["duration_ms"]      = ota_snap.duration_ms;
    doc["old_version"]      = ota_snap.old_version;
  }

  String payload; serializeJson(doc, payload);

  WiFiClientSecure* client = new WiFiClientSecure();
  client->setInsecure(); client->setTimeout(10);
  HTTPClient http;
  http.begin(*client, String(ota_server) + "/telemetry/event");
  http.addHeader("Content-Type", "application/json");
  http.setTimeout(5000);
  http.POST(payload);
  http.end();
  delete client;
}

// ---------------- PRINT RESOURCE TABLE ----------------
void printOTAReport() {
  OTAReport r;
  if (!loadOTAReport(prefs, r)) return;

  uint32_t consumed = r.heap_before > r.heap_peak
                      ? r.heap_before - r.heap_peak : 0;
  float dur_s = r.duration_ms / 1000.0f;

  Serial.println("\n┌──────────────────────────────────────────┐");
  Serial.println("│        OTA RESOURCE USAGE SUMMARY        │");
  Serial.println("├─────────────┬─────────────┬──────────────┤");
  Serial.println("│  Metric     │ Before OTA  │ During OTA   │");
  Serial.println("├─────────────┼─────────────┼──────────────┤");
  Serial.printf ("│  CPU %%      │  %6.1f %%   │  %6.1f %%    │\n",
    r.cpu_before, r.cpu_peak);
  Serial.printf ("│  Memory %%   │  %6.1f %%   │  %6.1f %%    │\n",
    r.mem_before, r.mem_peak);
  Serial.printf ("│  Free Heap  │  %7u B  │  %7u B    │\n",
    r.heap_before, r.heap_peak);
  Serial.println("├─────────────┴─────────────┴──────────────┤");
  Serial.printf ("│  CPU delta  : %+.1f%%\n",  r.cpu_peak - r.cpu_before);
  Serial.printf ("│  MEM delta  : %+.1f%%\n",  r.mem_peak - r.mem_before);
  Serial.printf ("│  Heap used  : %u bytes\n", consumed);
  Serial.printf ("│  Duration   : %.1fs (%u ms)\n", dur_s, r.duration_ms);
  Serial.printf ("│  %s → %s\n", r.old_version, firmware_version);
  Serial.println("└──────────────────────────────────────────┘\n");

  clearOTAReport(prefs);
}

// ---------------- OTA PERFORM UPDATE ----------------
void performUpdate(void* param) {
  String fwUrl = String(ota_server) + "/firmware/latest.bin";

  memset(&ota_snap, 0, sizeof(ota_snap));
  ota_snap.cpu_before  = _lastCpu;
  ota_snap.mem_before  = pct(getUsedRAM(), getTotalRAM());
  ota_snap.heap_before = getFreeRAM();
  ota_snap.cpu_peak    = ota_snap.cpu_before;
  ota_snap.mem_peak    = ota_snap.mem_before;
  ota_snap.heap_peak   = ota_snap.heap_before;
  strncpy(ota_snap.old_version, firmware_version, 15);
  ota_snap.old_version[15] = '\0';

  ota_start_ms    = millis();
  _last_milestone = 0;

  Serial.println("\n⬆️  OTA UPDATE STARTING");
  Serial.printf("   v%s → new | CPU:%.1f%% MEM:%.1f%% Heap:%uB\n",
    firmware_version, ota_snap.cpu_before,
    ota_snap.mem_before, ota_snap.heap_before);

  sendOTAEvent("ota_start");

  WiFiClientSecure* client = new WiFiClientSecure();
  client->setInsecure();
  httpUpdate.rebootOnUpdate(false);

  httpUpdate.onProgress([](int current, int total) {
    if (total <= 0) return;
    int p = (current * 100) / total;
    for (int m : MILESTONES) {
      if (p >= m && _last_milestone < m) {
        _last_milestone = m;
        Serial.printf("   📥 %3d%%  heap:%uB\n", p, getFreeRAM());
      }
    }
    float cur_mem = pct(getUsedRAM(), getTotalRAM());
    if (cur_mem > ota_snap.mem_peak) {
      ota_snap.mem_peak  = cur_mem;
      ota_snap.heap_peak = getFreeRAM();
    }
    ota_snap.duration_ms = millis() - ota_start_ms;
  });

  httpUpdate.onStart([]()      {});
  httpUpdate.onEnd([]()        {});
  httpUpdate.onError([](int e) {
    _errorCount++;
    Serial.printf("   ❌ Error %d: %s\n", e,
      httpUpdate.getLastErrorString().c_str());
  });

  t_httpUpdate_return ret = httpUpdate.update(*client, fwUrl);
  delete client;

  if (ret == HTTP_UPDATE_OK) {
    ota_snap.duration_ms = millis() - ota_start_ms;
    saveOTAReport(prefs, ota_snap);
    Serial.printf("\n✅ Flash done | CPU:%.1f%% MEM:%.1f%% dur:%ums\n",
      ota_snap.cpu_before, ota_snap.mem_before, ota_snap.duration_ms);
    Serial.println("   Saved to NVS. Rebooting...");
    Serial.flush();
    delay(300);
    ESP.restart();

  } else if (ret == HTTP_UPDATE_FAILED) {
    _errorCount++;
    Serial.printf("❌ OTA failed (%d): %s\n",
      httpUpdate.getLastError(),
      httpUpdate.getLastErrorString().c_str());
    sendOTAEvent("ota_failed");

  } else if (ret == HTTP_UPDATE_NO_UPDATES) {
    Serial.println("ℹ️  Already up to date");
    sendOTAEvent("ota_skipped");
  }

  vTaskDelete(NULL);
}

// ---------------- OTA LISTENER TASK ----------------
WiFiServer otaServer(OTA_PORT);

void otaListenerTask(void* param) {
  otaServer.begin();
  Serial.printf("🎧 OTA ready on port %d\n", OTA_PORT);
  while (true) {
    WiFiClient client = otaServer.available();
    if (client) {
      String req = "";
      unsigned long t = millis();
      while (client.connected() && millis() - t < 2000) {
        if (client.available()) {
          char c = client.read();
          req += c;
          if (req.endsWith("\r\n\r\n")) break;
        }
      }
      if (req.startsWith("POST /ota-trigger")) {
        client.println("HTTP/1.1 200 OK\r\nContent-Length: 0\r\n\r\n");
        client.stop();
        Serial.println("\n⚡ OTA triggered by server");
        xTaskCreate(performUpdate, "OTA_UPDATE", 8192, NULL, 1, NULL);
      } else {
        client.println("HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\n\r\n");
        client.stop();
      }
    }
    vTaskDelay(10 / portTICK_PERIOD_MS);
  }
}

// ---------------- SETUP ----------------
void setup() {
  Serial.begin(115200);
  delay(1000);

  // Record boot time — used for uptime and battery simulation
  _bootTime = (uint32_t)time(nullptr);
  // If NTP not synced yet, use millis-based fallback
  if (_bootTime < 1000000) _bootTime = 0;

  Serial.printf("\n[%s] v%s\n", device_id, firmware_version);
  connectWiFi();

  // Sync time via NTP so timestamps and uptime are accurate
  configTime(0, 0, "pool.ntp.org", "time.nist.gov");
  // Wait up to 3s for NTP
  time_t now = 0;
  for (int i = 0; i < 6 && now < 1000000; i++) {
    delay(500); now = time(nullptr);
  }
  _bootTime = (uint32_t)now;
  Serial.printf("🕐 Boot time set: %u\n", _bootTime);

  printOTAReport();
  sendOTAEvent("device_online");
  xTaskCreate(otaListenerTask, "OTA_LISTENER", 4096, NULL, 1, NULL);
}

// ---------------- LOOP ----------------
void loop() {
  unsigned long loopStart = millis();
  sendTelemetry();
  long sleepMs = telemetry_interval_ms - (long)(millis() - loopStart);
  if (sleepMs > 0) delay((uint32_t)sleepMs);
}