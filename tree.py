import random
import subprocess
import os
import traceback
from statistics import mean
import threading

import board
import neopixel
import RPi.GPIO as GPIO
import mido

import time

SPEED_OF_SOUND = 343
SENSOR_SECONDS_TO_CM = SPEED_OF_SOUND * 100 / 2  # speed of sound * 100 for cm /2 since the wave goes back and forth
MAX_DURATION = (100 * 10) / SENSOR_SECONDS_TO_CM  # sensor time for 10 meters

GPIO.setmode(GPIO.BCM)

TRIG = 23

ECHO = 24
SIDES = [24, 27, 25, 17, 22]

LEDS_PER_STRIP = 355
SLEEP_TIME = 1.0
BRIGHTNESS = 1.0

TRUNK_SIZE = 27
BRANCH_SIZE = 44
LEDS_PER_SECTION = TRUNK_SIZE + BRANCH_SIZE
SECTIONS = 5
MIDI_CHANGE_PATCH_BUTTON_CHANNEL = 6

DISABLED_MIDI_SECTIONS = []

PIN = board.D21

COLORS = [
    (255, 0, 0),
    (0, 255, 0),
    (0, 0, 255),
    (255, 255, 0),
    (0, 255, 255),
    (255, 0, 255)
]

PUREDATA_FILE = "tree4.pd"
PUREDATA_DIR = "/home/tree/sound"

PRE_NORMALIZED_MIN_DISCATNCE_CM = 20
PRE_NORMALIZED_MAX_DISCATNCE_CM = 200

MAX_MIDI_VALUE = 127
MAX_MIDI_VALUES = [127, 127, 80, 127, 127, 127, 127]
SAMPLES_PER_SECTION = 5
BASE_SPARK_CHANCE = 0.03
MAX_SPARK_CHANCE = 0.1
BASE_SPARK_SPEED = 1
MAX_SPARK_SPEED = 20
current_distances = [10*100 for _ in range(SECTIONS)]


def get_section(section: int, is_branch: bool) -> tuple[int, int]:
    leds_per_section = TRUNK_SIZE + BRANCH_SIZE
    start_position = section * leds_per_section
    if is_branch:
        start_position += TRUNK_SIZE
        return start_position, start_position + BRANCH_SIZE
    else:
        return start_position, start_position + TRUNK_SIZE


def normalize_distance(distance, max_value=255):
    if distance < PRE_NORMALIZED_MIN_DISCATNCE_CM:
        return max_value
    if distance > PRE_NORMALIZED_MAX_DISCATNCE_CM:
        return 0
    return (max_value - (distance - PRE_NORMALIZED_MIN_DISCATNCE_CM) * max_value /
            (PRE_NORMALIZED_MAX_DISCATNCE_CM - PRE_NORMALIZED_MIN_DISCATNCE_CM))


def send_midi(midi_device, section, distance):
    if section not in DISABLED_MIDI_SECTIONS:
        note = int(normalize_distance(distance, 127))
        midi_device.send(
            mido.Message('note_on', note=note, channel=section))


def main_loop(midi_device):
    global current_distances
    last_distance_values = [[10 * 100 for _ in range(SAMPLES_PER_SECTION)] for _ in range(len(SIDES))]

    while True:
        for section, side_gpio in enumerate(SIDES):
            time.sleep(0.01)
            GPIO.output(TRIG, True)
            time.sleep(0.00001)
            GPIO.output(TRIG, False)
            start_time = time.time()
            got_0 = False
            got_1 = False
            while GPIO.input(side_gpio) == 0 and time.time() - start_time < MAX_DURATION:
                got_0 = True
                pulse_start = time.time()

            while GPIO.input(side_gpio) == 1 and time.time() - start_time < MAX_DURATION:
                got_1 = True
                pulse_end = time.time()

            if not got_0 or not got_1 or time.time() - start_time >= MAX_DURATION:
                distance = 10 * 100  # 10 meters
            else:
                pulse_duration = pulse_end - pulse_start
                distance = pulse_duration * 17150
                distance = round(distance, 2)

            last_distance_values[section].pop()
            last_distance_values[section].insert(0, distance)
            distance = mean(last_distance_values[section])
            current_distances[section] = distance
            send_midi(midi_device, section, distance)


