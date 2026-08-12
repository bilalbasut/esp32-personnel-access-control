#include <Arduino.h>
#include <Wire.h>
#include "RTClib.h"
#include "database.h" // temporary list will change when smallFS added

// --- 1. Hardware Pins ---
// Outputs
#define RELAY_PIN       32
#define BUZZER_PIN      33
#define GREEN_LED_PIN   25
#define RED_LED_PIN     17

// Inputs (Restored)
#define EXIT_BUTTON_PIN 35
#define DOOR_SENSOR_PIN 34

// UART Scanner
#define SCANNER_RX_PIN  27
#define SCANNER_TX_PIN  26

// --- 2. RTC Object ---
RTC_DS3231 rtc;

// --- 3. Hardware Control Functions ---
void grantAccess() {
  digitalWrite(GREEN_LED_PIN, HIGH);
  digitalWrite(RELAY_PIN, HIGH); 
  
  digitalWrite(BUZZER_PIN, HIGH);
  delay(500);
  digitalWrite(BUZZER_PIN, LOW);
  
  delay(2500); // Door remains unlocked for 3 seconds total
  
  digitalWrite(GREEN_LED_PIN, LOW);
  digitalWrite(RELAY_PIN, LOW);
}

void denyAccess() {
  for (int i = 0; i < 3; i++) {
    digitalWrite(RED_LED_PIN, HIGH);
    digitalWrite(BUZZER_PIN, HIGH);
    delay(150);
    
    digitalWrite(RED_LED_PIN, LOW);
    digitalWrite(BUZZER_PIN, LOW);
    delay(150);
  }
}

bool isCardAuthorized(String scannedUID) {
  scannedUID.trim(); 
  for (int i = 0; i < numAuthorizedCards; i++) {
    if (scannedUID == authorizedCards[i]) {
      return true; 
    }
  }
  return false; 
}

// --- 4. System Setup ---
void setup() {
  Serial.begin(115200);
  delay(1000);
  
  // Initialize Scanner on Serial1
  Serial1.begin(9600, SERIAL_8N1, SCANNER_RX_PIN, SCANNER_TX_PIN);

  // Initialize Outputs
  pinMode(RELAY_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(GREEN_LED_PIN, OUTPUT);
  pinMode(RED_LED_PIN, OUTPUT);
  
  digitalWrite(RELAY_PIN, LOW);
  digitalWrite(BUZZER_PIN, LOW);
  digitalWrite(GREEN_LED_PIN, LOW);
  digitalWrite(RED_LED_PIN, LOW);

  // Initialize Inputs (Restored)
  pinMode(EXIT_BUTTON_PIN, INPUT);
  pinMode(DOOR_SENSOR_PIN, INPUT);

  // Initialize RTC
  if (!rtc.begin()) {
    Serial.println("CRITICAL ERROR: Couldn't find RTC! Check wiring.");
    while (1); 
  }

  if (rtc.lostPower()) {
    Serial.println("RTC lost power! Resetting time...");
    rtc.adjust(DateTime(F(__DATE__), F(__TIME__)));
  }

  Serial.println("System Ready. Waiting for card scan...");
}

// --- 5. Main Loop ---
void loop() {
  if (Serial1.available() > 0) {
    String scannedUID = "";
    
    // Read the incoming UART bytes from the scanner
    while (Serial1.available() > 0) {
      char incomingByte = Serial1.read(); 
      scannedUID += incomingByte;
      delay(2); 
    }
    
    scannedUID.trim();

    // Get the exact time from the I2C RTC
    DateTime now = rtc.now();
    char timestamp[25];
    sprintf(timestamp, "%04d/%02d/%02d %02d:%02d:%02d", 
            now.year(), now.month(), now.day(), 
            now.hour(), now.minute(), now.second());

    // Print the formatted log
    Serial.print("[");
    Serial.print(timestamp);
    Serial.print("] UID: ");
    Serial.print(scannedUID);
    
    // Check the database and fire the hardware
    if (isCardAuthorized(scannedUID)) {
      Serial.println(" -> GRANTED");
      grantAccess(); 
    } else {
      Serial.println(" -> DENIED");
      denyAccess(); 
    }
  }
}