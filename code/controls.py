# controls.py - single source of truth for the 4 rotary knobs + their buttons.
#
# Each entry in CONTROLS is one PHYSICAL control, left to right on the seesaw
# breakout (position 0-3). Edit THIS file and it applies globally -- code.py's
# main loop reads these definitions instead of hardcoding per-knob branches, so
# changing a knob's turn action or a button's press action here changes it
# everywhere at once.
#
# Event names are what player.PlayerState.on_event() understands:
#   turn (knob):  KNOB_CW / KNOB_CCW (+ _FAST variants), VOL_UP / VOL_DOWN
#   press (button): SELECT, PLAY_PAUSE, BACK, STOP, ...
# Set a field to None to disable that action for the control.

# |encoder delta| in one tick that counts as a quick flick ("fast"). Only used
# by controls whose turn_cw/turn_ccw are plain events with a *_FAST variant set.
FAST_THRESHOLD = 3


def _ctrl(name, switch_pin, turn_cw=None, turn_ccw=None, press=None,
          turn_cw_fast=None, turn_ccw_fast=None,
          volume_popout=False, save_in_settings=False,
          del_when_editing=False, reconnect_when_saved=False):
    """One physical control.

      name                 label (LED / debugging)
      switch_pin           seesaw pin of this knob's button
      turn_cw / turn_ccw   event on clockwise / counter-clockwise turn
                           (None = turning does nothing)
      press                event when its button is pressed (None = no action)
      turn_cw_fast         optional fast variant: if set, a quick flick
                           (|delta| >= FAST_THRESHOLD) emits this instead of
                           the normal turn event; otherwise the normal one.
      volume_popout        arm the Now-Playing volume pop-out on every turn
      save_in_settings     press saves settings while in the Settings view
      del_when_editing     press deletes a char while editing a setting
      reconnect_when_saved press reconnects after a save (Settings view)
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


# Physical position -> what it does. Order = left to right on the breakout;
# the encoder channel is the list index (0-3), fixed by the hardware.
CONTROLS = [
    # NOTE: NAV's fast events use the legacy "KNOB_CWFAST"/"KNOB_CCWFAST"
    # names (no underscore) that player.py does NOT handle -- so a quick
    # flick on this knob is currently a no-op (only slow turns scroll /
    # switch tracks). If you want fast flicks to work, change these two to
    # "KNOB_CW_FAST" / "KNOB_CCW_FAST".
    _ctrl("NAV",       switch_pin=12, turn_cw="KNOB_CW",      turn_ccw="KNOB_CCW",
          press="SELECT",
          turn_cw_fast="KNOB_CWFAST", turn_ccw_fast="KNOB_CCWFAST"),

    _ctrl("TRANSPORT", switch_pin=14, turn_cw="KNOB_CW_FAST", turn_ccw="KNOB_CCW_FAST",
          press="PLAY_PAUSE", save_in_settings=True),

    _ctrl("VOLUME",    switch_pin=17, turn_cw="VOL_UP",       turn_ccw="VOL_DOWN",
          press="BACK", volume_popout=True),

    _ctrl("AUX",       switch_pin=9,  turn_cw=None,           turn_ccw=None,
          press="STOP", del_when_editing=True, reconnect_when_saved=True),
]

# Number of controls (drives the main loop's per-control arrays/loops).
N_CONTROLS = len(CONTROLS)

# Seesaw button pin per physical position (in CONTROLS order).
SWITCH_PINS = tuple(c["switch_pin"] for c in CONTROLS)
