#!/usr/bin/env python3
#
# This is a full, self-contained Python script to read data from two types of sensors:
# 1. DHT Sensor (DHT11 or DHT22) for Temperature and Humidity.
# 2. DS18B20 Sensor for Temperature using the One-Wire protocol.
#
# Prerequisites:
# - Installation: pip3 install adafruit-circuitpython-dht
# - Configuration: One-Wire MUST be enabled via 'sudo raspi-config'.
#
# Wiring Checklist:
# - DS18B20 Data -> BCM 4 (Physical Pin 7), with 4.7kΩ pull-up resistor.
# - DHT Data -> BCM 17 (Physical Pin 11).
#

import time
import json
import traceback
import glob
# We need to import the Pin definition for Blinka compatibility
from adafruit_blinka.microcontroller.bcm283x.pin import Pin 
import adafruit_dht
from adafruit_dht import DHT11, DHT22 # Import both sensor classes

# --- Configuration ---
# BCM 17 is chosen for DHT to avoid conflict with the default One-Wire pin BCM 4.
DHT_PIN = Pin(17) 
SENSOR_ID = "RPI_SENSOR_1" 

# --- CRITICAL: CHOOSE THE CORRECT SENSOR TYPE ---
# The primary reason for the "DHT sensor not found" error is selecting the wrong class.
# UNCOMMENT ONE LINE below that matches your sensor:
# The blue sensor is DHT11, the white sensor is DHT22 (AM2302).

SENSOR_TYPE = DHT11  # <-- CHECK THIS: Is this correct for your sensor? (Currently set to DHT11)
# SENSOR_TYPE = DHT22 # <-- Uncomment this if you have a DHT22 (white sensor)

# --- Initialization ---
dhtDevice = None
try:
    # Initialize the DHT device with the selected type and pin
    dhtDevice = SENSOR_TYPE(DHT_PIN)
    print(f"✅ {SENSOR_TYPE.__name__} sensor initialized on BCM {DHT_PIN.id}")
except ValueError as e:
    # This usually indicates a setup issue or a conflict
    print(f"⚠️ {SENSOR_TYPE.__name__} Initialization Error: {e}")

def get_dht_data():
    """Reads DHT sensor data, handles common errors, and returns a dictionary."""
    if dhtDevice is None:
        # If initialization failed, skip read attempt
        return {"status": "DHT_INIT_FAILED", "message": "Check the SENSOR_TYPE setting and BCM 17 wiring."}
        
    try:
        # Read the sensor data
        temperature_c = dhtDevice.temperature
        humidity = dhtDevice.humidity

        # Check if readings are valid (sometimes they return None)
        if temperature_c is not None and humidity is not None:
            # Data is valid, construct the dictionary
            return {
                "temperature_c": round(temperature_c, 1),
                "temperature_f": round(temperature_c * (9 / 5) + 32, 1),
                "humidity": round(humidity, 1),
                "status": "OK"
            }
        else:
            # Data read failed (e.g., checksum error - very common)
            return {"status": "READ_FAILED", "message": "Sensor data was 'None', retry needed."}

    except RuntimeError as error:
        # Specific hardware timing error (common with DHT, safe to ignore and retry)
        return {"status": "RUNTIME_ERROR", "message": str(error)}
        
    except Exception as e:
        # Catch any other unexpected errors
        traceback.print_exc()
        return {"status": "UNEXPECTED_ERROR", "message": str(e)}

def get_ds18b20_data():
    """Reads DS18B20 sensor data from the One-Wire file system."""
    
    # 1. Find the sensor file path 
    base_dir = '/sys/bus/w1/devices/'
    # Finds the folder that starts with '28-' (the DS18B20 family code)
    device_folder = glob.glob(base_dir + '28*')
    
    if not device_folder:
        return {"status": "DS18B20_NOT_FOUND", "message": "Ensure One-Wire is enabled and BCM 4 wiring/resistor is correct."}

    device_file = device_folder[0] + '/w1_slave'
    
    # 2. Read and parse the data
    try:
        # Attempt to read the file contents
        with open(device_file, 'r') as f:
            lines = f.readlines()

        # Check if the CRC is OK ('YES')
        if lines[0].strip()[-3:] != 'YES':
             # Re-read if CRC check failed
             time.sleep(0.2)
             with open(device_file, 'r') as f:
                lines = f.readlines()
                if lines[0].strip()[-3:] != 'YES':
                    return {"status": "DS18B20_CRC_ERROR", "message": "CRC check failed after retry."}


        temp_line = lines[1]
        equal_pos = temp_line.find('t=')
        
        if equal_pos != -1:
            temp_string = temp_line[equal_pos+2:]
            temp_c = float(temp_string) / 1000.0
            
            # Success
            return {
                "temperature_c": round(temp_c, 1),
                "temperature_f": round(temp_c * (9 / 5) + 32, 1),
                "status": "OK"
            }
        else:
            # Temperature parsing failed
            return {"status": "DS18B20_PARSE_ERROR", "message": "Could not find 't=' in sensor file data."}

    except Exception as e:
        return {"status": "DS18B20_READ_ERROR", "message": str(e)}


if __name__ == '__main__':
    print(f"--- Raspberry Pi Multi-Sensor Station Initialized ---")
    print(f"DHT Sensor Type: {SENSOR_TYPE.__name__} | Data Pin: BCM {DHT_PIN.id} (Physical Pin 11)")
    print(f"DS18B20 Sensor uses One-Wire bus (Data Pin: BCM 4 / Physical Pin 7).")
    
    try:
        while True:
            # 1. Read DHT Sensor
            dht_data = get_dht_data()
            
            # 2. Read DS18B20 Sensor
            ds_data = get_ds18b20_data()
            
            # 3. Combine results into a single payload
            combined_payload = {
                "id": SENSOR_ID,
                "timestamp": time.time(),
                "sensors": {
                    "dht_sensor": dht_data,
                    "ds18b20": ds_data
                }
            }
            
            json_output = json.dumps(combined_payload, indent=2)
            
            print("-" * 50)
            
            # Provide clear feedback on which sensors passed/failed
            dht_ok = dht_data.get('status') == "OK"
            ds_ok = ds_data.get('status') == "OK"
            
            if dht_ok and ds_ok:
                print(f"✅ All Sensors Read Successfully:")
            else:
                print(f"❌ Read with Errors/Warnings (DS18B20 Status: {ds_data.get('status')}, DHT Status: {dht_data.get('status')}):")
                
            print(json_output)

            # Wait 5 seconds between readings
            time.sleep(5.0)

    except KeyboardInterrupt:
        print("\nScript stopped by user.")
        # Clean up the DHT sensor connection
        if dhtDevice is not None:
            dhtDevice.exit() 
