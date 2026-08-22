#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>

#define CHANNEL 6

uint8_t broadcast[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
uint32_t seq = 0;

void setup() {
  Serial.begin(9600);
  Serial.println("Setup started");
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  WiFi.setSleep(false);
  esp_wifi_set_channel(CHANNEL, WIFI_SECOND_CHAN_NONE);

  if (esp_now_init() != ESP_OK) {
    Serial.println("esp_now init failed");
    while (true) delay(1000);
  }

  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, broadcast, 6);
  peer.channel = CHANNEL;
  peer.ifidx = WIFI_IF_STA;
  peer.encrypt = false;
  esp_now_add_peer(&peer);

  // Serial.print("tx mac ");
  // Serial.println(WiFi.macAddress());
}

void loop() {
  seq++;
  esp_now_send(broadcast, (uint8_t *)&seq, sizeof(seq));
  Serial.print("tx mac: "); Serial.println(WiFi.macAddress());
  delay(10);
}
