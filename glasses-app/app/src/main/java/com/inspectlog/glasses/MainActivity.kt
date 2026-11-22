package com.inspectlog.glasses

import android.app.Activity
import android.graphics.Color
import android.graphics.Typeface
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.speech.tts.TextToSpeech
import android.util.Log
import android.util.TypedValue
import android.view.Gravity
import android.view.KeyEvent
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import android.widget.LinearLayout
import android.widget.TextView
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.util.concurrent.TimeUnit

/**
 * Glasses display: black background (see-through on the waveguide), big bright text.
 * Connects to the laptop over WebSocket, sends capture_request on a touchpad/ring tap,
 * and shows "Logged #N · ..." confirmations.
 */
class MainActivity : Activity() {
    private val tag = "InspectLog"
    private val green = Color.rgb(80, 255, 120)
    private val ui = Handler(Looper.getMainLooper())
    private val http = OkHttpClient.Builder().pingInterval(10, TimeUnit.SECONDS).build()

    private lateinit var statusView: TextView
    private lateinit var mainView: TextView
    private lateinit var countView: TextView
    private lateinit var keyView: TextView

    private var socket: WebSocket? = null
    private var connected = false
    private var stopped = false
    private var lastCapture = 0L
    private var tts: TextToSpeech? = null
    private lateinit var server: String
    private lateinit var capture: GlassesCapture
    private lateinit var live: LiveView
    private var liveWanted = false
    private val autoStop = Runnable { finishCapture() }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        window.decorView.systemUiVisibility = (View.SYSTEM_UI_FLAG_FULLSCREEN
            or View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY)

        val prefs = getSharedPreferences("inspectlog", MODE_PRIVATE)
        intent.getStringExtra("server")?.let { prefs.edit().putString("server", it).apply() }
        server = prefs.getString("server", Config.DEFAULT_SERVER)!!

