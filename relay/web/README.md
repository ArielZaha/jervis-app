The phone app's copies of the window's drawing scripts (graph.js, earth.js, planet.js), served by the relay
(relay/server.py's VISUAL_FILES; the Dockerfile copies them in).

They are kept apart from the copies at the repo root on purpose: these are the versions the phone app
(phone_client.html) is written for, and they are newer than this branch's desktop window (index.html) expects.
The root copies belong to the window and are not touched. Once the window is updated to the same versions, this
folder can go and the Dockerfile can copy the root files again.
