# ----------------------------------------------------------------------------------
# Raspberry Pi Multi-Sensor Reader with BLE
# Project: Terra
# ----------------------------------------------------------------------------------

#!/usr/bin/env python3

import time
import json
import traceback
import serial
import os 
import serial.tools.list_ports 
from datetime import datetime

# --- PyBleno Python 3.11+ Compatibility Patch ---
# pybleno uses 'rU' mode in os.fdopen which was removed in Python 3.11.
# This intercepts that call and safely removes the 'U' flag on the fly.
_orig_fdopen = os.fdopen
def _patched_fdopen(fd, mode='r', *args, **kwargs):
    if isinstance(mode, str) and 'U' in mode:
        mode = mode.replace('U', '')
    return _orig_fdopen(fd, mode, *args, **kwargs)
os.fdopen = _patched_fdopen
# ------------------------------------------------

# Import necessary Blinka/CircuitPython libraries for DHT
from adafruit_blinka.microcontroller.bcm283x.pin import Pin
from adafruit_dht import DHT11, DHT22

# Import PyBleno for Bluetooth Low Energy
# Install via: pip3 install pybleno
from pybleno import Bleno, BlenoPrimaryService, Characteristic

# --- Configuration ---

# BLE Configuration
BLE_DEVICE_NAME = "terra-rpi"
# Remove dashes for pybleno
TARGET_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0".replace("-", "")
TARGET_CHARACTERISTIC_UUID = "12345678-1234-5678-1234-56789abcdef1".replace("-", "")

# DHT Sensor Configuration
DHT_PIN = Pin(17) 
DHT_TIMEOUT = 3.0 
SENSOR_TYPE = DHT11  

# DS18B20 Configuration
W1_DEVICE_PATH = '/sys/bus/w1/devices/'

# Serial Configuration for Moisture & pH Sensors
MOISTURE_SERIAL_PORT = '/dev/ttyUSB0' 
PH_SERIAL_PORT = '/dev/ttyUSB0' # Reverted back to ttyUSB0 as requested
SERIAL_BAUD_RATE = 9600
SERIAL_TIMEOUT = 3.0        

# Moisture Calibration
AIR_DRY_VALUE = 600   
FULL_WET_VALUE = 300  

# Initialize the DHT device
try:
    dhtDevice = SENSOR_TYPE(DHT_PIN)
except Exception as e:
    print(f"FATAL: Could not initialize DHT sensor on BCM 17: {e}")
    dhtDevice = None

# ----------------------------------------------------------------------------------
# BLE Characteristic & Service Setup
# ----------------------------------------------------------------------------------

class SensorDataCharacteristic(Characteristic):
    def __init__(self):
        Characteristic.__init__(self, {
            'uuid': TARGET_CHARACTERISTIC_UUID,
            'properties': ['read', 'notify'],
            'value': None
        })
        self._value = bytes("{}", 'utf-8')
        self._updateValueCallback = None

    def onReadRequest(self, offset, callback):
        callback(Characteristic.RESULT_SUCCESS, self._value)

    def onSubscribe(self, maxValueSize, updateValueCallback):
        print("BLE: Device subscribed to sensor notifications.")
        self._updateValueCallback = updateValueCallback

    def onUnsubscribe(self):
        print("BLE: Device unsubscribed.")
        self._updateValueCallback = None

    def update_data(self, json_str):
        self._value = bytes(json_str, 'utf-8')
        if self._updateValueCallback:
            self._updateValueCallback(self._value)

bleno = Bleno()
sensor_char = SensorDataCharacteristic()

def onStateChange(state):
    if state == 'poweredOn':
        print(f"BLE powered on. Advertising as '{BLE_DEVICE_NAME}'...")
        bleno.startAdvertising(BLE_DEVICE_NAME, [TARGET_SERVICE_UUID])
    else:
        bleno.stopAdvertising()

def onAdvertisingStart(error):
    if not error:
        bleno.setServices([
            BlenoPrimaryService({
                'uuid': TARGET_SERVICE_UUID,
                'characteristics': [sensor_char]
            })
        ])

bleno.on('stateChange', onStateChange)
bleno.on('advertisingStart', onAdvertisingStart)

# ----------------------------------------------------------------------------------
# Sensor Reading Functions
# ----------------------------------------------------------------------------------

def get_dht_data():
    if not dhtDevice:
        return {"status": "NOT_INITIALIZED"}
    try:
        temperature_c = dhtDevice.temperature
        humidity = dhtDevice.humidity
        if temperature_c is not None and humidity is not None:
            return {"status": "OK", "temperature_c": round(temperature_c, 1), "humidity": round(humidity, 1)}
        else:
            return {"status": "READ_FAILED"}
    except Exception as e:
        return {"status": "ERROR"}