        buildUi()
        capture = GlassesCapture(cacheDir, http)
        // Never let frames pile up: if older frames are still being sent, skip this one.
        live = LiveView { jpeg ->
            val s = socket
            if (s == null || s.queueSize() > 25_000) false else s.send(okio.ByteString.of(*jpeg))
        }
        val needed = arrayOf(android.Manifest.permission.CAMERA, android.Manifest.permission.RECORD_AUDIO)
        if (needed.any { checkSelfPermission(it) != android.content.pm.PackageManager.PERMISSION_GRANTED }) {
            requestPermissions(needed, 1)
        }
        if (Config.SPEAK_CONFIRMATIONS) tts = TextToSpeech(this) {}
        connect()
    }

    private fun label(sizeSp: Float, bold: Boolean = false) = TextView(this).apply {
        setTextColor(green)
        setTextSize(TypedValue.COMPLEX_UNIT_SP, sizeSp)
        gravity = Gravity.CENTER
        if (bold) typeface = Typeface.DEFAULT_BOLD
    }

    private fun buildUi() {
        statusView = label(18f).apply { text = "Connecting…" }
        mainView = label(34f, bold = true).apply { text = "InspectAR" }
        countView = label(20f)
        keyView = label(13f).apply {
            setTextColor(Color.rgb(140, 140, 140))
            text = Config.HINT
        }
        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setBackgroundColor(Color.BLACK)
            setPadding(24, 16, 24, 16)
        }
        val wrap = LinearLayout.LayoutParams.MATCH_PARENT
        root.addView(statusView, LinearLayout.LayoutParams(wrap, 0, 1f))
        root.addView(mainView, LinearLayout.LayoutParams(wrap, 0, 3f))
        root.addView(countView, LinearLayout.LayoutParams(wrap, 0, 1f))
        root.addView(keyView, LinearLayout.LayoutParams(wrap, 0, 0.6f))
        setContentView(root)
    }

    // ------------------------------------------------------------- WebSocket

    private fun connect() {
        if (stopped) return
        Log.i(tag, "connecting to $server")
        socket = http.newWebSocket(Request.Builder().url(server).build(), object : WebSocketListener() {
            override fun onOpen(ws: WebSocket, response: Response) {
                connected = true
                ui.post { statusView.text = "Connected" }
            }

            override fun onMessage(ws: WebSocket, text: String) {
                Log.i(tag, "recv $text")
                ui.post { handle(text) }
            }

            override fun onClosing(ws: WebSocket, code: Int, reason: String) {
                ws.close(1000, null)
            }

            override fun onClosed(ws: WebSocket, code: Int, reason: String) = retry("closed")
            override fun onFailure(ws: WebSocket, t: Throwable, response: Response?) = retry(t.message ?: "error")
        })
    }

    private fun retry(why: String) {
        connected = false
        Log.w(tag, "disconnected: $why")
        ui.post { statusView.text = "Reconnecting…" }
        ui.postDelayed({ connect() }, 2000)
    }

    private fun handle(raw: String) {
        val msg = try { JSONObject(raw) } catch (e: Exception) { return }
        val text = msg.optString("text")
        if (msg.has("count")) countView.text = "${msg.getInt("count")} logged"
        when (msg.optString("type")) {
            // Checklist mode: line1 small on top, line2 big in the middle, line3 below.
            "step", "result", "reading", "done" -> {
                statusView.text = msg.optString("line1")
                mainView.text = msg.optString("line2")
                countView.text = msg.optString("line3")
                if (Config.SPEAK_CONFIRMATIONS) {
                    val say = "${msg.optString("line1")}. ${msg.optString("line2")}"
                    tts?.speak(say, TextToSpeech.QUEUE_FLUSH, null, "checklist")
                }
            }
            "logged" -> {
                mainView.text = text
                statusView.text = "Connected"
                if (Config.SPEAK_CONFIRMATIONS) {
                    tts?.speak("Logged number ${msg.optInt("id")}", TextToSpeech.QUEUE_FLUSH, null, "logged")
                }
            }
            "status" -> statusView.text = text
            "live" -> setLive(msg.optBoolean("on"))
            "capture" -> requestCapture()  // the page's Capture button
        }
    }

    private fun setLive(on: Boolean) {
        liveWanted = on
        live.stop()  // always restart cleanly: another app (e.g. the frame's camera button) may have taken the camera
        if (on) live.start()
        keyView.text = if (live.running) "● LIVE  camera to phone" else Config.HINT
    }

    private fun sendCommand(command: String) {
        val now = System.currentTimeMillis()
        if (now - lastCapture < 600) return  // ignore double swipes
        lastCapture = now
        if (!connected) {
            statusView.text = "Not connected"
            return
        }
        socket?.send("""{"type":"command","command":"$command"}""")
    }

    private fun requestCapture() {
        if (Config.GLASSES_CAPTURE) {
            if (capture.active) { finishCapture(); return }  // second tap = done talking
            val now = System.currentTimeMillis()
            if (now - lastCapture < Config.DEBOUNCE_MS) return
            lastCapture = now
            if (Config.PHOTO_ONLY && live.running && live.latestJpeg != null) {
                capture.start(withAudio = false, ready = live.latestJpeg)  // instant: use the live frame
                statusView.text = "Checking photo…"
                finishCapture()
                return
            }
            live.stop()  // the camera can only be open once; live view resumes after the capture
            if (Config.PHOTO_ONLY) {
                capture.start(withAudio = false)
                statusView.text = "Checking photo…"
                finishCapture()
                return
            }
            capture.start()
            statusView.text = "● REC  photo + note"
            keyView.text = if (capture.micOk) "speak now · tap again when done" else "mic busy · photo only"
            ui.postDelayed(autoStop, Config.MAX_NOTE_MS)
            return
        }
        val now = System.currentTimeMillis()
        if (now - lastCapture < Config.DEBOUNCE_MS) return
        lastCapture = now
        if (!connected) {
            statusView.text = "Not connected"
            return
        }
        socket?.send("""{"type":"capture_request"}""")
        statusView.text = "Capturing…"
    }

    private fun finishCapture() {
        ui.removeCallbacks(autoStop)
        if (!capture.active) return
        if (!Config.PHOTO_ONLY) statusView.text = "Saving…"
        keyView.text = Config.HINT
        val base = server.replaceFirst("ws://", "http://").replaceFirst("wss://", "https://").substringBefore("/ws/")
        capture.finishAndUpload(base) { ok, message ->
            Log.i(tag, "capture upload: $ok $message")
            ui.post { if (liveWanted && !live.running) setLive(true) }
            // On success the server pushes the result/step to the display.
            if (!ok) ui.post { statusView.text = message }
        }
    }

    // ------------------------------------------------- key event discovery

    override fun dispatchKeyEvent(event: KeyEvent): Boolean {
        val name = KeyEvent.keyCodeToString(event.keyCode)
        val action = if (event.action == KeyEvent.ACTION_DOWN) "down" else "up"
        Log.i(tag, "key $action $name (${event.keyCode}) source=${event.source} repeat=${event.repeatCount}")
        if (Config.SHOW_KEY_DEBUG && event.action == KeyEvent.ACTION_DOWN) keyView.text = "key: $name (${event.keyCode})"
        val press = event.action == KeyEvent.ACTION_DOWN && event.repeatCount == 0

        when (event.keyCode) {
            in Config.CAPTURE_KEYS -> { if (press) requestCapture(); return true }
            in Config.PASS_KEYS -> { if (press) sendCommand("pass"); return true }
            in Config.BACK_KEYS -> { if (press) sendCommand("back"); return true }
        }
        return super.dispatchKeyEvent(event)
    }

    override fun onTouchEvent(event: MotionEvent): Boolean {
        Log.i(tag, "touch ${MotionEvent.actionToString(event.action)} x=${event.x} y=${event.y}")
        if (Config.TAP_SCREEN_CAPTURES && event.action == MotionEvent.ACTION_UP) {
            requestCapture()
        }
        return true
    }

    override fun onGenericMotionEvent(event: MotionEvent): Boolean {
        Log.i(tag, "motion ${MotionEvent.actionToString(event.action)} source=${event.source} x=${event.x} y=${event.y}")
        return super.onGenericMotionEvent(event)
    }

    override fun onDestroy() {
        live.stop()
        stopped = true
        socket?.close(1000, "bye")
        tts?.shutdown()
        super.onDestroy()
    }
}
