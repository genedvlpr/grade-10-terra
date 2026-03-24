# ----------------------------------------------------------------------------------
# Raspberry Pi Multi-Sensor Reader
# Reads:
# 1. DHT11/DHT22 (Temperature & Humidity) via BCM 17
# 2. DS18B20 (Temperature) via One-Wire (BCM 4)
# 3. Capacitive Soil Moisture (Percentage) via Arduino Serial (/dev/ttyUSB0)
# ----------------------------------------------------------------------------------

#!/usr/bin/env python3

import time
import json
import traceback
import serial
import os 
import serial.tools.list_ports 

# Import necessary Blinka/CircuitPython libraries for DHT
from adafruit_blinka.microcontroller.bcm283x.pin import Pin
from adafruit_dht import DHT11, DHT22

# --- Configuration ---

# DHT Sensor Configuration
# BCM 17 corresponds to Physical Pin 11
DHT_PIN = Pin(17) 
DHT_TIMEOUT = 3.0 
SENSOR_TYPE = DHT11  # <-- Change to DHT22 if you have the white sensor

# DS18B20 Configuration
W1_DEVICE_PATH = '/sys/bus/w1/devices/'

# Arduino Serial Configuration for Moisture Sensor
SERIAL_PORT = '/dev/ttyUSB0' # <-- CHECK THIS PORT if still getting SERIAL_ERROR
SERIAL_BAUD_RATE = 9600
SERIAL_TIMEOUT = 3.0        

# --- MOISTURE CALIBRATION (CRITICAL: TUNE THESE VALUES) ---
# Raw values are typically 0-1023. Lower raw reading = WET.
# You MUST replace these examples with YOUR sensor's actual readings for 0% and 100%.
AIR_DRY_VALUE = 600   # Raw reading when sensor is suspended in air (0% moisture)
FULL_WET_VALUE = 300  # Raw reading when sensor is submerged in water (100% moisture)

SENSOR_ID = "RPI_SENSOR_1" 

# Initialize the DHT device
try:
    dhtDevice = SENSOR_TYPE(DHT_PIN)
except Exception as e:
    print(f"FATAL: Could not initialize DHT sensor on BCM 17: {e}")
    dhtDevice = None

# ----------------------------------------------------------------------------------
# Sensor Reading Functions
# ----------------------------------------------------------------------------------

def get_dht_data():
    """Reads DHT sensor and returns data as a dictionary."""
    if not dhtDevice:
        return {"status": "NOT_INITIALIZED", "message": "DHT Device initialization failed"}
    
    try:
        # Attempt to read the sensor data
        temperature_c = dhtDevice.temperature
        humidity = dhtDevice.humidity

        if temperature_c is not None and humidity is not None:
            return {
                "status": "OK",
                "temperature_c": round(temperature_c, 1),
                "temperature_f": round(temperature_c * (9 / 5) + 32, 1),
                "humidity": round(humidity, 1)
            }
        else:
            # Data read failed (often a checksum or timing error)
            return {"status": "READ_FAILED", "message": "DHT returned None values (try again)"}

    except RuntimeError as error: 
        # This is the "DHT sensor not found, check wiring" error.
        # FIX: Ensure 10kOhm pull-up resistor is installed on the data line!
        return {"status": "RUNTIME_ERROR", "message": str(error)}
    except Exception as e:
        traceback.print_exc()
        return {"status": "UNEXPECTED_ERROR", "message": str(e)}

def get_ds18b20_data():
    """Reads DS18B20 sensor via One-Wire file system."""
    try:
        devices = [d for d in os.listdir(W1_DEVICE_PATH) if d.startswith('28-')]
        if not devices:
            return {"status": "DS18B20_NOT_FOUND", "message": "No '28-' devices found. Check wiring or One-Wire setup."}
        
        device_folder = os.path.join(W1_DEVICE_PATH, devices[0])
        device_file = os.path.join(device_folder, 'w1_slave')

        with open(device_file, 'r') as f:
            lines = f.readlines()

        if lines[0].strip().endswith('YES'):
            temp_line = lines[1]
            temp_output = temp_line.split('=')[-1]
            temperature_c = float(temp_output) / 1000.0
            
            return {
                "status": "OK",
                "temperature_c": round(temperature_c, 1),
                "temperature_f": round(temperature_c * (9 / 5) + 32, 1)
            }
        else:
            return {"status": "READ_FAILED", "message": "CRC check failed for DS18B20 data"}

    except FileNotFoundError:
        return {"status": "FS_ERROR", "message": "One-Wire device file not found. Check One-Wire setup."}
    except Exception as e:
        traceback.print_exc()
        return {"status": "UNEXPECTED_ERROR", "message": str(e)}

