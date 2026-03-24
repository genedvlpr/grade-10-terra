import asyncio
import json
import logging
from bleak import BleakServer
from bleak.backends.service import BleakGATTService, BleakGATTCharacteristic
from bleak.backends.descriptor import BleakGATTDescriptor

# --- Configuration ---
# You need to define your own 128-bit UUIDs for a custom service
SERVICE_UUID = "B8D0D663-8F28-466A-824F-892D5F2F43EE" 
CHARACTERISTIC_UUID = "A1E9E441-AC2B-459E-910B-22878D1612A0"

# Set up logging for better output
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class SensorDataService(BleakGATTService):
    """
    A custom BLE Service to hold the sensor data characteristic.
    """
    def __init__(self, uuid):
        super().__init__(uuid)
        self.sensor_data_char = SensorDataCharacteristic(
            CHARACTERISTIC_UUID, 
            properties=0x02 | 0x08, # Read (0x02) and Write (0x08)
            permissions=0x01 | 0x04, # Readable (0x01) and Writeable (0x04)
            service_uuid=uuid
        )
        self.add_characteristic(self.sensor_data_char)
        
    def get_latest_data(self):
        """Returns the most recently written sensor data."""
        return self.sensor_data_char.value
        
class SensorDataCharacteristic(BleakGATTCharacteristic):
    """
    The Characteristic where multi_sensor_reader.py will write the JSON data.
    """
    def __init__(self, uuid, properties, permissions, service_uuid):
        super().__init__(uuid, properties, permissions, service_uuid)
        # Initial value: an empty JSON object string
        self.value = b'{}'
        
    def read_value(self, sender, **kwargs):
        """Called when a BLE client tries to READ this characteristic."""
        logger.info(f"Characteristic Read by {sender}: {self.value.decode()}")
        return self.value

    def write_value(self, value, sender, **kwargs):
        """Called when a BLE client tries to WRITE to this characteristic."""
        try:
            # The received value is a byte array; decode it to a string
            json_string = value.decode('utf-8')
            # Validate that it's valid JSON
            sensor_dict = json.loads(json_string) 
            
            # Update the characteristic's value
            self.value = value
            logger.info(f"✅ Data written successfully by {sender}. ID: {sensor_dict.get('id')}, Time: {sensor_dict.get('timestamp')}")
            # print the current state of the data for debugging/display
            print("\n--- Latest Sensor Data Received ---")
            print(json.dumps(sensor_dict, indent=2))
            print("-----------------------------------\n")

        except json.JSONDecodeError:
            logger.error(f"Received non-JSON data from {sender}: {value!r}")
        except Exception as e:
            logger.error(f"An error occurred during write: {e}")

async def run_ble_server():
    """
    Starts the Bleak BLE server.
    """
    logger.info("Starting BLE GATT server...")
    
    # Create the custom service
    service = SensorDataService(SERVICE_UUID)
    
    # Initialize the server
    server = BleakServer(
        service,
        # A friendly name that will be advertised
        advertisement_data={"local_name": "RPI_SENSOR_STATION"} 
    )

    try:
        # Start the server and keep it running
        await server.start()
        logger.info(f"Server running and advertising as 'RPI_SENSOR_STATION'.")
        logger.info(f"Service UUID: {SERVICE_UUID}")
        logger.info(f"Characteristic UUID: {CHARACTERISTIC_UUID}")
        logger.info("Waiting for multi_sensor_reader.py to connect and write data...")
        
        # Keep the asyncio loop running indefinitely
        await asyncio.Event().wait()
        
    except Exception as e:
        logger.critical(f"A critical error occurred: {e}")
    finally:
        # Gracefully stop the server on exit (e.g., Ctrl+C)
        if server:
            await server.stop()
        logger.info("BLE GATT server stopped.")

if __name__ == "__main__":
    try:
        asyncio.run(run_ble_server())
    except KeyboardInterrupt:
        logger.info("Program stopped by user (KeyboardIntErrupt).")
