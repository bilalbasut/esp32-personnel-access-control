#include <Arduino.h>
#include <Wire.h>
#include "RTClib.h"
#include "FS.h"
#include <LittleFS.h>
#include <SPI.h>
#include <Ethernet.h>
#include <PubSubClient.h>
#include <Preferences.h>
#include <ArduinoJson.h>


// --- 1. PROJECT DATA STRUCTURES ---
// #pragma pack ensures the compiler uses exactly 32 bytes with no padding
#pragma pack(push, 1) 
struct AccessRecord {
  uint32_t seq;         // Sequence number (increments forever)
  uint32_t ts;          // Unix timestamp
  uint8_t uid[7];       // Card UID (raw bytes)
  uint8_t uidLen;       // Length of UID
  uint8_t dir;          // 0=in, 1=out
  uint8_t result;       // 0=granted, 1=unknown, 2=expired, 3=schedule, 4=manual
  uint8_t mode;         // 0=online, 1=offline
  uint8_t tsrc;         // 0=ntp, 1=rtc, 2=invalid
  uint8_t floor;        // Floor/door number
  uint8_t reserved[9];  // Padding to hit exactly 32 bytes
  uint16_t crc16;       // Integrity check
};
#pragma pack(pop)


// --- 2. GLOBAL VARIABLES & NVS POINTERS ---

Preferences preferences;
int readPointer = 0;         // Tracks which log needs to be sent next
int writePointer = 0;        // Tracks where the next scanned card should be saved
uint32_t globalSequence = 0; // Lifetime scan counter for deduplication

const int MAX_LOGS = 500;    // Maximum offline capacity before overwriting old logs

// --- Hardware Pins ---
#define RELAY_PIN       32
#define BUZZER_PIN      33
#define GREEN_LED_PIN   25
#define RED_LED_PIN     17
#define EXIT_BUTTON_PIN 35
#define DOOR_SENSOR_PIN 34
#define SCANNER_RX_PIN  27
#define SCANNER_TX_PIN  26
#define W5500_CS_PIN    5
#define W5500_RST_PIN   4

RTC_PCF8563 rtc;
// --- FreeRTOS Task Handle ---
TaskHandle_t NetworkTask;

// --- State Machine Timers ---
unsigned long relayStartTime = 0;
bool isRelayActive = false;
unsigned long successBeepStartTime = 0;
bool isSuccessBeepActive = false;
bool isDenySequenceActive = false;
unsigned long lastDenyStepTime = 0;
int denyBeepCount = 0;
bool denyLedState = false;
bool hasDoorOpened = false;

// --- FR-04 Debounce Tracking ---
String lastScannedUID = "";
unsigned long lastScanTime = 0;

// --- 3. NETWORK & MQTT CONFIGURATION ---

byte mac[] = { 0x00, 0x1A, 0x2B, 0x3C, 0x4D, 0x5E };
IPAddress mqttServer(192, 168, 1, 100); 

EthernetClient ethClient;
PubSubClient mqtt(ethClient);

const char* mqtt_client_id = "GATE-K3-01";
const char* topic_event = "pdks/merkez/dev/GATE-K3-01/event";
const char* topic_event_ack = "pdks/merkez/dev/GATE-K3-01/event/ack";
const char* topic_status = "pdks/merkez/dev/GATE-K3-01/status";
const char* topic_hb = "pdks/merkez/dev/GATE-K3-01/hb";


// --- 4. HELPER FUNCTIONS ---
// Converts incoming ASCII Hex from the UART scanner into raw binary bytes
void stringToBytes(String hexString, uint8_t* byteArray, uint8_t maxLen) {
  int len = hexString.length();
  for (int i = 0; i < len && i / 2 < maxLen; i += 2) {
    String byteString = hexString.substring(i, i + 2);
    byteArray[i / 2] = (uint8_t) strtol(byteString.c_str(), NULL, 16);
  }
}


// --- 5. HARDWARE CONTROL (NON-BLOCKING) ---

void grantAccess() {
  isDenySequenceActive = false; 
  digitalWrite(RED_LED_PIN, LOW);
  hasDoorOpened = false;
  
  isRelayActive = true;
  relayStartTime = millis();
  digitalWrite(GREEN_LED_PIN, HIGH);
  digitalWrite(RELAY_PIN, HIGH); 
  
  isSuccessBeepActive = true;
  successBeepStartTime = millis();
  digitalWrite(BUZZER_PIN, HIGH);
}

void denyAccess() {
  if (isRelayActive) return; // Don't override an active unlock
  isDenySequenceActive = true;
  denyBeepCount = 0;
  denyLedState = true; 
  lastDenyStepTime = millis();
  digitalWrite(RED_LED_PIN, HIGH);
  digitalWrite(BUZZER_PIN, HIGH);
}

