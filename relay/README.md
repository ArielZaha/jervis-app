# Jervis relay — deploy steps

This is the small always-on router that lets a paired phone reach Jervis when it isn't on the same Wi-Fi as the
computer (see `server.py`'s docstring for what it does and, just as importantly, what it deliberately doesn't see).
It's a separate deployable service from the Jervis app itself, built from the **repo root** `Dockerfile` (not a
file in this folder — see that Dockerfile's own comment for why) — every command below assumes you're in the repo
root, not `relay/`.

**Most people don't need to deploy this.** Jervis ships with `JERVIS_RELAY_URL` already pointed at a shared relay
that every install uses by default, same as any other bundled service. It's safe to share: the relay never sees a
device token, a pairing code, or an encryption key, and every message it routes is end-to-end encrypted per phone
(phone_crypto.py) — it only ever sees which computerId a connection belongs to, a value with no meaning on its
own. Deploy your own only if you want to run that piece yourself instead of relying on the shared one.

## Render (recommended — genuinely free, no credit card)

1. Install the CLI (`brew install render` on macOS; see <https://render.com/docs/cli> otherwise), then
   `render login` — this opens your browser to sign in or create a free Render account.
2. From the repo root:
   ```
   render services create --name jervis-relay --type web_service --runtime docker \
     --repo https://github.com/ArielZaha/jervis-app --branch main --root-directory . \
     --plan free --region oregon --output json
   ```
   (Render finds `Dockerfile` at the repo root automatically for a Docker-runtime service — nothing further to
   point at it.) If the name's taken, pick another; it becomes part of the URL.
3. Your relay's address is `wss://<service-name>.onrender.com/`. Set that as `JERVIS_RELAY_URL` in Jervis's
   Settings (Computer control, advanced), replacing the shared default — or as the `JERVIS_RELAY_URL` environment
   variable if you're running from source.

Later updates: `render deploys create <service-id>`, or just push to the connected branch — auto-deploy is on by
default.

**The free tier's one real tradeoff:** a Render free service spins down after 15 minutes with no inbound traffic
(HTTP requests *or* WebSocket messages). Jervis's own keepalive ping (`relay/server.py`'s `_keepalive`, every 25s)
keeps it awake the whole time your computer is running and connected, so in normal use this never matters. If the
relay *has* gone fully to sleep (computer was off a while), the next request wakes it in 30-60 seconds — your phone
might see a brief delay on the very first reconnect, nothing more; `relay_client.py` already retries with backoff.

## Fly.io (an alternative — needs a credit card once your trial ends)

1. Install the Fly CLI and sign in: <https://fly.io/docs/flyctl/install/>, then `flyctl auth login`.
2. From the repo root:
   ```
   flyctl launch --config relay/fly.toml --dockerfile Dockerfile --no-deploy
   ```
   It reads `relay/fly.toml` and offers to create an app named `jervis-relay`. If that name's taken (app names are
   global on Fly), pick another and update the `app =` line in `relay/fly.toml` to match.
3. Deploy:
   ```
   flyctl deploy --config relay/fly.toml --dockerfile Dockerfile
   ```
4. Your relay's address is `wss://<app-name>.fly.dev/` (the `http_service` block in `fly.toml` already forces
   HTTPS/WSS). Set that as `JERVIS_RELAY_URL`, same as above.

Fly's free trial ends after a while, and keeping the app running after that needs a card on file (pay-as-you-go —
see Fly's own pricing, not repeated here since it changes). Render's free tier has no such expiry, which is why
it's the default above.

## Cost

The shared default relay runs under Ariel's account — its cost and uptime scale with how many people use phone
control, not with any one person's usage, which is worth remembering before assuming it'll stay free forever as
adoption grows.

For your own instance, either platform's smallest free/cheap tier is all this needs — a few lines of JSON routed
occasionally, no heavy compute or storage.
