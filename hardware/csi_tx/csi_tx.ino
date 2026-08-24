/* archived file not used anywhere */


#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>

// 88:13:BF:0D:D0:14

#define CHANNEL 11

uint8_t broadcast[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
uint32_t seq = 0;

volatile uint32_t txOk = 0;
volatile uint32_t txFail = 0;

void onSent(const wifi_tx_info_t *info, esp_now_send_status_t status) {
  if (status == ESP_NOW_SEND_SUCCESS) txOk++;
  else txFail++;
}

void setup() {
  Serial.begin(115200);
  Serial.println("Setup started");
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  WiFi.setSleep(false);

  esp_err_t chErr = esp_wifi_set_channel(CHANNEL, WIFI_SECOND_CHAN_NONE);
  Serial.printf("set_channel: %s\n", esp_err_to_name(chErr));

  if (esp_now_init() != ESP_OK) {
    Serial.println("esp_now init failed");
    while (true) delay(1000);
  }
  esp_now_register_send_cb(onSent);

  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, broadcast, 6);
  peer.channel = CHANNEL;
  peer.ifidx = WIFI_IF_STA;
  peer.encrypt = false;
  esp_err_t peerErr = esp_now_add_peer(&peer);
  Serial.printf("add_peer: %s\n", esp_err_to_name(peerErr));
  esp_now_rate_config_t rate = {};
  rate.phymode = WIFI_PHY_MODE_HT20;
  rate.rate = WIFI_PHY_RATE_MCS0_LGI;
  rate.ersu = false;
  rate.dcm = false;
  esp_err_t rateErr = esp_now_set_peer_rate_config(broadcast, &rate);
  Serial.printf("set_rate: %s\n", esp_err_to_name(rateErr));

}

void loop() {
  static uint32_t lastReport = 0;
  static uint32_t sendErr = 0;
  seq++;
  if (esp_now_send(broadcast, (uint8_t *)&seq, sizeof(seq)) != ESP_OK) sendErr++;


  if (millis() - lastReport >= 1000) {
    lastReport = millis();
    uint8_t ch;
    wifi_second_chan_t sec;
    esp_wifi_get_channel(&ch, &sec);
    Serial.printf("seq=%u ok=%u fail=%u senderr=%u ch=%u\n", seq, txOk, txFail, sendErr, ch);
  }
  delay(10);
}
