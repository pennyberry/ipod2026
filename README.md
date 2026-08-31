# ipod2026

iPod music player UI - running on Adafruit Metro ESP32-S3 (CircuitPython) along with some additional adafruit hardware - using CircuitPython

- Adafruit Metro ESP32-S3
- Sharp 400x240 memory display
- TLV320DAC3100 I2S DAC (headphones)
- Quad rotary encoder breakout on Stemma QT
- Lifepo4 battery with jsp connector
- MicroSD card
- Jellyfin music server over WiFi (HTTPS, Let's Encrypt)

## Hardware & Pinout

Wiring as built; GPIOs verified against the Metro ESP32-S3 board definition.

### TLV320DAC3100 I2S DAC ↔ ESP32
https://www.adafruit.com/product/6309

(Headphones only, speaker amp disabled)

| Pin | Connection |
|-----|-----------|
| VIN | 3V3 |
| GND | GND |
| SCL | SCL (shared I2C bus; same pins as STEMMA QT) |
| SDA | SDA |
| DIN | A2 (GPIO16) |
| WSEL | A1 (GPIO15) |
| BCK | A0 (GPIO14) |
| MCLK | D4 (GPIO4) – feeds 15 MHz PWM clock for low-noise PLL lock |
| RST | D12 (GPIO12) – reset toggle (low→high) MUST happen before any I2S use |

**Note:** Headphone mixer trim is set to -15.5 dB in audio.py; dac_volume is the fader.

### Sharp 400x240 Display ↔ ESP32
https://www.adafruit.com/product/4694

| Pin | Connection |
|-----|-----------|
| VIN | 3.3–5V |
| GND | GND |
| SCLK | SCK (GPIO39) |
| MOSI | MOSI (GPIO42) |
| CS | D6 (GPIO6) |

Shares the board SPI bus with the SD card below.

### Adafruit I2C Quad Rotary Encoder Breakout ↔ ESP32

https://www.adafruit.com/product/5752

| Pin | Connection |
|-----|-----------|
| Stemma QT | Stemma QT |


- (SCL=GPIO48, SDA=GPIO47)
- One seesaw chip @0x49 carries all 4 knobs, their buttons, and 4 NeoPixels
- Encoders: ch 0–3

### lifepo4 battery with JSP connector ↔ ESP32

| Pin | Connection |
|-----|-----------|
| battery positive/negative | JST connector (**DOUBLE CHECK POLARITY!**) |

- 3.7V Lifepo4
- Chip reports 0–100% SoC over I2C at addr 0x36 (no divider or chemistry table needed)

### MicroSD Card (Onboard Slot, Board SPI)

Shares the SPI bus with theS display; code reuses the same board.SPI() singleton (a second SPI object on the same pins raises pin-conflict). Bus is only locked per-transaction, so they coexist.

- **Mounted:** read-browse at /sd
- **Browsed from:** Settings → "SD files"

## CircuitPython Libraries

install circuitpython on your esp32 by following this guide:
- https://learn.adafruit.com/circuitpython-with-esp32-quick-start/installing-circuitpython

you will be able to plugin your esp32 to your pc and drop files to the machine after this is completed. you can place all the files in the /code directory into the root of the esp32. you will need to load the library files below into the /lib/ folder as well

these individual libraries

- adafruit_max1704x.mpy
- adafruit_sdcard.mpy
- adafruit_sharpmemorydisplay.mpy
- adafruit_tlv320.mpy
- bdf2adafruit.py
- gfx.mpy

these libraries

- adafruit_bitmap_font
- adafruit_bus_device
- adafruit_display_text
- adafruit_gfx
- adafruit_register
- adafruit_seesaw

reference to libraries:
- https://github.com/adafruit/Adafruit_MAX1704X
- https://circuitpython.org/libraries
- https://github.com/adafruit/Adafruit_CircuitPython_Bundle/releases/download/20260827/adafruit-circuitpython-bundle-10.x-mpy-20260827.zip

