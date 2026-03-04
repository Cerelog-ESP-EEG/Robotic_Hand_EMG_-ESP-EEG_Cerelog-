"""
Cerelog EMG → Hand Control (all-in-one)
ESP32 → parse → RMS → Arduino hand + live GUI

Usage:  python3 robohand_emg.py
        python3 robohand_emg.py /dev/cu.usbmodemXXXX   (force Arduino port)
"""

import sys, time, threading, collections, struct
import numpy as np
import serial, serial.tools.list_ports

import matplotlib
matplotlib.use('MacOSX')
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from matplotlib.widgets import Slider
from matplotlib.animation import FuncAnimation

# ── EMG / Cerelog config ──────────────────────────────────────────────────────
INITIAL_BAUD        = 9600
FINAL_BAUD          = 115200
BAUD_RATE_INDEX     = 0x04
SAMPLE_RATE         = 250.0
SAMPLE_PERIOD       = 1.0 / SAMPLE_RATE
HARDWARE_VREF       = 4.50
HARDWARE_GAIN       = 24
GUI_CORRECTION      = 24.0 * 0.6133
NUM_CHANNELS        = 8
NUM_STATUS_BYTES    = 3
BYTES_PER_CH        = 3
PKT_SIZE            = 37
PKT_START           = 0xABCD
PKT_END             = 0xDCBA
PKT_IDX_LEN         = 2
PKT_IDX_CHECKSUM    = 34
CERELOG_USB_IDS     = [{'vid': 0x1A86, 'pid': 0x7523}]
CERELOG_DESCS       = ["USB-SERIAL CH340", "CH340"]

# ── Hand / Arduino config ─────────────────────────────────────────────────────
EMG_CHANNEL     = 0        # ch1 = index 0
WINDOW_MS       = 150
OPEN_THRESHOLD  = 50.0
CLOSE_THRESHOLD = 25.0
OPEN_PERCENT    = 100
CLOSE_PERCENT   = 0
ARDUINO_BAUD    = 9600
PLOT_SECONDS    = 5

# ── Shared state ──────────────────────────────────────────────────────────────
rms_history = collections.deque(maxlen=int(SAMPLE_RATE * PLOT_SECONDS))
cal_history = collections.deque(maxlen=int(SAMPLE_RATE * 20))  # 20s calibration window
shared = dict(rms=0.0, hand_open=False,
              open_thr=OPEN_THRESHOLD, close_thr=CLOSE_THRESHOLD,
              status="Starting up...")
lock = threading.Lock()


# ── Helpers ───────────────────────────────────────────────────────────────────

def convert_uv(raw):
    scale = (2 * HARDWARE_VREF / HARDWARE_GAIN) / (2 ** 24)
    return raw * scale * 1e6 * GUI_CORRECTION


def set_hand(ser, pct):
    try:
        ser.write(f"{pct}\n".encode())
    except Exception:
        pass


def find_cerelog():
    ports = serial.tools.list_ports.comports()
    candidates = [
        p.device for p in ports
        if (p.vid and p.pid and {'vid': p.vid, 'pid': p.pid} in CERELOG_USB_IDS)
        or any(d.lower() in (p.description or "").lower() for d in CERELOG_DESCS)
    ]
    return candidates or [p.device for p in ports]


def find_arduino(exclude=None):
    for p in serial.tools.list_ports.comports():
        if p.device == exclude:
            continue
        desc = (p.description or "") + (p.manufacturer or "")
        if any(k in desc for k in ("Arduino", "usbmodem", "FTDI", "Prolific")):
            return p.device
    # fallback: first port that isn't the Cerelog
    for p in serial.tools.list_ports.comports():
        if p.device != exclude:
            return p.device
    return None


def open_cerelog():
    print("Searching for Cerelog Board...")
    candidate_ports = find_cerelog()
    for port_name in candidate_ports:
        print(f"--- Testing port: {port_name} ---")
        ser = None
        try:
            ser = serial.Serial(port_name, INITIAL_BAUD, timeout=2)
            time.sleep(5)
            if ser.in_waiting > 0: ser.read(ser.in_waiting)

            print(f"Sending handshake...")
            current_unix_time = int(time.time())
            checksum_payload = struct.pack('>BI', 0x02, current_unix_time) + bytes([0x01, BAUD_RATE_INDEX])
            checksum = sum(checksum_payload) & 0xFF
            handshake_packet = struct.pack('>BB', 0xAA, 0xBB) + checksum_payload + struct.pack('>B', checksum) + struct.pack('>BB', 0xCC, 0xDD)
            ser.write(handshake_packet)
            time.sleep(0.1)
            ser.baudrate = FINAL_BAUD
            print(f"Switched to {ser.baudrate} baud...")
            time.sleep(0.5)
            ser.reset_input_buffer()

            bytes_received = ser.read(PKT_SIZE * 5)
            if bytes_received and PKT_START.to_bytes(2, 'big') in bytes_received:
                print(f"SUCCESS on: {port_name}")
                return ser, port_name
            else:
                ser.close()
        except serial.SerialException:
            if ser: ser.close()
    return None, None


