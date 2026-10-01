#include <WiFi.h>

// --- APNA WI-FI DETAILS YAHA DAAL ---
const char* ssid = "VINAY’s iPhone";
const char* password = "1234512345";

const int lightPin = 26;  // Relay 1
const int lampPin = 27;   // Relay 2
const int socketPin = 14; // Relay 3

WiFiServer server(80);

void setup() {
  Serial.begin(115200);

  pinMode(lightPin, OUTPUT);
  pinMode(lampPin, OUTPUT);
  pinMode(socketPin, OUTPUT);

  // Relay module active-low hai, isliye shuru me HIGH (OFF) rakhenge
  digitalWrite(lightPin, HIGH);
  digitalWrite(lampPin, HIGH);
  digitalWrite(socketPin, HIGH);

  Serial.print("Connecting to WiFi");
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println("\nWiFi Connected!");
  Serial.print("ESP32 IP Address: ");
  Serial.println(WiFi.localIP()); // <--- YE IP NODE-RED MEIN UPDATE KAR LENA

  server.begin();
}

void loop() {
  WiFiClient client = server.available();

  if (client) {
    String request = client.readStringUntil('\r');
    client.flush();

    // LOW = ON (Relay ON), HIGH = OFF (Relay OFF)
    if (request.indexOf("/ALL=ON") != -1) {
      digitalWrite(lightPin, LOW);
      digitalWrite(lampPin, LOW);
      digitalWrite(socketPin, LOW);
      Serial.println("Command: SAB ON");
    }
    if (request.indexOf("/ALL=OFF") != -1) {
      digitalWrite(lightPin, HIGH);
      digitalWrite(lampPin, HIGH);
      digitalWrite(socketPin, HIGH);
      Serial.println("Command: SAB OFF");
    }

    // Node-RED ko reply bhejo
    client.println("HTTP/1.1 200 OK\nContent-type:text/html\n\n");
    
    // Connection close karo taaki Node-RED hang na ho
    delay(1);
    client.stop(); 
    Serial.println("Client disconnected. Node-RED is free now.");
  }
}