#pragma once
#include <Arduino.h>
#include <IPAddress.h>

// ============================================================
// 1. CONFIGURATION
// ============================================================
#define FW_VERSION "1.8.3"
#define DEVICE_ID "GATE-K3-01"
#define FLOOR_NUMBER 3
#define DEVICE_DIR DIR_IN // Options: DIR_IN (0) or DIR_OUT (1)

// Hardware Pins
#define RELAY_PIN       32
#define BUZZER_PIN      33
#define GREEN_LED_PIN   25
#define RED_LED_PIN     17
#define EXIT_BUTTON_PIN 35

// W5500 / VSPI
#define W5500_SCK_PIN   18
#define W5500_MISO_PIN  19
#define W5500_MOSI_PIN  23
#define W5500_CS_PIN    5
#define W5500_RST_PIN   4

// MFRC522 / HSPI
#define RFID_SCK_PIN    14
#define RFID_MISO_PIN   27
#define RFID_MOSI_PIN   13
#define RFID_SS_PIN     15

// I2C
#define I2C_SDA_PIN     21
#define I2C_SCL_PIN     22

// Timing
#define RELAY_DURATION_MS       3000UL
#define SUCCESS_BEEP_MS          250UL
#define DENY_STEP_MS             150UL
#define RFID_DEBOUNCE_MS        5000UL
#define EXIT_DEBOUNCE_MS          50UL
#define HEARTBEAT_INTERVAL_MS  30000UL
#define NTP_SYNC_INTERVAL_MS 3600000UL
#define ACK_TIMEOUT_MS          2000UL
#define PUBLISH_RATE_LIMIT_MS     50UL

// OTA Constants
#define OTA_CHUNK_SIZE           512
#define OTA_STALL_TIMEOUT_MS   10000UL
#define OTA_TOTAL_TIMEOUT_MS   60000UL

// Persistent Queue
#define EVENT_FILE "/events.bin"
#define MAX_EVENTS 20000
#define RECORD_SIZE 32
#define CHECKPOINT_EVENT_INTERVAL 64
#define CHECKPOINT_ACK_INTERVAL   16

// Network Configuration
inline byte mac[] = { 0x00, 0x1A, 0x2B, 0x3C, 0x4D, 0x5E };
inline IPAddress deviceIP(192, 168, 11, 155);
inline IPAddress dnsIP(8, 8, 8, 8);
inline IPAddress gatewayIP(192, 168, 10, 1);
inline IPAddress subnetMask(255, 255, 254, 0);
inline IPAddress mqttServer(192, 168, 10, 124);
const uint16_t MQTT_PORT = 1883;

// MQTT Topics
const char TOPIC_EVENT[]     = "pdks/merkez/dev/GATE-K3-01/event";
const char TOPIC_EVENT_ACK[] = "pdks/merkez/dev/GATE-K3-01/event/ack";
const char TOPIC_STATUS[]    = "pdks/merkez/dev/GATE-K3-01/status";
const char TOPIC_HEARTBEAT[] = "pdks/merkez/dev/GATE-K3-01/hb";
const char TOPIC_ACL[]       = "pdks/merkez/cfg/acl";
const char TOPIC_CMD[]       = "pdks/merkez/dev/GATE-K3-01/cmd";
const char TOPIC_CMD_RES[]   = "pdks/merkez/dev/GATE-K3-01/cmd/res";