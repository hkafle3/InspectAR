package com.inspectlog.glasses

import android.graphics.SurfaceTexture
import android.media.MediaRecorder
import android.util.Log
import okhttp3.Call
import okhttp3.Callback
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.MultipartBody
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.asRequestBody
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import java.io.File
import java.io.IOException
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread

/**
 * Glasses-only capture: one photo from the glasses camera + a short voice note from the
 * glasses mics, uploaded straight to the laptop (POST /api/capture). No phone needed.
 */
@Suppress("DEPRECATION") // android.hardware.Camera: the M6 camera is a legacy HAL, the old API is the simplest fit
class GlassesCapture(private val cacheDir: File, private val http: OkHttpClient) {
    private val tag = "InspectLog"
    private var recorder: MediaRecorder? = null
    private val audioFile = File(cacheDir, "note.m4a")
    private val photoFile = File(cacheDir, "photo.jpg")
    @Volatile private var photo: ByteArray? = null
    private var photoDone = CountDownLatch(1)

    /** True from the first tap until the capture is handed off for upload. */
    @Volatile var active = false
        private set
    /** False if another app (e.g. the built-in recorder) is holding the mic. */
    var micOk = true
        private set

    /** Starts the voice note and takes the photo in parallel. */
    fun start(withAudio: Boolean = true, ready: ByteArray? = null) {
        active = true
        micOk = true
        photo = ready
        photoDone = CountDownLatch(1)
        if (ready != null) photoDone.countDown()  // live view already has a frame: no camera restart
        else thread(name = "photo") {
            photo = takePhoto()
            photoDone.countDown()
        }
        if (!withAudio) return
        try {
            audioFile.delete()
            recorder = MediaRecorder().apply {
                setAudioSource(MediaRecorder.AudioSource.MIC)
                setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
                setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
                setAudioSamplingRate(16000)
                setAudioChannels(1)
                setAudioEncodingBitRate(64000)
                setOutputFile(audioFile.absolutePath)
                prepare()
                start()
            }
        } catch (e: Exception) {
            Log.e(tag, "mic failed (busy?)", e)
            recorder?.release()
            recorder = null
            micOk = false
        }
    }

    /** Stops the note, waits for the photo, and uploads both. */
    fun finishAndUpload(baseUrl: String, done: (ok: Boolean, message: String) -> Unit) {
        active = false
        val hadAudio = recorder != null
        try {
            recorder?.stop()
        } catch (e: Exception) {
            Log.w(tag, "recorder stop: ${e.message}")  // happens if the note was very short
        }
        recorder?.release()
        recorder = null

        thread(name = "upload") {
            photoDone.await(6, TimeUnit.SECONDS)
            val body = MultipartBody.Builder().setType(MultipartBody.FORM)
            val jpeg = photo
            if (jpeg != null) {
                photoFile.writeBytes(jpeg)
                body.addFormDataPart("photo", "glasses.jpg", photoFile.asRequestBody("image/jpeg".toMediaType()))
            }
            if (hadAudio && audioFile.length() > 1000) {
                body.addFormDataPart("audio", "note.m4a", audioFile.asRequestBody("audio/mp4".toMediaType()))
            }
            if (jpeg == null && !(hadAudio && audioFile.length() > 1000)) {
                done(false, "No photo or audio")
                return@thread
            }
            body.addFormDataPart("note", "")
            Log.i(tag, "uploading photo=${jpeg?.size ?: 0}B audio=${audioFile.length()}B")
            val req = Request.Builder().url("$baseUrl/api/capture").post(body.build()).build()
            http.newBuilder().readTimeout(90, TimeUnit.SECONDS).build().newCall(req).enqueue(object : Callback {
                override fun onFailure(call: Call, e: IOException) = done(false, "Upload failed")
                override fun onResponse(call: Call, response: Response) {
                    response.use { done(it.isSuccessful, if (it.isSuccessful) "Saved" else "Server error ${it.code}") }
                }
            })
        }
    }

    private fun takePhoto(): ByteArray? {
        var cam: android.hardware.Camera? = null
        return try {
            cam = android.hardware.Camera.open(0)
            val p = cam.parameters
            val size = p.supportedPictureSizes.filter { it.width <= 1024 }.maxByOrNull { it.width * it.height }
            if (size != null) p.setPictureSize(size.width, size.height)
            p.jpegQuality = 80
            if (p.supportedFocusModes?.contains(android.hardware.Camera.Parameters.FOCUS_MODE_CONTINUOUS_PICTURE) == true) {
                p.focusMode = android.hardware.Camera.Parameters.FOCUS_MODE_CONTINUOUS_PICTURE
            }
            cam.parameters = p
            cam.setPreviewTexture(SurfaceTexture(10))
            cam.startPreview()
            Thread.sleep(500)  // let exposure and focus settle
            val latch = CountDownLatch(1)
            var data: ByteArray? = null
            cam.takePicture(null, null) { bytes, _ -> data = bytes; latch.countDown() }
            latch.await(5, TimeUnit.SECONDS)
            Log.i(tag, "photo ${data?.size ?: 0} bytes")
            data
        } catch (e: Exception) {
            Log.e(tag, "camera failed", e)
            null
        } finally {
            try { cam?.stopPreview() } catch (_: Exception) {}
            cam?.release()
        }
    }
}
