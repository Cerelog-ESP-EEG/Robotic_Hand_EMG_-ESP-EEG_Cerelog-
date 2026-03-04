import serial
import serial.tools.list_ports
import time
import sys

BAUD = 9600


def find_arduino():
    ports = serial.tools.list_ports.comports()
    for p in ports:
        if any(k in (p.manufacturer or "") for k in ("Arduino", "wch", "FTDI", "CH340", "Prolific")):
            return p.device
    # fallback: show all ports and let user pick
    if not ports:
        print("No serial ports found.")
        sys.exit(1)
    print("Available ports:")
    for i, p in enumerate(ports):
        print(f"  {i}: {p.device} - {p.description}")
    idx = int(input("Select port number: "))
    return ports[idx].device


def set_open(ser, percent):
    percent = max(0, min(100, int(percent)))
    ser.write(f"{percent}\n".encode())
    time.sleep(0.05)
    response = ser.read_all().decode(errors="ignore").strip()
    if response:
        print(response)


def main():
    port = sys.argv[1] if len(sys.argv) > 1 else find_arduino()
    print(f"Connecting to {port} at {BAUD} baud...")
    ser = serial.Serial(port, BAUD, timeout=1)
    time.sleep(2)  # wait for Arduino reset
    print(ser.read_all().decode(errors="ignore").strip())
    print("Enter 0-100 to set hand openness (q to quit).")

    while True:
        try:
            val = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if val.lower() == "q":
            break
        try:
            set_open(ser, val)
        except ValueError:
            print("Enter a number 0-100")

    ser.close()


if __name__ == "__main__":
    main()