# ── Worker thread: ESP32 → process → hand ────────────────────────────────────

def worker(arduino_port_override=None):
    hand_ser   = None
    cerelog_ser = None
    try:
        with lock:
            shared['status'] = "Connecting to Cerelog board..."

        cerelog_ser, cerelog_port = open_cerelog()
        if not cerelog_ser:
            with lock:
                shared['status'] = "Error: Cerelog board not found."
            return

        with lock:
            shared['status'] = "Cerelog OK. Connecting to Arduino hand..."

        arduino_port = arduino_port_override or find_arduino(exclude=cerelog_port)
        if not arduino_port:
            with lock:
                shared['status'] = "Error: Arduino not found."
            return

        hand_ser = serial.Serial(arduino_port, ARDUINO_BAUD, timeout=1)
        time.sleep(2)
        hand_ser.read_all()
        set_hand(hand_ser, CLOSE_PERCENT)

        with lock:
            shared['status'] = ""

        print(f"\n>>> STREAMING WITH ACTIVE DC BLOCKER >>>")
        print(f"Hardware Gain: {HARDWARE_GAIN} | GUI Cal: {GUI_CORRECTION:.2f}")

        # DC blocker state
        R      = 0.995
        prev_x = [0.0] * NUM_CHANNELS
        prev_y = [0.0] * NUM_CHANNELS
        first  = True

        # RMS buffer for hand control
        win    = int(SAMPLE_RATE * WINDOW_MS / 1000)
        buf    = np.zeros(win)
        idx    = 0
        hand_open = False

        buffer      = bytearray()
        start_mark  = PKT_START.to_bytes(2, 'big')
        end_mark    = PKT_END.to_bytes(2, 'big')

        while True:
            if cerelog_ser.in_waiting:
                buffer.extend(cerelog_ser.read(cerelog_ser.in_waiting))
            elif len(buffer) < PKT_SIZE:
                time.sleep(0.001)
                continue

            while True:
                si = buffer.find(start_mark)
                if si == -1 or len(buffer) < si + PKT_SIZE:
                    break

                pkt = buffer[si: si + PKT_SIZE]
                if pkt.endswith(end_mark):
                    payload = pkt[PKT_IDX_LEN:PKT_IDX_CHECKSUM]
                    if (sum(payload) & 0xFF) == pkt[PKT_IDX_CHECKSUM]:
                        ads = pkt[7:34]
                        sample = []
                        for ch in range(NUM_CHANNELS):
                            o      = NUM_STATUS_BYTES + ch * BYTES_PER_CH
                            raw    = int.from_bytes(ads[o:o + BYTES_PER_CH], 'big', signed=True)
                            cur_x  = convert_uv(raw)
                            cur_y  = 0.0 if first else cur_x - prev_x[ch] + R * prev_y[ch]
                            prev_x[ch] = cur_x
                            prev_y[ch] = cur_y
                            sample.append(cur_y)
                        first = False

                        # hand control on ch1
                        buf[idx % win] = abs(sample[EMG_CHANNEL])
                        idx += 1
                        if idx >= win:
                            rms = float(np.sqrt(np.mean(buf ** 2)))
                            with lock:
                                ot = shared['open_thr']
                                ct = shared['close_thr']
                                shared['rms'] = rms
                                rms_history.append(rms)
                                cal_history.append(rms)

                            if not hand_open and rms > ot:
                                hand_open = True
                                set_hand(hand_ser, OPEN_PERCENT)
                            elif hand_open and rms < ct:
                                hand_open = False
                                set_hand(hand_ser, CLOSE_PERCENT)

                            with lock:
                                shared['hand_open'] = hand_open

                        buffer = buffer[si + PKT_SIZE:]
                        continue
                buffer = buffer[si + 1:]

    except Exception as e:
        with lock:
            shared['status'] = f"Error: {e}"
    finally:
        for s in (hand_ser, cerelog_ser):
            if s and s.is_open:
                try:
                    set_hand(s, CLOSE_PERCENT)
                    s.close()
                except Exception:
                    pass


# ── GUI ───────────────────────────────────────────────────────────────────────

