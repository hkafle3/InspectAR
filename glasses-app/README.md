# InspectAR glasses app

A plain Android app (minSdk/targetSdk 28) for the M6 glasses display. Black background, big green text.
It connects to the laptop backend over WebSocket, sends `capture_request` when you tap, and shows checklist steps
(`Step 2/5 · Ceiling · Check for water damage`), results (`Flagged · Water stain`), readings, and free-form `Logged #N · …`.

Build from the command line (uses Android Studio's Java):

```bash
cd glasses-app
JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home" ./gradlew assembleDebug
```

## Run in the emulator (no glasses needed)

1. Start the backend on the laptop (see the main README).
2. Open this `glasses-app` folder in Android Studio and let it sync.
3. Use the emulator Android Studio already made (Medium Phone). It runs a newer Android than the glasses, which is fine for testing the display.
   From the command line: `adb install -r --bypass-low-target-sdk-block app/build/outputs/apk/debug/app-debug.apk`
4. Press Run. Click on the screen or press Enter to "tap". The emulator reaches the laptop at `10.0.2.2`, which is already the default.

## Install on the glasses

```bash
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb shell am start -n com.inspectlog.glasses/.MainActivity --es server ws://<laptop-ip>:8000/ws/glasses
```

The server address is remembered after the first launch.

Or, from the repo root, `scripts/restart_glasses.sh usb` (over the USB cable) does it all.

## Controls

On the M6 touchpad: **tap** takes a photo, **swipe forward** passes the step, **swipe back** goes back.
Key codes live in `Config.kt` (`CAPTURE_KEYS`, `PASS_KEYS`, `BACK_KEYS`); `adb logcat -s InspectLog` shows each key press.
