#include <WiFi.h>
#include <WebServer.h>
#include <DHT.h>   // Library Manager -> "DHT sensor library" (Adafruit) install karo

// --- APNA WI-FI DETAILS YAHA DAAL ---
const char* ssid = "VINAY’s iPhone";
const char* password = "1234512345";

// --- RELAY TYPE ---
// Zyada tar relay module active-low hote hain (LOW = ON). Agar "ON" bhejne par bulb OFF ho
// aur "OFF" bhejne par ON (ya module ka jumper "H" par hai), toh isko false kar do.
#define RELAY_ACTIVE_LOW true

// --- RELAY PINS ---
const int lightPin = 26;  // Relay 1 - Light
const int lampPin = 27;   // Relay 2 - Lamp
const int fanPin = 14;    // Relay 3 - Fan

// --- SENSOR PINS ---
const int pirPin = 13;    // PIR (HC-SR501) OUT pin
#define DHTPIN 4          // DHT DATA pin
#define DHTTYPE DHT11     // DHT22 hai toh yaha DHT22 likh do

DHT dht(DHTPIN, DHTTYPE);
WebServer server(80);

bool lightOn = false, lampOn = false, fanOn = false;
float temperature = NAN, humidity = NAN;
unsigned long lastDhtRead = 0;

void setRelay(int pin, bool& state, bool on) {
  state = on;
  digitalWrite(pin, (on == RELAY_ACTIVE_LOW) ? LOW : HIGH);
}

// URL jaise /LIGHT=ON, /FAN=OFF, /ALL=ON
void handleCommand() {
  String uri = server.uri();
  bool on = uri.endsWith("=ON");
  bool valid = on || uri.endsWith("=OFF");

  if (valid && (uri.startsWith("/LIGHT=") || uri.startsWith("/ALL="))) setRelay(lightPin, lightOn, on);
  if (valid && (uri.startsWith("/LAMP=") || uri.startsWith("/ALL="))) setRelay(lampPin, lampOn, on);
  if (valid && (uri.startsWith("/FAN=") || uri.startsWith("/ALL="))) setRelay(fanPin, fanOn, on);

  if (!valid) {
    server.send(404, "text/plain", "Unknown command");
    return;
  }
  Serial.println("Command: " + uri);
  server.send(200, "text/plain", "OK");
}

// Python dashboard ye JSON padhta hai (Node-RED ke through)
void handleStatus() {
  String json = "{";
  json += "\"pir\":" + String(digitalRead(pirPin) == HIGH ? 1 : 0);
  json += ",\"temp\":" + (isnan(temperature) ? String("null") : String(temperature, 1));
  json += ",\"humidity\":" + (isnan(humidity) ? String("null") : String(humidity, 1));
  json += ",\"light\":" + String(lightOn ? 1 : 0);
  json += ",\"lamp\":" + String(lampOn ? 1 : 0);
  json += ",\"fan\":" + String(fanOn ? 1 : 0);
  json += "}";
  server.send(200, "application/json", json);
}

void setup() {
  Serial.begin(115200);

  pinMode(lightPin, OUTPUT);
  pinMode(lampPin, OUTPUT);
  pinMode(fanPin, OUTPUT);
  pinMode(pirPin, INPUT);

  // Shuru me sab OFF
  setRelay(lightPin, lightOn, false);
  setRelay(lampPin, lampOn, false);
  setRelay(fanPin, fanOn, false);

  dht.begin();

  Serial.print("Connecting to WiFi");
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi Connected!");
  Serial.print("ESP32 IP Address: ");
  Serial.println(WiFi.localIP()); // <--- YE IP NODE-RED FLOW ("Set ESP32 IP" node) MEIN UPDATE KAR LENA

  server.on("/STATUS", handleStatus);
  server.onNotFound(handleCommand);
  server.begin();
}

void loop() {
  server.handleClient();

  // DHT11 ko 2 second se jaldi mat padho
  if (millis() - lastDhtRead > 2000) {
    lastDhtRead = millis();
    float t = dht.readTemperature();
    float h = dht.readHumidity();
    if (!isnan(t)) temperature = t;
    if (!isnan(h)) humidity = h;
  }

  // Wi-Fi gaya toh wapas jodo
  if (WiFi.status() != WL_CONNECTED) {
    WiFi.reconnect();
    delay(500);
  }
}