def main():
    arduino_override = sys.argv[1] if len(sys.argv) > 1 else None
    threading.Thread(target=worker, args=(arduino_override,), daemon=True).start()

    fig = plt.figure(figsize=(10, 6), facecolor="#1e1e2e")
    fig.canvas.manager.set_window_title("EMG Hand Control")

    gs = gridspec.GridSpec(3, 1, height_ratios=[4, 1, 1], hspace=0.6, figure=fig)

    ax = fig.add_subplot(gs[0])
    ax.set_facecolor("#181825")
    ax.tick_params(colors="#cdd6f4")
    ax.yaxis.label.set_color("#cdd6f4")
    ax.xaxis.label.set_color("#cdd6f4")
    for sp in ax.spines.values():
        sp.set_color("#45475a")
    ax.set_xlim(0, int(SAMPLE_RATE * PLOT_SECONDS))
    ax.set_ylim(0, 150)
    ax.set_ylabel("RMS (µV)")
    ax.set_xticks([])

    n_pts = int(SAMPLE_RATE * PLOT_SECONDS)
    ys = np.zeros(n_pts)
    (waveform,)  = ax.plot(np.arange(n_pts), ys, color="#89b4fa", lw=1.5)
    open_line    = ax.axhline(OPEN_THRESHOLD,  color="#a6e3a1", lw=1.2, ls="--", label="open thr")
    close_line   = ax.axhline(CLOSE_THRESHOLD, color="#f38ba8", lw=1.2, ls="--", label="close thr")
    ax.legend(facecolor="#313244", labelcolor="#cdd6f4", loc="upper right")
    status_txt   = ax.text(0.01, 0.95, "", transform=ax.transAxes,
                           color="#f9e2af", fontsize=10, va="top")
    state_txt    = ax.text(0.99, 0.95, "CLOSED", transform=ax.transAxes,
                           color="#f38ba8", fontsize=14, fontweight="bold",
                           ha="right", va="top")

    ax_open  = fig.add_subplot(gs[1])
    ax_close = fig.add_subplot(gs[2])
    fig.subplots_adjust(left=0.12, right=0.95)
    # Sliders are 0-100% of the observed signal range
    sl_open  = Slider(ax_open,  "Open sensitivity",  0, 100, valinit=60, color="#a6e3a1")
    sl_close = Slider(ax_close, "Close sensitivity", 0, 100, valinit=30, color="#f38ba8")
    for sl in (sl_open, sl_close):
        sl.label.set_color("#cdd6f4")
        sl.valtext.set_color("#cdd6f4")
        sl.ax.set_facecolor("#313244")

    def compute_thresholds():
        """Derive thresholds in µV from percentiles of the calibration window."""
        with lock:
            cal = list(cal_history)
        if len(cal) < 50:
            return OPEN_THRESHOLD, CLOSE_THRESHOLD, 0.0, OPEN_THRESHOLD * 2
        arr    = np.array(cal)
        noise  = np.percentile(arr, 15)   # resting baseline
        peak   = np.percentile(arr, 95)   # typical contraction
        spread = max(peak - noise, 1.0)
        ot = noise + (sl_open.val  / 100.0) * spread
        ct = noise + (sl_close.val / 100.0) * spread
        return ot, ct, noise, peak

    def update(_):
        ot, ct, noise, peak = compute_thresholds()

        with lock:
            shared['open_thr']  = ot
            shared['close_thr'] = ct
            rms       = shared['rms']
            hand_open = shared['hand_open']
            hist      = list(rms_history)
            status    = shared['status']

        n = len(hist)
        if n > 0:
            ys[-n:] = hist
        if n < n_pts:
            ys[:n_pts - n] = 0
        waveform.set_ydata(ys)
        waveform.set_color("#a6e3a1" if hand_open else "#89b4fa")
        open_line.set_ydata([ot, ot])
        close_line.set_ydata([ct, ct])

        # auto-scale Y to actual signal
        ymax = max(peak * 1.3, rms * 1.3, ot * 1.3, 1.0) if peak > 0 else max(rms * 1.5, 10)
        ax.set_ylim(0, ymax)

        # show actual µV values on threshold lines
        open_line.set_label(f"open  {ot:.1f} µV  ({sl_open.val:.0f}%)")
        close_line.set_label(f"close {ct:.1f} µV  ({sl_close.val:.0f}%)")
        ax.legend(facecolor="#313244", labelcolor="#cdd6f4", loc="upper right", fontsize=8)

        status_txt.set_text(status)
        if hand_open:
            state_txt.set_text("OPEN");   state_txt.set_color("#a6e3a1")
        else:
            state_txt.set_text("CLOSED"); state_txt.set_color("#f38ba8")

    anim = FuncAnimation(fig, update, interval=50, cache_frame_data=False)
    plt.show(block=False)
    while plt.get_fignums():
        plt.pause(0.05)


if __name__ == "__main__":
    main()