def setup_leds():
    strip = neopixel.NeoPixel(PIN, LEDS_PER_STRIP, brightness=1.0, auto_write=False)
    return strip


def setup_sensors():
    GPIO.setup(TRIG, GPIO.OUT)

    for side in SIDES:
        GPIO.setup(side, GPIO.IN)

    GPIO.output(TRIG, False)


def start_puredata():
    p = subprocess.Popen(["puredata", "-nogui", "-audiooutdev", "2", "-midiindev", "1", "-alsamidi", PUREDATA_FILE],
                         cwd=PUREDATA_DIR)
    return p


def get_midi_device():
    devices = mido.get_output_names()
    for device in devices:
        if "Pure Data" in device:
            return mido.open_output(device)


def set_random_patch(midi_device):
    for _ in range(random.randint(1,100)):
        send_midi(midi_device, MIDI_CHANGE_PATCH_BUTTON_CHANNEL, 123)


def colors_similar(color1, color2, threshold=10):
    if (abs(color1[0] - color2[0]) > threshold or
            abs(color1[1] - color2[1]) > threshold or
            abs(color1[2] - color2[2]) > threshold):
        return False
    return True


def go_to_color(color, target, speed):
    new_color = []
    if target[0] > color[0]:
        new_color.append(min(255, color[0] + speed))
    else:
        new_color.append(max(0, color[0] - speed))
    if target[1] > color[1]:
        new_color.append(min(255, color[1] + speed))
    else:
        new_color.append(max(0, color[0] - speed))
    if target[2] > color[2]:
        new_color.append(min(255, color[2] + speed))
    else:
        new_color.append(max(0, color[2] - speed))
    return tuple(new_color)


def do_leds(strip):
    global current_distances
    section_base_colors = [random.choice(COLORS) for _ in range(SECTIONS)]

    sections = [[section_base_colors[section] for _ in range(LEDS_PER_SECTION)] for section in range(SECTIONS)]

    while True:
        for section in range(SECTIONS):
            if random.random() < 0.001:
                section_base_colors[section] = random.choice(COLORS)
            # speed = BASE_SPARK_SPEED + normalize_distance(current_distances[section],
            #                                               MAX_SPARK_SPEED - BASE_SPARK_SPEED)
            speed = BASE_SPARK_SPEED
            spark_chance = BASE_SPARK_CHANCE + normalize_distance(current_distances[section],
                                                                  MAX_SPARK_CHANCE - BASE_SPARK_CHANCE)
            is_spark = random.random() < spark_chance
            if is_spark:
                new_led_color = random.choice(COLORS)
            elif not colors_similar(sections[section][0], section_base_colors[section], 100):
                new_led_color = go_to_color(sections[section][0], section_base_colors[section], speed)
            else:
                new_led_color = section_base_colors[section]
            sections[section].pop()
            sections[section].insert(0, new_led_color)
            strip[section * LEDS_PER_SECTION:(section + 1) * LEDS_PER_SECTION] = sections[section]
            strip.show()


def main():
    print("Starting tree.py")
    setup_sensors()

    strip = setup_leds()
    led_thread = threading.Thread(target=do_leds, args=(strip, ), daemon=True)
    led_thread.start()

    while True:
        print("Starting Puredata")
        puredata_process = start_puredata()
        midi_device = get_midi_device()

        set_random_patch(midi_device)

        try:
            main_loop(midi_device)
        except Exception as e:
            traceback.print_exc()
        finally:
            GPIO.cleanup()
            os.kill(puredata_process.pid, 9)



if __name__ == '__main__':
    main()
