// Edit this file to change what appears on your home screen.
// "id" is the webOS app ID. To list every app ID installed on your TV, run:
//   ares-launch --device mytv --list
// "color" is the tile colour and also tints the background glow when focused.
window.HOME_CONFIG = {
  rows: [
    {
      title: "Streaming",
      tiles: [
        { name: "Netflix", id: "netflix", color: "#b3261e", text: "#ffffff" },
        { name: "prime video", id: "amazon", color: "#3b8cf0", text: "#ffffff" },
        { name: "YouTube", id: "youtube.leanback.v4", color: "#f5f5f5", text: "#d01818" },
        { name: "Disney+", id: "com.disney.disneyplus-prod", color: "#1d2d8c", text: "#ffffff" }
      ]
    },
    {
      title: "More",
      tiles: [
        { name: "Apple TV", id: "com.apple.appletv", color: "#2a6b35", text: "#ffffff" },
        { name: "Live TV", id: "com.webos.app.livetv", color: "#26262b", text: "#ffffff" },
        { name: "Web Browser", id: "com.webos.app.browser", color: "#4a2a8c", text: "#ffffff" },
        { name: "Music", id: "spotify-beehive", color: "#7a5a1f", text: "#ffffff" }
      ]
    }
  ],
  // Top-right buttons
  pills: [
    { label: "Inputs", icon: "input", id: "com.webos.app.hdmi1" },
    { label: "Wi-Fi", icon: "wifi", id: "com.palm.app.settings", params: { target: "network" } },
    { label: "Settings", icon: "gear", id: "com.palm.app.settings" }
  ]
};