def get_ds18b20_data():
    try:
        devices = [d for d in os.listdir(W1_DEVICE_PATH) if d.startswith('28-')]
        if not devices:
            return {"status": "NOT_FOUND"}
        
        device_folder = os.path.join(W1_DEVICE_PATH, devices[0])
        device_file = os.path.join(device_folder, 'w1_slave')

        with open(device_file, 'r') as f:
            lines = f.readlines()

        if lines[0].strip().endswith('YES'):
            temp_output = lines[1].split('=')[-1]
            return {"status": "OK", "temperature_c": round(float(temp_output) / 1000.0, 1)}
        else:
            return {"status": "READ_FAILED"}
    except Exception as e:
        return {"status": "ERROR"}

def calculate_moisture_percent(raw_reading):
    if AIR_DRY_VALUE <= FULL_WET_VALUE: return 0.0
    if raw_reading >= AIR_DRY_VALUE: return 0.0 
    if raw_reading <= FULL_WET_VALUE: return 100.0 
    moisture_range = AIR_DRY_VALUE - FULL_WET_VALUE
    relative_position = AIR_DRY_VALUE - raw_reading
    return round((relative_position / moisture_range) * 100.0, 1)

def get_moisture_data():
    try:
        ser = serial.Serial(MOISTURE_SERIAL_PORT, SERIAL_BAUD_RATE, timeout=SERIAL_TIMEOUT)
        ser.flush()
        if not ser.closed:
            _ = ser.readline()
        line = ser.readline().decode('utf-8').strip()
        ser.close()

        if line:
            raw_reading = int(line)
            return {"status": "OK", "moisture_percent": calculate_moisture_percent(raw_reading)}
        return {"status": "NO_RESPONSE"}
    except Exception as e:
        return {"status": "ERROR"}

def get_smoothed_ph():
    try:
        ser_ph = serial.Serial(PH_SERIAL_PORT, 9600, timeout=1)
        ser_ph.flush()
        readings = []
        for _ in range(20):
            if ser_ph.in_waiting > 0:
                line = ser_ph.readline().decode('utf-8').rstrip()
                if line.isdigit():
                    readings.append(int(line))
            time.sleep(0.01)
        ser_ph.close()

        if not readings:
            return None
            
        avg_adc = sum(readings) / len(readings)
        voltage = (avg_adc / 1023.0) * 5.0
        ph = (voltage / 5.0) * 14.0
        return round(ph, 2)
    except Exception as e:
        return None

# ----------------------------------------------------------------------------------
# Main Loop
# ----------------------------------------------------------------------------------

if __name__ == '__main__':
    print(f"--- Terra: Multi-Sensor BLE Station Initialized ---")
    
    # Start BLE Service
    bleno.start()

    try:
        while True:
            # 1. Read all sensors
            dht_data = get_dht_data()
            ds18b20_data = get_ds18b20_data()
            moisture_data = get_moisture_data()
            ph_value = get_smoothed_ph()

            # 2. Extract specific values for payload
            soil_temp = ds18b20_data.get('temperature_c') if ds18b20_data.get('status') == 'OK' else None
            soil_moisture = moisture_data.get('moisture_percent') if moisture_data.get('status') == 'OK' else None
            air_temp = dht_data.get('temperature_c') if dht_data.get('status') == 'OK' else None
            air_humidity = dht_data.get('humidity') if dht_data.get('status') == 'OK' else None

            # 3. Create Dashboard JSON 
            dashboard_payload = {
                "soil_temp": soil_temp,
                "soil_moisture": soil_moisture,
                "air_temp": air_temp,
                "air_humidity": air_humidity,
                "soil_ph": ph_value
            }
            
            json_output = json.dumps(dashboard_payload, indent=4)
            
            # 4. Update BLE Characteristic
            sensor_char.update_data(json.dumps(dashboard_payload))
            
            # 5. Print Detailed Status and Log to Terminal
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print("-" * 60)
            print(f"[{timestamp}] Sensor Data Log:")
            print(f"  > Soil Temp:     {soil_temp}°C" if soil_temp is not None else "  > Soil Temp:     -- (Error/None)")
            print(f"  > Soil Moisture: {soil_moisture}%" if soil_moisture is not None else "  > Soil Moisture: -- (Error/None)")
            print(f"  > Soil pH:       {ph_value}" if ph_value is not None else "  > Soil pH:       -- (Error/None)")
            print(f"  > Air Temp:      {air_temp}°C" if air_temp is not None else "  > Air Temp:      -- (Error/None)")
            print(f"  > Air Humidity:  {air_humidity}%" if air_humidity is not None else "  > Air Humidity:  -- (Error/None)")
            print("\nBroadcasting Payload via BLE:")
            print(json_output)
            
            # Update frequency
            time.sleep(5.0)

    except KeyboardInterrupt:
        print("\nScript stopped by user. Shutting down BLE...")
        bleno.stopAdvertising()
        bleno.disconnect()
        print("Done.")

    except Exception as e:
        print(f"\nFATAL CRITICAL ERROR: {e}")
        traceback.print_exc()