package com.inspectlog.glasses

import android.graphics.ImageFormat
import android.graphics.Rect
import android.graphics.SurfaceTexture
import android.graphics.YuvImage
import android.os.SystemClock
import android.util.Log
import java.io.ByteArrayOutputStream
import kotlin.math.abs

/**
 * Live view: streams small JPEG frames from the glasses camera to the laptop while it's on.
 * Only runs when turned on from the report page; the display shows "● LIVE" meanwhile.
 * Open, use and stop it on the main thread.
 */
@Suppress("DEPRECATION")
class LiveView(private val send: (ByteArray) -> Boolean) {
    private val tag = "InspectLog"
    private var cam: android.hardware.Camera? = null
    private var tex: SurfaceTexture? = null
    private var lastFrame = 0L
    @Volatile private var latestFrame: ByteArray? = null
    private var frameW = 0
    private var frameH = 0

    /** The newest frame as a better-quality JPEG, so a tap can use it as the photo instantly. */
    val latestJpeg: ByteArray?
        get() {
            val f = latestFrame ?: return null
            val out = ByteArrayOutputStream()
            YuvImage(f, ImageFormat.NV21, frameW, frameH, null).compressToJpeg(Rect(0, 0, frameW, frameH), 85, out)
            return out.toByteArray()
        }

    val running get() = cam != null

    fun start(): Boolean {
        if (cam != null) return true
        return try {
            val c = android.hardware.Camera.open(0)
            val p = c.parameters
            // Small frames travel well over busy Wi-Fi; aim for about 480x360.
            val size = p.supportedPreviewSizes.minByOrNull { abs(it.width - Config.LIVE_WIDTH) + abs(it.height - Config.LIVE_WIDTH * 3 / 4) }!!
            p.setPreviewSize(size.width, size.height)
            if (p.supportedFocusModes?.contains(android.hardware.Camera.Parameters.FOCUS_MODE_CONTINUOUS_VIDEO) == true) {
                p.focusMode = android.hardware.Camera.Parameters.FOCUS_MODE_CONTINUOUS_VIDEO
            }
            c.parameters = p
            val t = SurfaceTexture(11)
            c.setPreviewTexture(t)
            val w = size.width
            val h = size.height
            frameW = w
            frameH = h
            c.setPreviewCallback { data, _ ->
                val now = SystemClock.elapsedRealtime()
                if (data == null || now - lastFrame < Config.LIVE_FRAME_MS) return@setPreviewCallback
                lastFrame = now
                val out = ByteArrayOutputStream()
                latestFrame = data
                YuvImage(data, ImageFormat.NV21, w, h, null).compressToJpeg(Rect(0, 0, w, h), Config.LIVE_QUALITY, out)
                send(out.toByteArray())  // returns false (frame dropped) if the network is still busy with older frames
            }
            c.startPreview()
            cam = c
            tex = t
            Log.i(tag, "live view on ${w}x$h")
            true
        } catch (e: Exception) {
            Log.e(tag, "live view failed", e)
            cam?.release()
            cam = null
            false
        }
    }

    fun stop() {
        val c = cam ?: return
        try {
            c.setPreviewCallback(null)
            c.stopPreview()
        } catch (_: Exception) {}
        c.release()
        cam = null
        latestFrame = null
        tex?.release()
        tex = null
        Log.i(tag, "live view off")
    }
}
