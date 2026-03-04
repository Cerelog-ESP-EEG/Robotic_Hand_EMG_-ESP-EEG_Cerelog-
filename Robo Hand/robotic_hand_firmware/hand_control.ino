#include <Servo.h>

const uint8_t SERVO_PINS[6] = {7, 6, 5, 4, 3, 2};
Servo fingers[6];

// 0% = open (170deg), 100% = closed (~40deg). Thumb (index 4) is inverted.
void setOpen(int percent) {
  percent = constrain(percent, 0, 100);
  int angle      = map(percent, 0, 100, 170, 40);  // fingers
  int thumbAngle = map(percent, 0, 100,  10, 140); // thumb inverted
  for (int i = 0; i < 5; i++) {
    fingers[i].write(i == 0 ? thumbAngle : angle);
  }
  // wrist (index 5) stays neutral
}

void setup() {
  Serial.begin(9600);
  for (int i = 0; i < 6; i++) {
    fingers[i].attach(SERVO_PINS[i], 500, 2500);
  }
  fingers[5].write(90); // wrist neutral
  setOpen(100);         // start open
  Serial.println("Ready. Send 0-100 to set hand openness.");
}

void loop() {
  if (Serial.available()) {
    int val = Serial.parseInt();
    if (Serial.read() == '\n' || true) { // accept any terminator
      setOpen(val);
      Serial.print("Set to ");
      Serial.print(val);
      Serial.println("%");
    }
  }
}
