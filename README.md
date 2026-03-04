# ESP-EEG Robotic Hand Controller 🤖

A demonstration of using the EMG capability of the ESP-EEG bio-signal sensor to control a robotic hand.

[![ESP-EEG Robotic Hand Demo](https://img.youtube.com/vi/xjNg0UMrPlc/maxresdefault.jpg)](https://youtube.com/shorts/xjNg0UMrPlc?si=EgGIO7fhjGFAiRqD)  
*(Click the image above to watch the demo on YouTube)*

## 📝 Overview

This project showcases how to capture electromyography (EMG) data using the **ESP-EEG** and map those muscle signals to control a robotic hand in real-time. 

* **Learn more about ESP-EEG:** [www.cerelog.com](https://www.cerelog.com/eeg_researchers.html)

## ⚙️ Hardware Required

* **Cerelog ESP-EEG:** Bio-signal sensor used to read the EMG data.
* **uHand:** The robotic hand used in this demo. (Available on [Amazon](https://www.amazon.com/Movement-Mechanical-Engineering-Programming-Standard/dp/B0D479BJ7J/ref=sr_1_1?dib=eyJ2IjoiMSJ9.uSgATQcUyhgHMBCS6dALnw.357YmDhfY059PnYAUX0FkxyW23NU66B9yQJaSJX3KmA&dib_tag=se&keywords=uHand&qid=1772597706&sr=8-1&th=1) for ~$160). Note: Cerelog isn't affiliated with this vendor.
* **Electrodes & Leads:** To attach to the user's arm for signal detection.

## Special electrode connection note;

This demo requries use of just Ch1. To connect, put (1+ and srb1) across a muscle group with tEMS pads and electrode gel. You then need to place one more elecrode on either elbow or wrist for biasing (USE either Bias pin or GND pin). **Special note:** I recomend you try this out with the 'GND' pin instead of Bias for EMG demo usage.

## 🚀 How to Run the Demo

To test this out yourself, follow these steps:

1. **Flash the Firmware:** Upload the Arduino firmware provided in this repository to the uHand robotic hand.
2. **Setup the ESP-EEG:** Connect the electrodes to your arm and ensure the ESP-EEG is powered and ready to transmit data.
3. **Run the Script:** Execute the Python script to bridge the connection between the Cerelog ESP-EEG and the uHand.

```bash
# Example command to run the python script
python robohand_emg.py   (for mac use python3)