// State machine processor called every loop cycle
void handleHardwareTimers() {
  unsigned long currentMillis = millis();
  
  if (isRelayActive && (currentMillis - relayStartTime >= 3000)) {
    isRelayActive = false;
    digitalWrite(GREEN_LED_PIN, LOW);
    digitalWrite(RELAY_PIN, LOW);
  }
  
  if (isSuccessBeepActive && (currentMillis - successBeepStartTime >= 250)) {
    isSuccessBeepActive = false;
    digitalWrite(BUZZER_PIN, LOW);
  }
  
  if (isDenySequenceActive) {
    if (currentMillis - lastDenyStepTime >= 150) {
      lastDenyStepTime = currentMillis; 
      if (denyLedState) {
        digitalWrite(RED_LED_PIN, LOW);
        digitalWrite(BUZZER_PIN, LOW);
        denyLedState = false;
        denyBeepCount++; 
      } else {
        if (denyBeepCount < 3) {
          digitalWrite(RED_LED_PIN, HIGH);
          digitalWrite(BUZZER_PIN, HIGH);
          denyLedState = true;
        } else {
          isDenySequenceActive = false;
        }
      }
    }
  }
}


// --- 6. DATABASE & LOGGING ---

bool isCardAuthorized(String scannedUID) {
  scannedUID.trim(); 
  File file = LittleFS.open("/database.txt", FILE_READ);
  if (!file) return false; 

  while (file.available()) {
    String line = file.readStringUntil('\n');
    line.trim(); 
    if (line == scannedUID) {
      file.close(); 
      return true;
    }
  }
  file.close(); 
  return false;
}

// Creates the 32-byte binary record and saves it to LittleFS
void logAccess(DateTime now, String scannedUID, uint8_t resultCode) {
  AccessRecord record = {0}; 
  
  globalSequence++;
  preferences.putUInt("seq", globalSequence);

  record.seq = globalSequence;
  record.ts = now.unixtime();
  record.uidLen = scannedUID.length() / 2; 
  stringToBytes(scannedUID, record.uid, 7); 
  record.dir = 0; 
  record.result = resultCode; 
  record.mode = (mqtt.connected()) ? 0 : 1; 
  record.tsrc = 1; // 1=rtc (Placeholder until NTP is implemented)
  record.floor = 3; 
  record.crc16 = 0xFFFF; // Placeholder

  String filename = "/log_" + String(writePointer) + ".bin";
  File logFile = LittleFS.open(filename, FILE_WRITE);
  if (logFile) {
    logFile.write((uint8_t*)&record, sizeof(AccessRecord));
    logFile.close();
  }
  
  Serial.println("Saved bin record to slot " + String(writePointer));
  
  writePointer++;
  if (writePointer >= MAX_LOGS) writePointer = 0;
  preferences.putInt("writePtr", writePointer);
}

// ==============================================================================
// --- 7. MQTT CALLBACK (FR-08 COMPLIANCE) ---
// ==============================================================================
// This function fires automatically when the server sends a message to the ESP32
void mqttCallback(char* topic, byte* payload, unsigned int length) {
  // Convert incoming payload to a String
  String message = "";
  for (unsigned int i = 0; i < length; i++) {
    message += (char)payload[i];
  }
  
  // If the message is an ACK from the server
  if (String(topic) == topic_event_ack) {
    JsonDocument doc;
    DeserializationError error = deserializeJson(doc, message);
    
    if (!error) {
      uint32_t ack_seq = doc["ack_seq"]; // Parse the sequence number
      
      // Load the current log waiting in the queue to verify the sequence matches
      String filename = "/log_" + String(readPointer) + ".bin";
      if (LittleFS.exists(filename)) {
        File logFile = LittleFS.open(filename, FILE_READ);
        AccessRecord record;
        logFile.read((uint8_t*)&record, sizeof(AccessRecord));
        logFile.close();
        
        // CRITICAL FR-08 LOGIC: Only advance the pointer if the server explicitly ACKs this exact sequence
        if (record.seq == ack_seq) {
          Serial.println("ACK Received for Seq: " + String(ack_seq) + ". Advancing pointer.");
          readPointer++;
          if (readPointer >= MAX_LOGS) readPointer = 0;
          preferences.putInt("readPtr", readPointer);
        }
      }
    }
  }
}


// --- 8. FREERTOS CORE 0 NETWORK TASK ---

