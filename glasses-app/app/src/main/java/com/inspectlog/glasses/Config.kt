package com.inspectlog.glasses

import android.view.KeyEvent

/** Everything you might need to change tomorrow lives in this one file. */
object Config {
    /**
     * Backend address. 10.0.2.2 is "the laptop" when running in the Android emulator.
     * On the real glasses, override it without rebuilding:
     *   adb shell am start -n com.inspectlog.glasses/.MainActivity --es server ws://192.168.1.23:8000/ws/glasses
     * (it's remembered after that).
     */
    const val DEFAULT_SERVER = "ws://10.0.2.2:8000/ws/glasses"

    /**
     * M6 touchpad (learned on hardware): tap = ENTER, swipe forward = DPAD_RIGHT, swipe back = DPAD_LEFT.
     * Codes also show in `adb logcat -s InspectLog`.
     */
    val CAPTURE_KEYS = setOf(KeyEvent.KEYCODE_ENTER, KeyEvent.KEYCODE_DPAD_CENTER, KeyEvent.KEYCODE_SPACE)
    val PASS_KEYS = setOf(KeyEvent.KEYCODE_DPAD_RIGHT)
    val BACK_KEYS = setOf(KeyEvent.KEYCODE_DPAD_LEFT, KeyEvent.KEYCODE_BACK)  // the back button steps back instead of closing the app

    /**
     * true: a tap takes the photo with the glasses camera and records the note with the glasses mics,
     * then uploads to the laptop (no phone needed). false: ask the phone app to capture instead.
     */
    const val GLASSES_CAPTURE = true

    /** Live view: one camera frame to the laptop every this many ms (only while turned on from the page). */
    const val LIVE_FRAME_MS = 120L
    /** Live frame width (height is 3/4 of it) and JPEG quality: small = smooth over busy Wi-Fi. */
    const val LIVE_WIDTH = 480
    const val LIVE_QUALITY = 45

    /** true: a tap just takes a photo and the AI decides pass or flag. false: tap also records a voice note. */
    const val PHOTO_ONLY = true

    /** Longest voice note; tap again to stop sooner. */
    const val MAX_NOTE_MS = 6000L

    /** Hint shown at the bottom of the display. */
    const val HINT = "tap: photo   ·   swipe ›: pass   ·   ‹ back"

    /** A tap on the screen (clicking in the emulator) captures too. */
    const val TAP_SCREEN_CAPTURES = true

    /** Ignore repeat taps within this window. */
    const val DEBOUNCE_MS = 1500L

    /** Speak confirmations out loud (for kits without a display module). */
    const val SPEAK_CONFIRMATIONS = false

    /** Show the last key code instead of the hint (for learning new buttons, e.g. the ring). */
    const val SHOW_KEY_DEBUG = false
}
