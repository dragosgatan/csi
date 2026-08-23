#include <WiFi.h>
#include <WiFiUdp.h>
#include <esp_now.h>
#include <esp_wifi.h>
#include "../secrets.h"

#define CHANNEL   11
#define NODE_ID   0 

const int   TX_PACKETS_PER_SEC = 20; 
uint8_t broadcastMac[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
uint8_t selfMac[6];
char    selfMacHex[13];   // 12 hex chars + null terminator

WiFiUDP udp;
char payload[1400];
uint32_t txSeq = 0;

volatile uint32_t rawCount = 0;
volatile uint32_t matchCount = 0;

void macToHex(const uint8_t *mac, char *out) {
  snprintf(out, 13, "%02X%02X%02X%02X%02X%02X",
           mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
}

void onCsi(void *ctx, wifi_csi_info_t *info) {
  rawCount++;
  if (!info->buf || info->len <= 0) return;
  if (memcmp(info->mac, selfMac, 6) == 0) return;  // ignore our own transmissions
  matchCount++;

  char txMacHex[13];
  macToHex(info->mac, txMacHex);

  // header: self_mac,tx_mac,timestamp,rssi,len,  then raw binary CSI bytes
  int pos = snprintf(payload, sizeof(payload), "%s,%s,%lu,%d,%d,",
                      selfMacHex, txMacHex, millis(),
                      info->rx_ctrl.rssi, info->len);

  if (pos + info->len >= (int)sizeof(payload)) return;  // safety guard
  memcpy(payload + pos, info->buf, info->len);
  pos += info->len;

  udp.beginPacket(LAPTOP_IP, LAPTOP_PORT);
  udp.write((const uint8_t*)payload, pos);
  udp.endPacket();
}

void onSniff(void *buf, wifi_promiscuous_pkt_type_t type) {}

void onEspNowSent(const wifi_tx_info_t *info, esp_now_send_status_t status) {}

void setup() {
  Serial.begin(115200);
  delay(300);

  Serial.print("# node ");
  Serial.print(NODE_ID);
  Serial.print(" connecting to ");
  Serial.println(WIFI_SSID);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  while (WiFi.status() != WL_CONNECTED) {
    delay(300);
    Serial.print(".");
  }
  Serial.println();

  WiFi.macAddress(selfMac);
  macToHex(selfMac, selfMacHex);

  Serial.print("# connected, ip=");
  Serial.print(WiFi.localIP());
  Serial.print(" mac=");
  Serial.println(selfMacHex);
  Serial.println("# >>> record this node's MAC + physical position for NODE_POSITIONS <<<");

  udp.begin(LAPTOP_PORT);
  esp_wifi_set_channel(CHANNEL, WIFI_SECOND_CHAN_NONE);

  if (esp_now_init() != ESP_OK) {
    Serial.println("# esp_now init failed");
    while (true) delay(1000);
  }
  esp_now_register_send_cb(onEspNowSent);

  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, broadcastMac, 6);
  peer.channel = CHANNEL;
  peer.ifidx = WIFI_IF_STA;
  peer.encrypt = false;
  esp_now_add_peer(&peer);

  wifi_promiscuous_filter_t filter = {};
  filter.filter_mask = WIFI_PROMIS_FILTER_MASK_MGMT | WIFI_PROMIS_FILTER_MASK_DATA;
  esp_wifi_set_promiscuous(true);
  esp_wifi_set_promiscuous_filter(&filter);
  esp_wifi_set_promiscuous_rx_cb(onSniff);

  wifi_csi_config_t cfg = {};
  cfg.lltf_en = true;
  cfg.htltf_en = true;
  cfg.ltf_merge_en = true;
  cfg.channel_filter_en = true;
  esp_wifi_set_csi_config(&cfg);
  esp_wifi_set_csi_rx_cb(onCsi, NULL);
  esp_wifi_set_csi(true);

  Serial.println("# mesh node ready - transmitting and listening simultaneously");
}

void loop() {
  // own periodic broadcast
  static uint32_t lastTx = 0;
  uint32_t txIntervalMs = 1000 / TX_PACKETS_PER_SEC;
  if (millis() - lastTx >= txIntervalMs) {
    lastTx = millis();
    txSeq++;
    esp_now_send(broadcastMac, (uint8_t*)&txSeq, sizeof(txSeq));
  }

  // heartbeat
  static uint32_t lastBeat = 0;
  if (millis() - lastBeat >= 1000) {
    lastBeat = millis();
    Serial.printf("# heartbeat node=%d raw=%u match=%u\n", NODE_ID, rawCount, matchCount);
  }
}