void networkTaskCode(void * pvParameters) {
  pinMode(W5500_RST_PIN, OUTPUT);
  digitalWrite(W5500_RST_PIN, LOW);
  delay(100);
  digitalWrite(W5500_RST_PIN, HIGH);
  delay(500);
  
  Ethernet.init(W5500_CS_PIN);
  mqtt.setServer(mqttServer, 1883); 
  mqtt.setCallback(mqttCallback); // Attach the listener function
  
  unsigned long lastHeartbeat = 0;

  for(;;) {
    Ethernet.maintain(); 
    
    if (Ethernet.linkStatus() == LinkON) {
      if (!mqtt.connected()) {
        Serial.println("Attempting MQTT connection...");
        if (mqtt.connect(mqtt_client_id, NULL, NULL, topic_status, 1, true, "offline")) {
          Serial.println("MQTT connected!");
          mqtt.publish(topic_status, "online", true); 
          mqtt.subscribe(topic_event_ack); // Subscribe to the ACK topic
        }
      } else {
        mqtt.loop(); // Must be called frequently to process incoming ACKs
        
        // FR-11: 30 Second Heartbeat
        if (millis() - lastHeartbeat > 30000) {
          mqtt.publish(topic_hb, "{\"uptime\": true}");
          lastHeartbeat = millis();
        }

        // Process Offline Queue
        if (readPointer != writePointer) {
          String filename = "/log_" + String(readPointer) + ".bin";
          
          if (LittleFS.exists(filename)) {
            File logFile = LittleFS.open(filename, FILE_READ);
            AccessRecord record;
            logFile.read((uint8_t*)&record, sizeof(AccessRecord));
            logFile.close();
            
            char payload[150];
            sprintf(payload, "{\"seq\":%lu,\"uid\":\"%s\",\"ts\":%lu,\"res\":%d}", 
                    record.seq, lastScannedUID.c_str(), record.ts, record.result);
            
            // Send the log. We DO NOT advance the pointer here anymore. 
            // The mqttCallback function will handle it when the server replies.
            mqtt.publish(topic_event, payload);
          } else {
             // File missing error handling
             readPointer++;
             if(readPointer >= MAX_LOGS) readPointer = 0;
             preferences.putInt("readPtr", readPointer);
          }
        }
      }
    }
    vTaskDelay(100 / portTICK_PERIOD_MS); 
  }
}


// --- 9. SETUP & INITIALIZATION ---

void initFileSystem() {
  if (!LittleFS.begin(true)) return;
  if (!LittleFS.exists("/database.txt")) {
    File file = LittleFS.open("/database.txt", FILE_WRITE);
    if (file) {
      file.println("04A2B3C1D5E680"); // Example valid hex
      file.close();
    }
  }
}

void setup() {
  Serial.begin(115200);
  delay(1000);
  
  initFileSystem();
  preferences.begin("access_system", false); 
  
  readPointer = preferences.getInt("readPtr", 0);
  writePointer = preferences.getInt("writePtr", 0);
  globalSequence = preferences.getUInt("seq", 0);
  
  Serial1.begin(9600, SERIAL_8N1, SCANNER_RX_PIN, SCANNER_TX_PIN);

  pinMode(RELAY_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(GREEN_LED_PIN, OUTPUT);
  pinMode(RED_LED_PIN, OUTPUT);
  pinMode(EXIT_BUTTON_PIN, INPUT);
  pinMode(DOOR_SENSOR_PIN, INPUT);

  if (!rtc.begin()) {
    Serial.println("CRITICAL ERROR: Couldn't find PCF8563! Check wiring.");
    while (1); 
  }

  if (rtc.lostPower()) {
    Serial.println("RTC lost power! Resetting time...");
    rtc.adjust(DateTime(F(__DATE__), F(__TIME__)));
  }

  xTaskCreatePinnedToCore(networkTaskCode, "NetworkTask", 10000, NULL, 1, &NetworkTask, 0);
}


// --- 10. MAIN HARDWARE LOOP (CORE 1) ---

void loop() {
  handleHardwareTimers(); 

  // Exit Button Trigger
  if (digitalRead(EXIT_BUTTON_PIN) == LOW && !isRelayActive) {
    DateTime now = rtc.now();
    // BUG FIX: Use a dummy valid hex string instead of "MANUAL"
    logAccess(now, "00000000000000", 4); 
    grantAccess();
  }

  // Anti-Tailgating Sensor
  if (isRelayActive) {
    bool currentDoorState = digitalRead(DOOR_SENSOR_PIN);
    if (currentDoorState == HIGH) hasDoorOpened = true; 
    if (hasDoorOpened && currentDoorState == LOW) {
      isRelayActive = false;
      digitalWrite(GREEN_LED_PIN, LOW);
      digitalWrite(RELAY_PIN, LOW);
      hasDoorOpened = false; 
    }
  }

  // UART Scanner Reading
  if (Serial1.available() > 0) {
    String scannedUID = "";
    while (Serial1.available() > 0) {
      char incomingByte = Serial1.read(); 
      scannedUID += incomingByte;
      delay(2); 
    }
    scannedUID.trim();
    unsigned long currentMillis = millis();

    // FR-04: 5-Second Debounce Logic
    if (scannedUID == lastScannedUID && (currentMillis - lastScanTime < 5000)) {
      Serial.println("Debounce: Ignored duplicate scan.");
    } else {
      lastScannedUID = scannedUID;
      lastScanTime = currentMillis;

      DateTime now = rtc.now();
      
      if (isCardAuthorized(scannedUID)) {
        logAccess(now, scannedUID, 0); 
        grantAccess(); 
      } else {
        logAccess(now, scannedUID, 1); 
        denyAccess(); 
      }
    }
  }
}