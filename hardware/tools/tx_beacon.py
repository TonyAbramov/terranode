import sys
import time
import serial

PORT = "COM4"
BAUD = 9600
INTERVAL = 3.0

n = int(sys.argv[1]) if len(sys.argv) > 1 else 1

ser = serial.Serial(PORT, BAUD, timeout=0.1)
print(f"Beacon initialized on {PORT} with interval {INTERVAL}s. Stop: Ctrl+C")

try:
    while True:
        msg = f"{n} TerraNode ping\n"
        ser.write(msg.encode("ascii"))
        ser.flush()
        print(time.strftime("%H:%M:%S"), "sent:", msg.strip())
        n += 1
        time.sleep(INTERVAL)
except KeyboardInterrupt:
    print("\nTerminated.")
finally:
    ser.close()
