# controls.py -- single source of truth for the 4 rotary knobs + their buttons.
# code.py's main loop reads CONTROLS every tick and turns each physical knob/button
# into an event that player.PlayerState.on_event() understands; change it here and
# it changes everywhere at once. Index = physical position on the seesaw breakout
# (0 = leftmost ... 3 = rightmost); reordering entries swaps which physical knob does
# what, but switch_pin must stay with its physical button. None / False = no action.

FAST_THRESHOLD = 3   # |encoder delta| in one tick that counts as a quick flick


def _ctrl(name, switch_pin, turn_cw=None, turn_ccw=None, press=None,
          turn_cw_fast=None, turn_ccw_fast=None,
          volume_popout=False, save_in_settings=False,
          del_when_editing=False, reconnect_when_saved=False):
    """One physical control.

      name                 label (LED / debugging)
      switch_pin           seesaw pin of this knob's button
      turn_cw / turn_ccw   event on slow clockwise / counter-clockwise turn
      turn_cw_fast/_ccw    optional: sent instead when the flick is quick
                           (|delta| >= FAST_THRESHOLD); None = fast turns behave like slow ones
      press                event when its button is pressed
      volume_popout        arm the Now-Playing volume pop-out on every turn
      save_in_settings     in Settings, this press saves settings first, then fires `press`
      del_when_editing     while editing a setting, this press deletes one char instead of firing `press`
      reconnect_when_saved after a save, this press reconnects with the new settings
    """
    return {
        "name": name,
        "switch_pin": switch_pin,
        "turn_cw": turn_cw,
        "turn_ccw": turn_ccw,
        "press": press,
        "turn_cw_fast": turn_cw_fast,
        "turn_ccw_fast": turn_ccw_fast,
        "volume_popout": volume_popout,
        "save_in_settings": save_in_settings,
        "del_when_editing": del_when_editing,
        "reconnect_when_saved": reconnect_when_saved,
    }


# Order = left to right on the seesaw breakout; index 0 is the leftmost knob.
CONTROLS = [
    # pos 1 -- NAV: stop playback; deletes chars while editing settings and
    # reconnects after a save. Turns still scroll / switch tracks (the legacy
    # fast-flick names below are ignored by player.py, so flicks do nothing).
    _ctrl(
        "NAV",
        switch_pin=12,
        turn_cw="KNOB_CW",
        turn_ccw="KNOB_CCW",
        turn_cw_fast="KNOB_CWFAST",
        turn_ccw_fast="KNOB_CCWFAST",
        press="STOP",
        del_when_editing=True,
        reconnect_when_saved=True,
    ),

    # pos 2 -- TRANSPORT: fast seek; play/pause; saves settings.
    _ctrl(
        "TRANSPORT",
        switch_pin=14,
        turn_cw="KNOB_CW_FAST",
        turn_ccw="KNOB_CCW_FAST",
        press="PLAY_PAUSE",
        save_in_settings=True,
    ),

    # pos 3 -- VOLUME: volume up/down; shows the volume bar on Now Playing.
    _ctrl(
        "VOLUME",
        switch_pin=17,
        turn_cw="VOL_UP",
        turn_ccw="VOL_DOWN",
        press="BACK",
        volume_popout=True,
    ),

    # pos 4 -- AUX: browse the library and pick tracks.
    _ctrl(
        "AUX",
        switch_pin=9,
        turn_cw="KNOB_CW",
        turn_ccw="KNOB_CCW",
        press="SELECT",
    ),
]

# Number of controls (drives the main loop's per-control arrays/loops).
N_CONTROLS = len(CONTROLS)

# Seesaw button pin per physical position (in CONTROLS order).
SWITCH_PINS = tuple(c["switch_pin"] for c in CONTROLS)