def calculate_moisture_percent(raw_reading):
    """Converts a raw moisture value to a percentage using defined calibration points."""
    
    # Check for invalid configuration (should not happen if constants are set correctly)
    if AIR_DRY_VALUE <= FULL_WET_VALUE:
        print("ERROR: AIR_DRY_VALUE must be greater than FULL_WET_VALUE.")
        return 0.0

    # Clamping: If sensor is drier than air-dry, report 0%
    if raw_reading >= AIR_DRY_VALUE:
        return 0.0 
    
    # Clamping: If sensor is wetter than full-wet, report 100%
    if raw_reading <= FULL_WET_VALUE:
        return 100.0 
    
    # Calculate percentage (linear interpolation)
    moisture_range = AIR_DRY_VALUE - FULL_WET_VALUE
    
    # Reading position relative to the dry end
    # Example: If reading is 450, dry=600, wet=300: 600 - 450 = 150. Range is 300. 150/300 = 0.5 (50%)
    relative_position = AIR_DRY_VALUE - raw_reading
    
    percent = (relative_position / moisture_range) * 100.0
    
    return round(percent, 1)


def get_moisture_data():
    """Reads raw moisture value from Arduino via Serial and converts to percentage."""
    try:
        ser = serial.Serial(SERIAL_PORT, SERIAL_BAUD_RATE, timeout=SERIAL_TIMEOUT)
        ser.flush()
        
        # CRITICAL FIX: Read and discard the initial "Arduino Moisture Sensor Ready." message
        if not ser.closed:
            _ = ser.readline()
        
        # Read the actual data line from the Arduino
        line = ser.readline().decode('utf-8').strip()
        ser.close()

        if line:
            try:
                raw_reading = int(line)
                moisture_percent = calculate_moisture_percent(raw_reading)
                
                return {
                    "status": "OK",
                    "raw_moisture": raw_reading,
                    "moisture_percent": moisture_percent
                }
            except ValueError:
                return {"status": "PARSE_ERROR", "message": f"Could not parse '{line}' as integer. Did the Arduino send non-numeric data?"}
        else:
            return {"status": "NO_RESPONSE", "message": "Arduino did not send a complete line in time. Check baud rate and port name."}

    except serial.SerialException as e:
        return {"status": "SERIAL_ERROR", "message": f"Failed to connect to {SERIAL_PORT}. Port may be incorrect or Arduino disconnected."}
    except Exception as e:
        traceback.print_exc()
        return {"status": "UNEXPECTED_ERROR", "message": str(e)}

# ----------------------------------------------------------------------------------
# Main Loop
# ----------------------------------------------------------------------------------

if __name__ == '__main__':
    
    print(f"--- Raspberry Pi Triple-Sensor Station Initialized ---")
    print(f"DHT Sensor Type: {SENSOR_TYPE.__name__} | Data Pin: BCM {DHT_PIN.id} (Physical Pin 11)")
    print(f"DS18B20 Sensor uses One-Wire bus (Data Pin: BCM 4 / Physical Pin 7).")
    print(f"Moisture Sensor uses Serial Port: {SERIAL_PORT}")
    print(f"Moisture Calibration: Dry={AIR_DRY_VALUE}, Wet={FULL_WET_VALUE}. Adjust these constants!")
    
    if not os.path.exists(SERIAL_PORT):
        print(f"\n⚠️ WARNING: Serial port {SERIAL_PORT} not found. Moisture reading will fail.")
        print("Ensure Arduino is connected and powered, and check the port name.")
        
    try:
        while True:
            # 1. Read all sensors
            dht_data = get_dht_data()
            ds18b20_data = get_ds18b20_data()
            moisture_data = get_moisture_data()

            # 2. Combine data into a single payload
            sensor_data_dict = {
                "id": SENSOR_ID,
                "timestamp": time.time(),
                "sensors": {
                    "dht": dht_data,
                    "ds18b20": ds18b20_data,
                    "moisture": moisture_data
                }
            }
            
            # 3. Convert to JSON
            json_output = json.dumps(sensor_data_dict, indent=4)
            
            # 4. Print Status and Payload
            dht_ok = dht_data['status'] == 'OK'
            ds_ok = ds18b20_data['status'] == 'OK'
            moist_ok = moisture_data['status'] == 'OK'
            all_ok = dht_ok and ds_ok and moist_ok 
            
            dht_status = dht_data.get('status', 'FAIL')
            ds_status = ds18b20_data.get('status', 'FAIL')
            moist_status = moisture_data.get('status', 'FAIL')
            
            print("-" * 60)
            if all_ok:
                print(f"✅ Read Successful! (DHT: OK, DS: OK, Moisture: OK)")
            else:
                print(f"❌ Read with Errors/Warnings (DHT Status: {dht_status}, DS Status: {ds_status}, Moisture Status: {moist_status})")
            
            print(json_output)
            
            # Wait time
            time.sleep(5.0)

    except KeyboardInterrupt:
        print("\nScript stopped by user.")

    except Exception as e:
        print(f"\nFATAL CRITICAL ERROR: {e}")
        traceback.print_exc()
