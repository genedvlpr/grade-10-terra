import serial
import time

# Use the port identified in your terminal
ser = serial.Serial('/dev/ttyUSB0', 9600, timeout=1)
ser.flush()

def get_smoothed_ph():
    readings = []
    # Collect 20 samples for a stable average
    for _ in range(20):
        if ser.in_waiting > 0:
            line = ser.readline().decode('utf-8').rstrip()
            if line.isdigit():
                readings.append(int(line))
        time.sleep(0.01)
    
    if not readings:
        return None
        
    avg_adc = sum(readings) / len(readings)
    # Voltage = (ADC / 1023) * 5V
    voltage = (avg_adc / 1023.0) * 5.0
    # pH = (Voltage / 5V) * 14
    ph = (voltage / 5.0) * 14.0
    return round(ph, 2)

try:
    print("Stabilizing pH readings...")
    while True:
        current_ph = get_smoothed_ph()
        if current_ph is not None:
            print(f"Stable Soil pH: {current_ph}")
        time.sleep(1)
except KeyboardInterrupt:
    ser.close()

