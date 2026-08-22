#include <WiFi.h>
#include <esp_wifi.h>
#include <math.h>

#define CHANNEL   6

// mac printed by the tx board on boot
uint8_t txMac[6] = {0x24, 0x6F, 0x28, 0x00, 0x00, 0x00};

#define SC_FIRST  6
#define SC_LAST   58
#define ALPHA     0.03    // baseline speed
#define BETA      0.25    // output smoothing
#define THRESHOLD 0.22
#define WARMUP    150

float baseline[64];
bool haveBaseline = false;
volatile float level = 0;
volatile uint32_t count = 0;

void onCsi(void *ctx, wifi_csi_info_t *info) {
  const int8_t *csi = info->buf;
  if (!csi || info->len < (SC_LAST + 1) * 2) return;
  if (memcmp(info->mac, txMac, 6) != 0) return;

  float sum = 0;
  int n = 0;
  for (int i = SC_FIRST; i <= SC_LAST; i++) {
    float im = csi[i * 2];
    float re = csi[i * 2 + 1];
    float amp = sqrtf(re * re + im * im);
    if (!haveBaseline) {
      baseline[i] = amp;
      continue;
    }
    sum += fabsf(amp - baseline[i]) / (baseline[i] + 1.0);
    baseline[i] += ALPHA * (amp - baseline[i]);
    n++;
  }

  if (!haveBaseline) {
    haveBaseline = true;
    return;
  }
  level += BETA * (sum / n - level);
  count++;
}

void onSniff(void *buf, wifi_promiscuous_pkt_type_t type) {}

void setup() {
  Serial.begin(115200);
  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  esp_wifi_set_channel(CHANNEL, WIFI_SECOND_CHAN_NONE);
  esp_wifi_set_promiscuous_filter(&(wifi_promiscuous_filter_t){WIFI_PROMIS_FILTER_MASK_DATA});
  esp_wifi_set_promiscuous_rx_cb(onSniff);
  esp_wifi_set_promiscuous(true);

  wifi_csi_config_t cfg = {};
  cfg.lltf_en = true;
  cfg.htltf_en = true;
  cfg.ltf_merge_en = true;
  cfg.channel_filter_en = true;

  esp_wifi_set_csi_config(&cfg);
  esp_wifi_set_csi_rx_cb(onCsi, NULL);
  esp_wifi_set_csi(true);
  Serial.println("rx ready");
}

void loop() {
  static uint32_t last = 0;
  if (millis() - last < 200) return;
  last = millis();

  float v = level;
  uint32_t c = count;
  if (c < WARMUP) {
    Serial.printf("calibrating %u/%u\n", c, WARMUP);
    return;
  }
  Serial.printf("%.3f %s\n", v, v > THRESHOLD ? "MOTION" : "still");
}
