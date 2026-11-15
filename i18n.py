"""
i18n -- the one place patient-facing instructional text gets its Filipino
counterpart. Scope is deliberately narrow (see the pasted "Filipino Language
Support" spec this module implements): tutorial hints, each game's code-drawn
"Controls" supplement panel (games/hud.py's draw_controls_panel -- NOT the
illustrated How-To-Play card art, which is pre-made PNG artwork with text
baked into the image and "fully out of reach for code to edit", per
games/hud.py's own comment), and the patient-facing calibration screen's
heading/instruction/feedback text. Therapist-facing text, game names,
branding, scores, and general UI labels never go through this module.

Usage:
    from i18n import tr
    tr("basketball.ctrl.squeeze.desc", self.language)
    tr("basketball.tut.4.target", self.language, goal=self.goal)

`self.language` is set on every game by games/session_mode.py's
SessionModeMixin (`"en"` or `"fil"`, from the therapist dashboard's Language
chip -- see scenes/therapist_dashboard.py's `_patient_language`).
"""

STRINGS = {
    # ------------------------------------------------------------------
    # Basketball
    # ------------------------------------------------------------------
    "basketball.tut.1": {
        "en":  "Squeeze the ball to raise the bar!",
        "fil": "Pisilin ang bola para itaas ang bar!",
    },
    "basketball.tut.2": {
        "en":  "Keep squeezing until the bar reaches the green zone, then release it.",
        "fil": "Ipagpatuloy ang pisil hanggang umabot ang bar sa green zone, pagkatapos ay bitawan.",
    },
    "basketball.tut.3": {
        "en":  "The ball shoots automatically every time you release inside the green zone.",
        "fil": "Awtomatikong sumisibat ang bola sa tuwing bitawan mo habang nasa loob ng green zone.",
    },
    "basketball.tut.4.target": {
        "en":  "Keep shooting to reach {goal} shots!",
        "fil": "Ipagpatuloy ang pagshoot para umabot sa {goal} shots!",
    },
    "basketball.tut.4.timed": {
        "en":  "Keep shooting as many as you can before time runs out!",
        "fil": "Magshoot ng kasing dami ng kaya mo bago maubos ang oras!",
    },
    "basketball.ctrl.squeeze.action": {"en": "Squeeze", "fil": "Pisilin"},
    "basketball.ctrl.squeeze.desc": {
        "en":  "Squeeze your hand to raise the grip bar.",
        "fil": "Pisilin ang iyong kamay para itaas ang grip bar.",
    },
    "basketball.ctrl.hold.action": {"en": "Hold", "fil": "Hawakan"},
    "basketball.ctrl.hold.desc": {
        "en":  "Keep squeezing until the bar reaches the green zone.",
        "fil": "Ipagpatuloy ang pisil hanggang umabot ang bar sa green zone.",
    },
    "basketball.ctrl.release.action": {"en": "Release", "fil": "Bitawan"},
    "basketball.ctrl.release.desc": {
        "en":  "Release your grip to shoot, then repeat.",
        "fil": "Bitawan ang iyong hawak para mag-shoot, pagkatapos ay ulitin.",
    },

    # ------------------------------------------------------------------
    # Lemonade
    # ------------------------------------------------------------------
    "lemonade.tut.1": {
        "en":  "Squeeze and hold to squeeze the lemon.",
        "fil": "Pisilin at hawakan para pigain ang lemon.",
    },
    "lemonade.tut.2": {
        "en":  "Keep holding until it's full, then release to pour the juice into the pitcher!",
        "fil": "Ipagpatuloy ang pisil hanggang mapuno, pagkatapos ay bitawan para maibuhos ang juice sa pitcher!",
    },
    "lemonade.tut.3.target": {
        "en":  "Keep squeezing to reach {goal} lemons!",
        "fil": "Ipagpatuloy ang pisil para umabot sa {goal} lemons!",
    },
    "lemonade.tut.3.timed": {
        "en":  "Squeeze as many lemons as you can before time runs out!",
        "fil": "Pigain ang kasing dami ng lemons na kaya mo bago maubos ang oras!",
    },
    "lemonade.ctrl.squeeze.action": {"en": "Squeeze", "fil": "Pisilin"},
    "lemonade.ctrl.squeeze.desc": {
        "en":  "Squeeze and hold to squeeze the lemon -- watch the juice fill up.",
        "fil": "Pisilin at hawakan para pigain ang lemon -- panoorin ang paglaki ng juice.",
    },
    "lemonade.ctrl.release.action": {"en": "Release", "fil": "Bitawan"},
    "lemonade.ctrl.release.desc": {
        "en":  "Release once full to pour that lemon's juice into the pitcher.",
        "fil": "Bitawan kapag puno na para maibuhos ang juice ng lemon sa pitcher.",
    },

    # ------------------------------------------------------------------
    # Whack-a-Mole
    # ------------------------------------------------------------------
    "whackmole.tut.1": {
        "en":  "Each hole is mapped to one finger, left to right: Thumb, Index, Middle, Ring, Pinky.",
        "fil": "Bawat butas ay para sa isang daliri, mula kaliwa pakanan: Hinlalaki, Hintuturo, "
               "Hinalang-kalingkingan, Palasingsingan, Hinliliit.",
    },
    "whackmole.tut.2": {
        "en":  "Bend the matching finger the moment a mole pops up in its hole!",
        "fil": "Baluktutin ang tamang daliri sa sandaling lumitaw ang mole sa butas nito!",
    },
    "whackmole.tut.3.target": {
        "en":  "Keep hitting moles to reach {goal}!",
        "fil": "Ipagpatuloy ang pagpukpok sa mole para umabot sa {goal}!",
    },
    "whackmole.tut.3.timed": {
        "en":  "Hit as many moles as you can before time runs out!",
        "fil": "Pukpukin ang kasing dami ng mole na kaya mo bago maubos ang oras!",
    },
    "whackmole.ctrl.bend.action": {"en": "Bend a finger", "fil": "Baluktutin ang daliri"},
    "whackmole.ctrl.bend.desc": {
        "en":  "Each hole is mapped to one finger, left to right: Thumb, Index, Middle, Ring, Pinky.",
        "fil": "Bawat butas ay para sa isang daliri, mula kaliwa pakanan: Hinlalaki, Hintuturo, "
               "Hinalang-kalingkingan, Palasingsingan, Hinliliit.",
    },
    "whackmole.ctrl.hit.action": {"en": "Hit the mole", "fil": "Pukpukin ang mole"},
    "whackmole.ctrl.hit.desc": {
        "en":  "Bend the matching finger the moment a mole pops up in its hole.",
        "fil": "Baluktutin ang tamang daliri sa sandaling lumitaw ang mole sa butas nito.",
    },

    # ------------------------------------------------------------------
    # Toy Factory
    # ------------------------------------------------------------------
    "toyfactory.tut.1": {
        "en":  "Tilt your wrist to move your hand over a toy on the conveyor, then squeeze to grab it.",
        "fil": "Ikiling ang iyong pulso para ilipat ang kamay sa ibabaw ng laruan sa conveyor, "
               "pagkatapos ay pisilin para kunin ito.",
    },
    "toyfactory.tut.2": {
        "en":  "Move your hand over the matching box, then release to drop the toy in.",
        "fil": "Ilipat ang kamay sa ibabaw ng tamang kahon, pagkatapos ay bitawan para ihulog ang laruan.",
    },
    "toyfactory.tut.3.target": {
        "en":  "Keep sorting toys to reach {goal}!",
        "fil": "Ipagpatuloy ang pag-ayos ng laruan para umabot sa {goal}!",
    },
    "toyfactory.tut.3.timed": {
        "en":  "Sort as many toys as you can before time runs out!",
        "fil": "Ayusin ang kasing dami ng laruan na kaya mo bago maubos ang oras!",
    },
    "toyfactory.ctrl.tilt.action": {"en": "Tilt", "fil": "Ikiling"},
    "toyfactory.ctrl.tilt.desc": {
        "en":  "Tilt your wrist in any direction to move your hand over the conveyor.",
        "fil": "Ikiling ang iyong pulso sa anumang direksyon para ilipat ang kamay sa ibabaw ng conveyor.",
    },
    "toyfactory.ctrl.squeeze.action": {"en": "Squeeze", "fil": "Pisilin"},
    "toyfactory.ctrl.squeeze.desc": {
        "en":  "Squeeze to grab the toy under your hand.",
        "fil": "Pisilin para kunin ang laruang nasa ilalim ng kamay.",
    },
    "toyfactory.ctrl.release.action": {"en": "Release", "fil": "Bitawan"},
    "toyfactory.ctrl.release.desc": {
        "en":  "Move over the matching box, then release to drop the toy in.",
        "fil": "Ilipat sa ibabaw ng tamang kahon, pagkatapos ay bitawan para ihulog ang laruan.",
    },

    # ------------------------------------------------------------------
    # Steady Aim
    # ------------------------------------------------------------------
    "steadyaim.tut.1": {
        "en":  "Tilt your wrist to move the aim cursor onto the target.",
        "fil": "Ikiling ang iyong pulso para ilipat ang pointer patungo sa target.",
    },
    "steadyaim.tut.2": {
        "en":  "Hold steady on target -- it fires automatically! No squeeze needed.",
        "fil": "Manatiling steady sa target -- awtomatikong babaril ito! Hindi na kailangang pisilin.",
    },
    "steadyaim.tut.3.target": {
        "en":  "Keep firing to reach {goal} shots!",
        "fil": "Ipagpatuloy ang pagbaril para umabot sa {goal} shots!",
    },
    "steadyaim.tut.3.timed": {
        "en":  "Fire as many shots as you can before time runs out!",
        "fil": "Bumaril ng kasing dami ng kaya mo bago maubos ang oras!",
    },
    "steadyaim.ctrl.aim.action": {"en": "Aim", "fil": "Itutok"},
    "steadyaim.ctrl.aim.desc": {
        "en":  "Tilt your wrist in any direction to move the aim cursor onto the target.",
        "fil": "Ikiling ang iyong pulso sa anumang direksyon para ilipat ang pointer patungo sa target.",
    },
    "steadyaim.ctrl.hold.action": {"en": "Hold steady", "fil": "Manatiling steady"},
    "steadyaim.ctrl.hold.desc": {
        "en":  "Hold the cursor on target -- it fires automatically once you hold long enough. "
               "No squeeze needed.",
        "fil": "Panatilihin ang pointer sa target -- awtomatiko itong babaril kapag natagalan ka. "
               "Hindi na kailangang pisilin.",
    },

    # ------------------------------------------------------------------
    # Garden Wonders (plant_the_garden)
    # ------------------------------------------------------------------
    "plantgarden.tut.1": {
        "en":  "Squeeze near the seed box to grab a seed.",
        "fil": "Pisilin malapit sa seed box para kunin ang isang binhi.",
    },
    "plantgarden.tut.2": {
        "en":  "Bend your wrist down further over empty soil to plant it.",
        "fil": "Iyuko pa ang iyong pulso paibaba sa ibabaw ng walang-lamang lupa para itanim ito.",
    },
    "plantgarden.tut.3": {
        "en":  "Now grab the watering can and squeeze over your plant to water it.",
        "fil": "Ngayon kunin ang watering can at pisilin sa ibabaw ng iyong tanim para diligan ito.",
    },
    "plantgarden.tut.4.target": {
        "en":  "Keep growing plants to reach {goal}!",
        "fil": "Ipagpatuloy ang pagtanim para umabot sa {goal}!",
    },
    "plantgarden.tut.4.timed": {
        "en":  "Grow as many plants as you can before time runs out!",
        "fil": "Magtanim ng kasing dami ng kaya mo bago maubos ang oras!",
    },
    "plantgarden.ctrl.tilt.action": {"en": "Tilt", "fil": "Ikiling"},
    "plantgarden.ctrl.tilt.desc": {
        "en":  "Tilt your wrist in any direction to move your hand around the garden.",
        "fil": "Ikiling ang iyong pulso sa anumang direksyon para ilipat ang kamay sa buong hardin.",
    },
    "plantgarden.ctrl.grab.action": {"en": "Grab", "fil": "Kunin"},
    "plantgarden.ctrl.grab.desc": {
        "en":  "Squeeze near the seed box or the watering can to pick it up.",
        "fil": "Pisilin malapit sa seed box o sa watering can para buhatin ito.",
    },
    "plantgarden.ctrl.plant.action": {"en": "Plant", "fil": "Itanim"},
    "plantgarden.ctrl.plant.desc": {
        "en":  "While holding a seed, bend your wrist down further over empty soil to plant it.",
        "fil": "Habang may hawak na binhi, iyuko pa ang pulso paibaba sa ibabaw ng walang-lamang "
               "lupa para itanim ito.",
    },
    "plantgarden.ctrl.water.action": {"en": "Water / Release", "fil": "Diligan / Bitawan"},
    "plantgarden.ctrl.water.desc": {
        "en":  "While holding the can, squeeze over a plant to water it, or bend your wrist down "
               "to let go of it anytime.",
        "fil": "Habang may hawak na watering can, pisilin sa ibabaw ng tanim para diligan ito, o "
               "iyuko ang pulso paibaba para bitawan ito anumang oras.",
    },

    # ------------------------------------------------------------------
    # Apple Catching
    # ------------------------------------------------------------------
    "applecatching.tut.1": {
        "en":  "Tilt your wrist left or right to move the basket.",
        "fil": "Ikiling ang iyong pulso sa kaliwa o kanan para ilipat ang basket.",
    },
    "applecatching.tut.2": {
        "en":  "Catching happens automatically -- just line the basket up under whatever is falling.",
        "fil": "Awtomatiko ang paghuli -- ihanay lang ang basket sa ilalim ng anumang bumabagsak.",
    },
    "applecatching.tut.3.target": {
        "en":  "Keep catching to reach {goal}!",
        "fil": "Ipagpatuloy ang paghuli para umabot sa {goal}!",
    },
    "applecatching.tut.3.timed": {
        "en":  "Catch as many as you can before time runs out!",
        "fil": "Humuli ng kasing dami ng kaya mo bago maubos ang oras!",
    },
    "applecatching.ctrl.tilt.action": {"en": "Tilt", "fil": "Ikiling"},
    "applecatching.ctrl.tilt.desc": {
        "en":  "Tilt your wrist left or right to move the basket.",
        "fil": "Ikiling ang iyong pulso sa kaliwa o kanan para ilipat ang basket.",
    },
    "applecatching.ctrl.catch.action": {"en": "Catch", "fil": "Huli"},
    "applecatching.ctrl.catch.desc": {
        "en":  "Line the basket up under whatever is falling -- catching is automatic.",
        "fil": "Ihanay ang basket sa ilalim ng anumang bumabagsak -- awtomatiko ang paghuli.",
    },

    # ------------------------------------------------------------------
    # Tile Rush (piano_tiles)
    # ------------------------------------------------------------------
    "tilerush.tut.1": {
        "en":  "Each lane is mapped to one finger, left to right: Thumb, Index, Middle, Ring, Pinky.",
        "fil": "Bawat lane ay para sa isang daliri, mula kaliwa pakanan: Hinlalaki, Hintuturo, "
               "Hinalang-kalingkingan, Palasingsingan, Hinliliit.",
    },
    "tilerush.tut.2": {
        "en":  "Bend the matching finger the moment its tile reaches the hit line!",
        "fil": "Baluktutin ang tamang daliri sa sandaling umabot ang tile nito sa hit line!",
    },
    "tilerush.tut.3.target": {
        "en":  "Keep tapping to reach {goal} tiles!",
        "fil": "Ipagpatuloy ang pag-tap para umabot sa {goal} tiles!",
    },
    "tilerush.tut.3.timed": {
        "en":  "Tap as many tiles as you can before time runs out!",
        "fil": "I-tap ang kasing dami ng tiles na kaya mo bago maubos ang oras!",
    },
    "tilerush.ctrl.bend.action": {"en": "Bend a finger", "fil": "Baluktutin ang daliri"},
    "tilerush.ctrl.bend.desc": {
        "en":  "Each lane is mapped to one finger, left to right: Thumb, Index, Middle, Ring, Pinky.",
        "fil": "Bawat lane ay para sa isang daliri, mula kaliwa pakanan: Hinlalaki, Hintuturo, "
               "Hinalang-kalingkingan, Palasingsingan, Hinliliit.",
    },
    "tilerush.ctrl.tap.action": {"en": "Tap the tile", "fil": "Tapikin ang tile"},
    "tilerush.ctrl.tap.desc": {
        "en":  "Bend the matching finger the moment its tile reaches the hit line.",
        "fil": "Baluktutin ang tamang daliri sa sandaling umabot ang tile nito sa hit line.",
    },

    # ------------------------------------------------------------------
    # Key and Lock
    # ------------------------------------------------------------------
    "keylock.tut.1": {
        "en":  "Tilt your wrist to turn the key toward the target angle.",
        "fil": "Ikiling ang iyong pulso para ipihit ang susi patungo sa target angle.",
    },
    "keylock.tut.2": {
        "en":  "Hold it steady on target to complete the turn!",
        "fil": "Panatilihin itong steady sa target para matapos ang pagpihit!",
    },
    "keylock.tut.3.target": {
        "en":  "Keep unlocking to reach {goal} locks!",
        "fil": "Ipagpatuloy ang pag-unlock para umabot sa {goal} locks!",
    },
    "keylock.tut.3.timed": {
        "en":  "Unlock as many as you can before time runs out!",
        "fil": "Mag-unlock ng kasing dami ng kaya mo bago maubos ang oras!",
    },
    "keylock.ctrl.tilt.action": {"en": "Tilt", "fil": "Ikiling"},
    "keylock.ctrl.tilt.desc": {
        "en":  "Tilt your wrist to turn the key toward the target angle.",
        "fil": "Ikiling ang iyong pulso para ipihit ang susi patungo sa target angle.",
    },
    "keylock.ctrl.hold.action": {"en": "Hold steady", "fil": "Manatiling steady"},
    "keylock.ctrl.hold.desc": {
        "en":  "Hold the key steady on target to complete the turn.",
        "fil": "Panatilihing steady ang susi sa target para matapos ang pagpihit.",
    },

    # ------------------------------------------------------------------
    # Purrfect Feast (feed_the_cat)
    # ------------------------------------------------------------------
    "feedcat.tut.1": {
        "en":  "Tilt your wrist to move to the food, then squeeze to pick up the bowl.",
        "fil": "Ikiling ang iyong pulso para lumipat patungo sa pagkain, pagkatapos ay pisilin "
               "para buhatin ang bowl.",
    },
    "feedcat.tut.2": {
        "en":  "Keep squeezing over the food to fill the bowl.",
        "fil": "Ipagpatuloy ang pisil sa ibabaw ng pagkain para mapuno ang bowl.",
    },
    "feedcat.tut.3": {
        "en":  "Carry the filled bowl to the cat and release to feed it!",
        "fil": "Dalhin ang puno nang bowl sa pusa at bitawan para pakainin ito!",
    },
    "feedcat.tut.4.target": {
        "en":  "Keep feeding cats to reach {goal}!",
        "fil": "Ipagpatuloy ang pagpakain ng pusa para umabot sa {goal}!",
    },
    "feedcat.tut.4.timed": {
        "en":  "Feed as many cats as you can before time runs out!",
        "fil": "Pakainin ang kasing dami ng pusa na kaya mo bago maubos ang oras!",
    },
    "feedcat.ctrl.tilt.action": {"en": "Tilt", "fil": "Ikiling"},
    "feedcat.ctrl.tilt.desc": {
        "en":  "Tilt your wrist left or right to move your hand.",
        "fil": "Ikiling ang iyong pulso sa kaliwa o kanan para ilipat ang kamay.",
    },
    "feedcat.ctrl.squeeze.action": {"en": "Squeeze", "fil": "Pisilin"},
    "feedcat.ctrl.squeeze.desc": {
        "en":  "Squeeze to pick up the bowl, then keep squeezing over the food to fill it.",
        "fil": "Pisilin para buhatin ang bowl, pagkatapos ay ipagpatuloy ang pisil sa ibabaw ng "
               "pagkain para mapuno ito.",
    },
    "feedcat.ctrl.release.action": {"en": "Release", "fil": "Bitawan"},
    "feedcat.ctrl.release.desc": {
        "en":  "Carry the filled bowl to the cat and release to feed it.",
        "fil": "Dalhin ang puno nang bowl sa pusa at bitawan para pakainin ito.",
    },

    # ------------------------------------------------------------------
    # Calibration (recovr/patient_app/scenes/calibrating.py)
    # ------------------------------------------------------------------
    "calib.prep.heading":     {"en": "Get Ready", "fil": "Maghanda"},
    "calib.prep.instruction": {
        "en":  "Place your hand in a relaxed position and let your fingers loosen naturally.",
        "fil": "Ilagay ang iyong kamay sa komportableng posisyon at hayaang maluwag nang natural "
               "ang mga daliri.",
    },
    "calib.prep.feedback_label": {"en": "Starting soon", "fil": "Magsisimula na"},
    "calib.prep.feedback_msg":   {"en": "Get comfortable...", "fil": "Humanap ng komportableng posisyon..."},

    "calib.baseline.grip.heading":     {"en": "Relax Your Hand", "fil": "Relaks ang Kamay"},
    "calib.baseline.grip.instruction": {
        "en":  "Let your hand rest naturally and stay relaxed.",
        "fil": "Hayaang magpahinga nang natural ang iyong kamay at manatiling relaks.",
    },
    "calib.baseline.flex.heading":     {"en": "Relax Your Fingers", "fil": "Relaks ang mga Daliri"},
    "calib.baseline.flex.instruction": {
        "en":  "Let your fingers rest naturally and stay relaxed.",
        "fil": "Hayaang magpahinga nang natural ang iyong mga daliri at manatiling relaks.",
    },
    "calib.baseline.wrist.heading":     {"en": "Keep Your Wrist Still", "fil": "Panatilihing Hindi Gumagalaw ang Pulso"},
    "calib.baseline.wrist.instruction": {
        "en":  "Rest your wrist in a comfortable position and keep it still.",
        "fil": "Ipahinga ang iyong pulso sa komportableng posisyon at huwag galawin.",
    },
    "calib.baseline.feedback_label": {"en": "Getting ready", "fil": "Paghahanda"},
    "calib.baseline.feedback_msg":   {"en": "Hold still...", "fil": "Huwag gumalaw..."},

    "calib.sensor.grip.heading":     {"en": "Let's check your grip!", "fil": "Susuriin natin ang iyong pagkapit!"},
    "calib.sensor.grip.instruction": {
        "en":  "Squeeze your hand when your therapist tells you.",
        "fil": "Pisilin ang iyong kamay kapag sinabi ng therapist mo.",
    },
    "calib.sensor.grip.feedback_label": {"en": "Your squeeze", "fil": "Ang iyong pisil"},
    "calib.sensor.grip.feedback_msg":   {"en": "Keep going!", "fil": "Ipagpatuloy!"},

    "calib.sensor.flex.heading":     {"en": "Let's check your finger movement!", "fil": "Susuriin natin ang galaw ng iyong mga daliri!"},
    "calib.sensor.flex.instruction": {
        "en":  "Bend your fingers, then relax when your therapist tells you.",
        "fil": "Iyuko ang iyong mga daliri, pagkatapos ay magpahinga kapag sinabi ng therapist mo.",
    },
    "calib.sensor.flex.feedback_label": {"en": "Finger movement", "fil": "Galaw ng daliri"},
    "calib.sensor.flex.feedback_msg":   {"en": "Keep going!", "fil": "Ipagpatuloy!"},

    "calib.sensor.wrist.heading":     {"en": "Let's check your wrist movement!", "fil": "Susuriin natin ang galaw ng iyong pulso!"},
    "calib.sensor.wrist.instruction": {
        "en":  "Slowly move your wrist to the left and right when your therapist tells you.",
        "fil": "Dahan-dahang igalaw ang iyong pulso sa kaliwa at kanan kapag sinabi ng therapist mo.",
    },
    "calib.sensor.wrist.feedback_label": {"en": "Wrist angle", "fil": "Anggulo ng pulso"},
    "calib.sensor.wrist.feedback_msg":   {"en": "Move left and right!", "fil": "Igalaw sa kaliwa at kanan!"},

    "calib.complete.heading":     {"en": "Great Job!", "fil": "Magaling!"},
    "calib.complete.instruction": {
        "en":  "Please wait while your therapist is preparing your session.",
        "fil": "Mangyaring maghintay habang inihahanda ng iyong therapist ang iyong session.",
    },
}


def tr(key, lang="en", **kwargs):
    """Look up `key`'s text in `lang` ("en"/"fil"), falling back to English
    (or the raw key, as an unmissable signal rather than a blank string) if
    the key or language is missing -- a translation gap should never crash
    or silently disappear a patient-facing instruction."""
    entry = STRINGS.get(key, {})
    text = entry.get(lang) or entry.get("en") or key
    return text.format(**kwargs) if kwargs else text
