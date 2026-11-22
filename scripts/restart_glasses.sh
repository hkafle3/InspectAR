#!/bin/bash
# Brings the InspectAR app back on the glasses: closes MicroLumin's camera/recorder apps
# (the frame buttons open them), wakes the display, and reopens our app pointed at this laptop.
# Usage: scripts/restart_glasses.sh            (uses the laptop's Wi-Fi address)
#        scripts/restart_glasses.sh usb        (talk over the USB cable instead)
ADB=~/Library/Android/sdk/platform-tools/adb
echo "Waiting for the glasses (plug in the USB cable if this hangs)..."
$ADB wait-for-device
SERIAL=$($ADB devices | awk 'NR>1 && $2=="device" {print $1; exit}')
export ANDROID_SERIAL=$SERIAL
if [ "$1" = "usb" ]; then
  $ADB reverse tcp:8000 tcp:8000
  SERVER=ws://127.0.0.1:8000/ws/glasses
else
  SERVER=ws://$(ipconfig getifaddr en0):8000/ws/glasses
fi
$ADB shell input keyevent KEYCODE_WAKEUP
$ADB shell am force-stop com.mlaixr.camera
$ADB shell am force-stop com.mlaixr.recorder
$ADB shell am start -S -n com.inspectlog.glasses/.MainActivity --es server "$SERVER" >/dev/null
echo "Glasses app restarted on $SERIAL, talking to $SERVER"
