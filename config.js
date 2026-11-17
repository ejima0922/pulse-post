// Pulse Post runtime configuration.
// clientKey: the TikTok app client key (public identifier, safe to expose).
// backendUrl: the Pulse Post server origin (no trailing slash).
window.PULSE_POST_CONFIG = {
  clientKey: "",
  backendUrl: "https://pulse-post-server.onrender.com",
  redirectUri: "https://ejima0922.github.io/pulse-post/callback.html",
  scopes: "user.info.basic,video.upload"
};
