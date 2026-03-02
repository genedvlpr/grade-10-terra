# ----------------------------------------------------------------------------------
# Raspberry Pi Multi-Sensor Wi-Fi API Server
# Project: Terra
# ----------------------------------------------------------------------------------

#!/usr/bin/env python3

import time
import json
import traceback
import serial
import os 
import threading
from datetime import datetime
from flask import Flask, jsonify

# Import necessary Blinka/CircuitPython libraries for DHT
from adafruit_blinka.microcontroller.bcm283x.pin import Pin
from adafruit_dht import DHT11, DHT22

# --- Configuration ---

# API Configuration
API_PORT = 5000

# DHT Sensor Configuration
DHT_PIN = Pin(17) 
DHT_TIMEOUT = 3.0 
SENSOR_TYPE = DHT11  

# DS18B20 Configuration
W1_DEVICE_PATH = '/sys/bus/w1/devices/'

# Serial Configuration for Moisture & pH Sensors
MOISTURE_SERIAL_PORT = '/dev/ttyUSB0' 
PH_SERIAL_PORT = '/dev/ttyUSB0' 
SERIAL_BAUD_RATE = 9600
SERIAL_TIMEOUT = 3.0        

# Moisture Calibration
AIR_DRY_VALUE = 600   
FULL_WET_VALUE = 300  

# Global variable to store the latest sensor readings
latest_sensor_data = {
    "soil_temp": None,
    "soil_moisture": None,
    "air_temp": None,
    "air_humidity": None,
    "soil_ph": None,
    "last_updated": None
}

# Initialize the DHT device
try:
    dhtDevice = SENSOR_TYPE(DHT_PIN)
except Exception as e:
    print(f"FATAL: Could not initialize DHT sensor on BCM 17: {e}")
    dhtDevice = None

# Initialize Flask App
app = Flask(__name__)

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
# Background Sensor Loop
# ----------------------------------------------------------------------------------
def sensor_update_loop():
    global latest_sensor_data
    
    print("--- Background Sensor Loop Started ---")
    
    while True:
        try:
            # 1. Read all sensors sequentially
            dht_data = get_dht_data()
            ds18b20_data = get_ds18b20_data()
            moisture_data = get_moisture_data()
            ph_value = get_smoothed_ph()

            # 2. Update the global dictionary
            latest_sensor_data["soil_temp"] = ds18b20_data.get('temperature_c') if ds18b20_data.get('status') == 'OK' else None
            latest_sensor_data["soil_moisture"] = moisture_data.get('moisture_percent') if moisture_data.get('status') == 'OK' else None
            latest_sensor_data["air_temp"] = dht_data.get('temperature_c') if dht_data.get('status') == 'OK' else None
            latest_sensor_data["air_humidity"] = dht_data.get('humidity') if dht_data.get('status') == 'OK' else None
            latest_sensor_data["soil_ph"] = ph_value
            
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            latest_sensor_data["last_updated"] = timestamp

            # 3. Print to terminal
            print("-" * 60)
            print(f"[{timestamp}] Sensors Updated:")
            print(f"  > Soil Temp:     {latest_sensor_data['soil_temp']}°C")
            print(f"  > Soil Moisture: {latest_sensor_data['soil_moisture']}%")
            print(f"  > Soil pH:       {latest_sensor_data['soil_ph']}")
            print(f"  > Air Temp:      {latest_sensor_data['air_temp']}°C")
            print(f"  > Air Humidity:  {latest_sensor_data['air_humidity']}%")
            
        except Exception as e:
            print(f"Error reading sensors: {e}")
            
        time.sleep(5.0)

# ----------------------------------------------------------------------------------
# API Routes
# ----------------------------------------------------------------------------------

@app.route('/api/sensors', methods=['GET'])
def get_sensors():
    """Returns the latest sensor data as JSON."""
    return jsonify(latest_sensor_data)

# ----------------------------------------------------------------------------------
# Main Execution
# ----------------------------------------------------------------------------------

if __name__ == '__main__':
    print(f"--- Terra: Multi-Sensor Wi-Fi API Initialized ---")
    
    # Start the sensor reading loop in a separate background thread
    sensor_thread = threading.Thread(target=sensor_update_loop, daemon=True)
    sensor_thread.start()

    # Start the Flask web server (host='0.0.0.0' exposes it to your local network)
    # You do NOT need sudo to run this script!
    try:
        app.run(host='0.0.0.0', port=API_PORT, debug=False)
    except KeyboardInterrupt:
        print("\nServer shutting down.")