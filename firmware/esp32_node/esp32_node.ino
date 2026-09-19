/*
 * ESP32 sensor and irrigation node for hGroup10.
  *
   * ESP32 -> Raspberry Pi:
    *   one JSON sensor reading per line, every 60 seconds
     *
      * Raspberry Pi -> ESP32:
       *   PUMP_ON / PUMP_OFF / PUMP_STATUS
        *   or {"cmd":"pump","state":"on|off"}
         *
          * The relay uses GPIO 25. The ESP32 always stops the pump after 10
           * seconds, even if the Raspberry Pi disconnects after starting it.
            */
            #include <Arduino.h>
            #include <dht11.h>
            
            #define DHT11PIN       17
            #define LIGHTPIN       34
            #define WATERLEVELPIN  33
            #define RAINWATERPIN   35
            #define RELAYPIN       25
            
            const unsigned long SAMPLE_INTERVAL_MS = 60000UL;
            const unsigned long PUMP_MAX_RUN_MS = 10000UL;
            const float ADC_FULL_SCALE = 4095.0;
            const char* POSITION = "zone-2-canopy";
            
            // Set this to true if your relay activates when GPIO 25 is LOW.
            // Set it to false if the relay activates when GPIO 25 is HIGH.
            const bool RELAY_ACTIVE_LOW = false;
            const uint8_t PUMP_ON_LEVEL = RELAY_ACTIVE_LOW ? LOW : HIGH;
            const uint8_t PUMP_OFF_LEVEL = RELAY_ACTIVE_LOW ? HIGH : LOW;
            
            dht11 DHT11;
            unsigned long lastSampleMs = 0;
            unsigned long pumpStartedMs = 0;
            bool pumpOn = false;
            String inputLine;
            
            float percentOfFullScale(int raw) {
              float percent = (raw / ADC_FULL_SCALE) * 100.0;
                if (percent < 0.0) return 0.0;
                  if (percent > 100.0) return 100.0;
                    return percent;
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
                                    Serial.print("{\"node\":\"esp32\",\"pump\":\"");
                                      Serial.print(pumpOn ? "on" : "off");
                                        Serial.print("\",\"reason\":\"");
                                          Serial.print(reason);
                                            Serial.println("\"}");
                                            }
                                            
                                            void setPump(bool turnOn, const char* reason) {
                                              // Repeated keepalive commands must not restart the 10-second timer.
                                                if (turnOn && !pumpOn) {
                                                    pumpStartedMs = millis();
                                                      }
                                                      
                                                        digitalWrite(RELAYPIN, turnOn ? PUMP_ON_LEVEL : PUMP_OFF_LEVEL);
                                                          pumpOn = turnOn;
                                                            reportPump(reason);
                                                            }
                                                            
                                                            void handleCommand(String command) {
                                                              command.trim();
                                                                command.toLowerCase();
                                                                
                                                                  // Accept both simple serial commands and the JSON sent by farm/esp_link.py.
                                                                    String compact = command;
                                                                      compact.replace(" ", "");
                                                                      
                                                                        bool jsonPumpCommand = compact.indexOf("\"cmd\":\"pump\"") >= 0;
                                                                          bool requestOn = compact.indexOf("\"state\":\"on\"") >= 0;
                                                                            bool requestOff = compact.indexOf("\"state\":\"off\"") >= 0;
                                                                            
                                                                              if (command == "pump_on" || (jsonPumpCommand && requestOn)) {
                                                                                  setPump(true, "command");
                                                                                    } else if (command == "pump_off" || (jsonPumpCommand && requestOff)) {
                                                                                        setPump(false, "command");
                                                                                          } else if (command == "pump_status") {
                                                                                              reportPump("status_request");
                                                                                                } else if (command.length() > 0) {
                                                                                                    Serial.print("{\"node\":\"esp32\",\"error\":\"unknown command\"}");
                                                                                                        Serial.println();
                                                                                                          }
                                                                                                          }
                                                                                                          
                                                                                                          void readCommands() {
                                                                                                            while (Serial.available() > 0) {
                                                                                                                char received = (char)Serial.read();
                                                                                                                
                                                                                                                    if (received == '\n' || received == '\r') {
                                                                                                                          if (inputLine.length() > 0) {
                                                                                                                                  handleCommand(inputLine);
                                                                                                                                          inputLine = "";
                                                                                                                                                }
                                                                                                                                                    } else if (inputLine.length() < 200) {
                                                                                                                                                          inputLine += received;
                                                                                                                                                              }
                                                                                                                                                                }
                                                                                                                                                                }
                                                                                                                                                                
                                                                                                                                                                void sampleAndReport() {
                                                                                                                                                                  int dhtResult = DHT11.read(DHT11PIN);
                                                                                                                                                                  
                                                                                                                                                                    if (dhtResult == DHTLIB_OK) {
                                                                                                                                                                        emitReading("air_temperature", (float)DHT11.temperature);
                                                                                                                                                                            emitReading("humidity", (float)DHT11.humidity);
                                                                                                                                                                              } else {
                                                                                                                                                                                  Serial.print("{\"node\":\"esp32\",\"error\":\"DHT11 read failed, code ");
                                                                                                                                                                                      Serial.print(dhtResult);
                                                                                                                                                                                          Serial.println("\"}");
                                                                                                                                                                                            }
                                                                                                                                                                                            
                                                                                                                                                                                              emitReading("light", percentOfFullScale(analogRead(LIGHTPIN)));
                                                                                                                                                                                                emitReading("water_level", percentOfFullScale(analogRead(WATERLEVELPIN)));
                                                                                                                                                                                                  emitReading("rainfall", percentOfFullScale(analogRead(RAINWATERPIN)));
                                                                                                                                                                                                  }
                                                                                                                                                                                                  
                                                                                                                                                                                                  void enforcePumpSafety() {
                                                                                                                                                                                                    if (pumpOn && millis() - pumpStartedMs >= PUMP_MAX_RUN_MS) {
                                                                                                                                                                                                        setPump(false, "safety_timeout");
                                                                                                                                                                                                          }
                                                                                                                                                                                                          }
                                                                                                                                                                                                          
                                                                                                                                                                                                          void setup() {
                                                                                                                                                                                                            // Must match NODE_SERIAL_BAUD in farm/config.py.
                                                                                                                                                                                                              Serial.begin(9600);
                                                                                                                                                                                                              
                                                                                                                                                                                                                pinMode(DHT11PIN, INPUT);
                                                                                                                                                                                                                  pinMode(LIGHTPIN, INPUT);
                                                                                                                                                                                                                    pinMode(WATERLEVELPIN, INPUT);
                                                                                                                                                                                                                      pinMode(RAINWATERPIN, INPUT);
                                                                                                                                                                                                                      
                                                                                                                                                                                                                        pinMode(RELAYPIN, OUTPUT);
                                                                                                                                                                                                                          digitalWrite(RELAYPIN, PUMP_OFF_LEVEL);
                                                                                                                                                                                                                          
                                                                                                                                                                                                                            inputLine.reserve(200);
                                                                                                                                                                                                                              delay(1500);
                                                                                                                                                                                                                              
                                                                                                                                                                                                                                Serial.println("{\"node\":\"esp32\",\"status\":\"ready\"}");
                                                                                                                                                                                                                                  reportPump("boot");
                                                                                                                                                                                                                                  
                                                                                                                                                                                                                                    // Produce the first sensor readings immediately.
                                                                                                                                                                                                                                      lastSampleMs = millis() - SAMPLE_INTERVAL_MS;
                                                                                                                                                                                                                                      }
                                                                                                                                                                                                                                      
                                                                                                                                                                                                                                      void loop() {
                                                                                                                                                                                                                                        readCommands();
                                                                                                                                                                                                                                          enforcePumpSafety();
                                                                                                                                                                                                                                          
                                                                                                                                                                                                                                            unsigned long now = millis();
                                                                                                                                                                                                                                              if (now - lastSampleMs >= SAMPLE_INTERVAL_MS) {
                                                                                                                                                                                                                                                  lastSampleMs = now;
                                                                                                                                                                                                                                                      sampleAndReport();
                                                                                                                                                                                                                                                        }
                                                                                                                                                                                                                                                        }
                                                                                                                                                                                                                                                        