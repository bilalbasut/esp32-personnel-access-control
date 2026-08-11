#include <Arduino.h>
#include "database.h"

// --- 1. Pin Definitions ---

// Outputs
#define RELAY_PIN       32
#define BUZZER_PIN      33
#define GREEN_LED_PIN   25
#define RED_LED_PIN     17

// Inputs
#define EXIT_BUTTON_PIN 35
#define DOOR_SENSOR_PIN 34

// UART Scanner Pins
#define SCANNER_RX_PIN  27  // Connect to Scanner's TX wire
#define SCANNER_TX_PIN  26  // Connect to Scanner's RX wire

void setup() {
  // --- 2. Initialize Debug Console ---
  // This is for your computer's serial monitor
  Serial.begin(115200);
  delay(1000); // Give the serial monitor a second to connect
  Serial.println("\n--- Access Control System Booting ---");

  // --- 3. Initialize UART Scanner ---
  // Most commercial RFID scanners default to a 9600 baud rate.
  // We route Hardware Serial 1 to our chosen GPIO pins.
  Serial1.begin(9600, SERIAL_8N1, SCANNER_RX_PIN, SCANNER_TX_PIN);
  Serial.println("Scanner Serial port opened on RX:27, TX:26");

  // --- 4. Configure Output Pins ---
  pinMode(RELAY_PIN, OUTPUT);
  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(GREEN_LED_PIN, OUTPUT);
  pinMode(RED_LED_PIN, OUTPUT);

  // Set default secure states (everything off/locked)
  digitalWrite(RELAY_PIN, LOW);
  digitalWrite(BUZZER_PIN, LOW);
  digitalWrite(GREEN_LED_PIN, LOW);
  digitalWrite(RED_LED_PIN, LOW);
  
  Serial.println("Output pins configured and secured.");

  // --- 5. Configure Input Pins ---
  // Important: GPIO 34 and 35 on the ESP32 are input-only and 
  // DO NOT have internal pull-up resistors. You MUST use physical resistors.
  pinMode(EXIT_BUTTON_PIN, INPUT);
  pinMode(DOOR_SENSOR_PIN, INPUT);
  
  Serial.println("Input pins configured.");
  Serial.println("Step 1 Complete. Ready for main loop.");
}

void loop() {
  // Check if the scanner has sent any data to the ESP32
  if (Serial1.available() > 0) {
    
    Serial.print("Card Scanned! Raw Data: ");
    String scannedUID = "";
    
    // Read all incoming bytes while they are available
    while (Serial1.available() > 0) {
      // Read one byte from the scanner
      char incomingByte = Serial1.read(); 
      
      // Add it to our string
      scannedUID += incomingByte;
      
      // Small delay to allow the next byte to arrive in the buffer
      delay(2); 
    }
    
    // Print the final, complete card UID to the console
    Serial.println(scannedUID);
    
    // Add a blank line for readability
    Serial.println("-------------------------");
  }
}

void grantAccess() {
  Serial.println("ACCESS GRANTED. Unlocking door...");
  
  digitalWrite(GREEN_LED_PIN, HIGH);
  digitalWrite(RELAY_PIN, HIGH); // Trigger the relay (dry contact closes)
  
  // A pleasant, single 500ms confirmation beep
  digitalWrite(BUZZER_PIN, HIGH);
  delay(500);
  digitalWrite(BUZZER_PIN, LOW);
  
  // Wait for the remainder of the 3-second unlock window
  delay(2500); 
  
  // Secure the door again
  digitalWrite(GREEN_LED_PIN, LOW);
  digitalWrite(RELAY_PIN, LOW);
  Serial.println("Door locked.");
}

void denyAccess() {
  Serial.println("ACCESS DENIED. Unrecognized Card.");
  
  // Flash red LED and beep 3 times rapidly
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
  
  // It uses the array from database.h seamlessly
  for (int i = 0; i < numAuthorizedCards; i++) {
    if (scannedUID == authorizedCards[i]) {
      return true; 
    }
  }
  return false; 
}

// --- Main Loop Update ---

void loop() {
  if (Serial1.available() > 0) {
    String scannedUID = "";
    
    while (Serial1.available() > 0) {
      char incomingByte = Serial1.read(); 
      scannedUID += incomingByte;
      delay(2); 
    }
    
    Serial.print("Card Scanned: ");
    Serial.println(scannedUID);
    
    // Check the database and trigger the appropriate hardware sequence
    if (isCardAuthorized(scannedUID)) {
      grantAccess();
    } else {
      denyAccess();
    }
    
    Serial.println("-------------------------");
  }
}