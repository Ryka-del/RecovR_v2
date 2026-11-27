"""
One-time generator for RecovR's calibration narration clips (see
recovr/patient_app/scenes/calibrating.py's _cue_audio_name) in both English
and Filipino. Uses edge-tts (Microsoft Edge's free neural voices) instead
of gTTS -- gTTS's single robotic voice per language sounded unnatural;
edge-tts needs no API key and keeps the same offline, pre-generated-once
workflow this project's audio already uses. Not imported by any app code;
run it by hand whenever a script needs regenerating.

Both languages are regenerated together because calibration_window.py's
PREP_DURATION / COMPLETE_DURATION are sized to whichever clip (English or
Filipino) is longer -- re-check this script's printed durations against
those two constants whenever the script or voices change.

Usage:
    pip install edge-tts
    python generate_calibration_audio.py
"""

import asyncio
import os

import edge_tts
import pygame

_AUDIO_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "audio")

_VOICES = {"en": "en-US-AvaMultilingualNeural", "fil": "fil-PH-BlessicaNeural"}
# en-US-AvaMultilingualNeural: the "Multilingual" generation of Azure neural
# voices reads less flat/robotic than non-multilingual ones; fil-PH has no
# Multilingual-tier voice, so BlessicaNeural is the most natural option there.
# -15% rate: slower, less rushed pacing than the default rate.
_RATE = "-15%"

# Each entry is the literal spoken script for that calibration stage -- the
# 5 sensor/prep/complete ones mirror their matching on-screen heading+
# instruction pair 1:1 (see i18n.py's matching "calib.*" keys and
# recovr/patient_app/scenes/calibrating.py's _PREP_CONTENT/_SENSOR_CONTENT/
# _COMPLETE_CONTENT); countdown/between are each shared across all 3
# sensors' "baseline"/"between trials" moments and are not 1:1 with one
# specific displayed line.
_CLIPS = {
    "calibration_prep": {
        "en":  "Get Ready. Place your hand in a relaxed position and let your fingers loosen naturally.",
        "fil": "Maghanda. Ilagay ang iyong kamay sa komportableng posisyon at hayaang maluwag nang natural "
               "ang mga daliri.",
    },
    "calibration_complete": {
        "en":  "Great job! Please wait while your therapist is preparing your session.",
        "fil": "Magaling! Mangyaring maghintay habang inihahanda ng iyong therapist ang iyong session.",
    },
    "calibration_ready_grip_first": {
        "en":  "Let's check your grip! Squeeze your hand when your therapist tells you.",
        "fil": "Susuriin natin ang iyong pagkapit! Pisilin ang iyong kamay kapag sinabi ng therapist mo.",
    },
    "calibration_ready_flex_first": {
        "en":  "Let's check your finger movement! Bend your fingers, then relax when your therapist tells you.",
        "fil": "Susuriin natin ang galaw ng iyong mga daliri! Iyuko ang iyong mga daliri, pagkatapos ay "
               "magpahinga kapag sinabi ng therapist mo.",
    },
    "calibration_ready_wrist_first": {
        "en":  "Let's check your wrist movement! Slowly move your wrist to the left and right when your "
               "therapist tells you.",
        "fil": "Susuriin natin ang galaw ng iyong pulso! Dahan-dahang igalaw ang iyong pulso sa kaliwa at "
               "kanan kapag sinabi ng therapist mo.",
    },
    "calibration_countdown": {
        "en":  "Stay relaxed and hold still as the countdown begins.",
        "fil": "Manatiling relaks at huwag gumalaw habang magsisimula ang pagbilang.",
    },
    "calibration_between": {
        "en":  "Great! Let's do that again.",
        "fil": "Mahusay! Gawin natin ito ulit.",
    },
}


_MAX_ATTEMPTS = 5


async def _generate_all():
    pygame.mixer.init()
    os.makedirs(_AUDIO_DIR, exist_ok=True)
    for base_name, texts in _CLIPS.items():
        for lang, text in texts.items():
            suffix = "_fil" if lang == "fil" else ""
            out_path = os.path.join(_AUDIO_DIR, f"{base_name}{suffix}.mp3")
            # The free edge-tts endpoint drops the websocket mid-batch on a
            # flaky connection every so often -- retry a few times in place
            # rather than aborting the whole run on one bad clip.
            for attempt in range(1, _MAX_ATTEMPTS + 1):
                try:
                    await edge_tts.Communicate(text, _VOICES[lang], rate=_RATE).save(out_path)
                    break
                except Exception as e:
                    if attempt == _MAX_ATTEMPTS:
                        raise
                    print(f"  retry {attempt}/{_MAX_ATTEMPTS} for {os.path.basename(out_path)} ({e})")
                    await asyncio.sleep(2 * attempt)
            length = pygame.mixer.Sound(out_path).get_length()
            print(f"wrote {os.path.basename(out_path)} ({os.path.getsize(out_path)} bytes, {length:.2f}s)")


if __name__ == "__main__":
    asyncio.run(_generate_all())
