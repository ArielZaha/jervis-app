"""The real Jarvis phone server (app.py, sandboxed: tools record instead of acting) with a stand-in main loop, for
the mobile app's live tests. Optional relay (RELAY=ws://...). Control API on CTRL: /pair /kick /end /state."""
import json, os, sys, threading, time, traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, ROOT); sys.path.insert(0, os.path.join(ROOT, "tests"))
os.environ["JARVIS_PHONE_CONTROL"] = "on"
os.environ["JARVIS_PHONE_PORT"] = os.environ.get("PORT", "8797")
os.environ["JARVIS_RELAY_URL"] = os.environ.get("RELAY", "")
import sandbox
sandbox.install()
os.environ["GROQ_API_KEY"] = os.environ.get("HARNESS_GROQ_KEY", "")
import app
app.GROQ_KEY = os.environ["GROQ_API_KEY"]
threading.Thread(target=app.run_phone_server, daemon=True).start()
if app.RELAY_URL:
    import relay_client
    threading.Thread(target=relay_client.run_relay_client, args=(app.relay,), daemon=True).start()


def fake_main_loop():
    while True:
        text = app.typed_inputs.get()
        try:
            app.broadcast("user", text)
            app.send_status("thinking")
            time.sleep(0.3)
            try:
                reply = app.handle_direct_command(str(text)) or f"Computer here: {text}"
            except Exception:
                traceback.print_exc(); reply = "Sorry, something went wrong with that command."
            app.broadcast("ai", reply)
            app.reply_to_phone_if_needed(text, str(reply))
            app.send_status("listening")
        except Exception:
            traceback.print_exc()


threading.Thread(target=fake_main_loop, daemon=True).start()


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urlsplit(self.path)
        out = {}
        if u.path == "/pair":
            app.start_phone_pairing()
            out.update(app.latest_ui_updates.get("phone_pairing", {}).get("data", {}))
        elif u.path == "/kick":
            for st in list(app.session_router._conns.values()):
                st["schedule_end"] and st["schedule_end"]()
        elif u.path == "/end":
            out["reply"] = app.disconnect_phone_session()
        elif u.path == "/state":
            out["connected"] = app.session_router.connected_device_names()
            out["devices"] = app.phone_server.registry.list()
            out["history"] = [{"role": m["role"], "content": m["content"]} for m in (app.chat_history or [])[-4:]]
            out["window"] = list(app.phone_chat_history)[-4:]
        elif u.path == "/set_history":
            app.chat_history = [{"role": "system", "content": "x"}]
        body = json.dumps(out).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(body)


print("harness ready", flush=True)
ThreadingHTTPServer(("127.0.0.1", int(os.environ.get("CTRL", "8796"))), H).serve_forever()
