// Android 11+ hides other installed apps from an app unless its manifest asks to see them. Jarvis opens apps by
// name ("open Spotify"), so it declares that it needs to see launchable apps (the standard <queries> entry for
// launcher activities, not the broad QUERY_ALL_PACKAGES permission) plus the intents it fires.
const { withAndroidManifest } = require("@expo/config-plugins");

const intent = (action, extra = {}) => ({ action: [{ $: { "android:name": action } }], ...extra });

module.exports = function withLauncherQueries(config) {
  return withAndroidManifest(config, (cfg) => {
    const manifest = cfg.modResults.manifest;
    manifest.queries = manifest.queries || [];
    manifest.queries.push({
      intent: [
        intent("android.intent.action.MAIN", { category: [{ $: { "android:name": "android.intent.category.LAUNCHER" } }] }),
        intent("android.intent.action.VIEW", { data: [{ $: { "android:scheme": "https" } }] }),
        intent("android.intent.action.VIEW", { data: [{ $: { "android:scheme": "geo" } }] }),
        intent("android.intent.action.DIAL"),
        intent("android.intent.action.SENDTO", { data: [{ $: { "android:scheme": "smsto" } }] }),
        intent("android.intent.action.SET_ALARM"),
        intent("android.intent.action.SET_TIMER"),
        intent("android.media.action.STILL_IMAGE_CAMERA"),
      ],
    });
    return cfg;
  });
};
