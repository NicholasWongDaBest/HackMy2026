/*
 * hGroup10 ESP32 sensor and pump node.
 *
 * Sensors -> newline-delimited JSON -> Raspberry Pi/MySQL/dashboard.
 * Raspberry Pi -> PUMP_ON/PUMP_OFF -> ESP32 IO25 -> relay -> pump.
 *
 * The ESP32 has the final 10-second safety cutoff. Even if the Pi or
 * dashboard fails after PUMP_ON, the relay is returned to OFF.
 */
#include <Arduino.h>
#include <dht11.h>

#define DHT11PIN       17
#define LIGHTPIN       34
#define SOILPIN        32
#define WATERLEVELPIN  33
#define RAINWATERPIN   35
#define RELAYPIN       25

const unsigned long SAMPLE_INTERVAL_MS = 60000UL;
const unsigned long PUMP_MAX_RUN_MS = 10000UL;
const char* POSITION = "zone-1";

// The supplied two-channel relay is active-low. If your relay LED is on
// while the dashboard says STOPPED, change this to false and re-upload.
const bool RELAY_ACTIVE_LOW = false;
const uint8_t PUMP_ON_LEVEL = RELAY_ACTIVE_LOW ? LOW : HIGH;
const uint8_t PUMP_OFF_LEVEL = RELAY_ACTIVE_LOW ? HIGH : LOW;

const float ADC_FULL_SCALE = 4095.0;

dht11 DHT11;
unsigned long lastSample = 0;
unsigned long pumpStartedAt = 0;
bool pumpRunning = false;
String commandBuffer;

float clampPercent(float value) {
  if (value < 0.0) return 0.0;
  if (value > 100.0) return 100.0;
  return value;
}

void emitReading(const char* sensorType, float value) {
  Serial.print("{\"sensor_position\":\"");
  Serial.print(POSITION);
  Serial.print("\",\"sensor_type\":\"");
  Serial.print(sensorType);
  Serial.print("\",\"sensor_value\":");
  Serial.print(value, 2);
  Serial.println("}");
}

void reportPump(const char* reason) {
  Serial.print("{\"type\":\"pump\",\"state\":\"");
  Serial.print(pumpRunning ? "on" : "off");
  Serial.print("\",\"reason\":\"");
  Serial.print(reason);
  Serial.println("\"}");
}

void setPump(bool turnOn, const char* reason) {
  digitalWrite(RELAYPIN, turnOn ? PUMP_ON_LEVEL : PUMP_OFF_LEVEL);
  pumpRunning = turnOn;
  if (turnOn) pumpStartedAt = millis();
  reportPump(reason);
}

void handleCommand(String command) {
  command.trim();
  command.toUpperCase();

  if (command == "PUMP_ON") {
    setPump(true, "command");
  } else if (command == "PUMP_OFF") {
    setPump(false, "command");
  } else if (command == "PUMP_STATUS") {
    reportPump("status_request");
  } else if (command.length() > 0) {
    Serial.print("{\"type\":\"error\",\"message\":\"unknown command: ");
    Serial.print(command);
    Serial.println("\"}");
  }
}

void readCommands() {
  while (Serial.available() > 0) {
    char received = Serial.read();
    if (received == '\n' || received == '\r') {
      if (commandBuffer.length() > 0) {
        handleCommand(commandBuffer);
        commandBuffer = "";
      }
    } else if (commandBuffer.length() < 50) {
      commandBuffer += received;
    }
  }
}

void sampleAndReport() {
  int dhtResult = DHT11.read(DHT11PIN);
  if (dhtResult == DHTLIB_OK) {
    emitReading("temperature", (float)DHT11.temperature);
    emitReading("humidity", (float)DHT11.humidity);
  } else {
    Serial.print("{\"type\":\"error\",\"message\":\"DHT11 read failed: ");
    Serial.print(dhtResult);
    Serial.println("\"}");
  }

  float light = clampPercent((analogRead(LIGHTPIN) / ADC_FULL_SCALE) * 100.0);
  float moisture = clampPercent(
      (analogRead(SOILPIN) / ADC_FULL_SCALE) * 100.0 * 2.3);
  float waterLevel = clampPercent(
      (analogRead(WATERLEVELPIN) / ADC_FULL_SCALE) * 100.0 * 2.5);
  float rainfall = clampPercent(
      (analogRead(RAINWATERPIN) / ADC_FULL_SCALE) * 100.0);

  emitReading("light", light);
  emitReading("moisture", moisture);
  emitReading("water_level", waterLevel);
  emitReading("rainfall", rainfall);
}

void setup() {
  Serial.begin(9600);

  pinMode(DHT11PIN, INPUT);
  pinMode(LIGHTPIN, INPUT);
  pinMode(SOILPIN, INPUT);
  pinMode(WATERLEVELPIN, INPUT);
  pinMode(RAINWATERPIN, INPUT);

  pinMode(RELAYPIN, OUTPUT);
  digitalWrite(RELAYPIN, PUMP_OFF_LEVEL);

  delay(1500);
  Serial.println("{\"type\":\"system\",\"status\":\"ready\"}");
  reportPump("boot");

  lastSample = millis() - SAMPLE_INTERVAL_MS;
}

void loop() {
  readCommands();

  unsigned long now = millis();
  if (pumpRunning && now - pumpStartedAt >= PUMP_MAX_RUN_MS) {
    setPump(false, "safety_timeout");
  }

  if (now - lastSample >= SAMPLE_INTERVAL_MS) {
    lastSample = now;
    sampleAndReport();
  }
}
