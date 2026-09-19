/*
 * ESP32 farm node -- hGroup10 "Save the Farm"
 *
 * Wired per the Keyestudio KS0567 assembly guide. Two jobs:
 *   1. read the kit's on-board sensors and stream them to the Pi as JSON
 *   2. drive the irrigation relay on command from the Pi
 *
 * Link: newline-delimited JSON over USB serial, 115200 baud.
 *
 * WHY THE WATCHDOG MATTERS
 * The Pi decides when to irrigate, but the Pi cannot stop a pump it has
 * lost the cable to. So this board refuses to run the relay on trust:
 *   - it stops after PUMP_MAX_RUN_MS no matter what the Pi says
 *   - it stops if no command has arrived for COMMAND_TIMEOUT_MS
 * The Pi therefore has to keep saying "still on" every second. Pull the
 * USB cable mid-irrigation and the pump shuts itself off within 5s.
 *
 * Other rules, mirroring app/sensors.py on the Pi:
 *   - a failed sensor read emits NOTHING; never a default, never a zero
 *   - no timestamp is sent; the board has no clock, the Pi stamps rows
 *   - no delay() in loop(), so commands are never blocked behind sampling
 *
 * Library: dht11 (resource/arduino codes/libraries/Dht11.zip)
 * Upload:  Arduino IDE -> board "ESP32 Dev Module" -> 115200 baud
 */
#include <dht11.h>

// ---- KS0567 pin map (from the Keyestudio assembly guide) --------------
#define DHT11PIN       17   // digital: air temperature + humidity
#define LIGHTPIN       34   // ADC1: photoresistor
#define WATERLEVELPIN  33   // ADC1: tank level
#define RAINWATERPIN   35   // ADC1: steam / rainfall
#define RELAYPIN       25   // water pump relay

// The KS0567 on-board relay energises on HIGH (matches the kit's own
// sample sketches). Set false if you swap in an active-low module.
const bool RELAY_ACTIVE_HIGH = true;

const unsigned long SAMPLE_INTERVAL_MS = 60000UL;  // matches POLL_INTERVAL_S
const unsigned long PUMP_MAX_RUN_MS    = 30000UL;  // matches PUMP_MAX_RUN_S
const unsigned long COMMAND_TIMEOUT_MS =  5000UL;  // link-loss cutoff

const char* POSITION = "zone-2-canopy";
const float ADC_FULL_SCALE = 4095.0;

dht11 DHT11;
unsigned long lastSample    = 0;
unsigned long pumpStartedMs = 0;
unsigned long lastCommandMs = 0;
bool   pumpOn = false;
String inputLine = "";

// ---- relay ------------------------------------------------------------
void relayWrite(bool on) {
  digitalWrite(RELAYPIN, (on == RELAY_ACTIVE_HIGH) ? HIGH : LOW);
}

void reportPump(const char* reason) {
  Serial.print("{\"node\":\"esp32\",\"pump\":\"");
  Serial.print(pumpOn ? "on" : "off");
  Serial.print("\",\"reason\":\"");
  Serial.print(reason);
  Serial.println("\"}");
}

void setPump(bool on, const char* reason) {
  if (on == pumpOn) return;          // nothing to do, stay quiet
  pumpOn = on;
  relayWrite(pumpOn);
  if (pumpOn) pumpStartedMs = millis();
  reportPump(reason);
}

// ---- commands from the Pi --------------------------------------------
// Deliberately string matching rather than a JSON parser: one message
// shape, no extra library, and nothing to go wrong on a noisy line.
void handleCommand(String line) {
  if (line.indexOf("\"cmd\":\"pump\"") < 0) return;

  lastCommandMs = millis();          // any pump command refreshes the watchdog

  if (line.indexOf("\"state\":\"on\"") >= 0) {
    setPump(true, "commanded");
  } else if (line.indexOf("\"state\":\"off\"") >= 0) {
    setPump(false, "commanded");
  }
}

// ---- sensors ----------------------------------------------------------
void emit(const char* sensorType, float value) {
  Serial.print("{\"sensor_position\":\"");
  Serial.print(POSITION);
  Serial.print("\",\"sensor_type\":\"");
  Serial.print(sensorType);
  Serial.print("\",\"sensor_value\":");
  Serial.print(value, 2);
  Serial.println("}");
}

// Raw ADC counts mean nothing to a judge. Convert to % of full scale.
float percentOfFullScale(int raw) {
  float pct = (raw / ADC_FULL_SCALE) * 100.0;
  if (pct < 0.0)   pct = 0.0;
  if (pct > 100.0) pct = 100.0;
  return pct;
}

void sampleAndReport() {
  int chk = DHT11.read(DHT11PIN);
  if (chk == 0) {                    // DHTLIB_OK
    emit("air_temperature", (float)DHT11.temperature);
    emit("humidity",        (float)DHT11.humidity);
  } else {
    Serial.print("{\"node\":\"esp32\",\"error\":\"dht11 read failed, code ");
    Serial.print(chk);
    Serial.println("\"}");
  }

  emit("light",       percentOfFullScale(analogRead(LIGHTPIN)));
  emit("water_level", percentOfFullScale(analogRead(WATERLEVELPIN)));
  emit("rainfall",    percentOfFullScale(analogRead(RAINWATERPIN)));
}

// ---- watchdog ---------------------------------------------------------
void enforceSafety() {
  if (!pumpOn) return;

  if (millis() - pumpStartedMs > PUMP_MAX_RUN_MS) {
    setPump(false, "max_runtime");
    return;
  }
  if (millis() - lastCommandMs > COMMAND_TIMEOUT_MS) {
    setPump(false, "link_lost");
  }
}

// ---- lifecycle --------------------------------------------------------
void setup() {
  Serial.begin(115200);

  pinMode(RELAYPIN, OUTPUT);
  relayWrite(false);                 // pump off before anything else

  pinMode(LIGHTPIN, INPUT);
  pinMode(WATERLEVELPIN, INPUT);
  pinMode(RAINWATERPIN, INPUT);

  inputLine.reserve(128);
  delay(1500);                       // DHT11 needs ~1s after power-up
  Serial.println("{\"node\":\"esp32\",\"status\":\"boot\",\"pump\":\"off\"}");
  lastSample = millis() - SAMPLE_INTERVAL_MS;   // sample immediately
}

void loop() {
  // 1. commands first -- never leave the pump waiting behind a sensor read
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n') {
      handleCommand(inputLine);
      inputLine = "";
    } else if (c != '\r') {
      if (inputLine.length() < 200) inputLine += c;   // cap: ignore junk floods
    }
  }

  // 2. safety, every pass
  enforceSafety();

  // 3. sampling. Subtraction handles the ~49-day millis() rollover.
  unsigned long now = millis();
  if (now - lastSample >= SAMPLE_INTERVAL_MS) {
    lastSample = now;
    sampleAndReport();
  }
}
