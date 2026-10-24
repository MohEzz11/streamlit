// Edit this file to change what appears on your home screen.
//
// Tiles: "match" finds the app on your TV by its name, so you do not need the
// exact app ID. "id" is used only if the name search finds nothing.
// To list every app installed on your TV:  ares-launch --device mytv --list
window.HOME_CONFIG = {
  rows: [
    {
      title: "Watch",
      tiles: [
        { name: "Netflix", match: "netflix", id: "netflix", color: "#b3261e", text: "#ffffff" },
        { name: "Shahid", match: "shahid", color: "#1db954", text: "#ffffff" },
        { name: "OSN+", match: "osn", color: "#111111", text: "#ffffff" },
        { name: "prime video", match: "prime video", id: "amazon", color: "#3b8cf0", text: "#ffffff" },
        { name: "Disney+", match: "disney", id: "com.disney.disneyplus-prod", color: "#1d2d8c", text: "#ffffff" },
        { name: "YouTube", match: "youtube", id: "youtube.leanback.v4", color: "#f5f5f5", text: "#d01818" },
        { name: "Apple TV", match: "apple tv", id: "com.apple.appletv", color: "#2b2b2f", text: "#ffffff" },
        { name: "STARZPLAY", match: "starz", color: "#0f1a33", text: "#ffffff" }
      ]
    },
    {
      title: "Live, Sport & Music",
      tiles: [
        { name: "Live TV", id: "com.webos.app.livetv", color: "#26262b", text: "#ffffff" },
        { name: "beIN CONNECT", match: "bein", color: "#5b1a7a", text: "#ffffff" },
        { name: "YouTube Kids", match: "youtube kids", color: "#e2312d", text: "#ffffff" },
        { name: "Spotify", match: "spotify", id: "spotify-beehive", color: "#1a7f3c", text: "#ffffff" },
        { name: "Anghami", match: "anghami", color: "#7b2ff7", text: "#ffffff" },
        { name: "Web Browser", id: "com.webos.app.browser", color: "#3a3a8c", text: "#ffffff" }
      ]
    }
  ],

  // Adds a final row with every app installed on the TV, so all your
  // favourites are always reachable. Set to false to hide it.
  showAllApps: true,

  // Top-right buttons
  pills: [
    { label: "Inputs", icon: "input", id: "com.webos.app.hdmi1" },
    { label: "Wi-Fi", icon: "wifi", id: "com.palm.app.settings", params: { target: "network" } },
    { label: "Settings", icon: "gear", id: "com.palm.app.settings" }
  ],

  // Prayer times are calculated on the TV, no internet needed.
  // Defaults: Dubai, UAE Awqaf angles (Fajr 18.2, Isha 18.2), Asr Shafi'i.
  // Abu Dhabi: 24.4539, 54.3773   Sharjah: 25.3463, 55.4209   Riyadh: 24.7136, 46.6753
  // "offsets" are minutes added to each time: use them to match your mosque or the Awqaf app.
  prayer: {
    city: "Dubai",
    lat: 25.2048,
    lng: 55.2708,
    fajrAngle: 18.2,
    ishaAngle: 18.2,
    asrFactor: 1, // 1 = Shafi'i/Maliki/Hanbali, 2 = Hanafi
    offsets: { fajr: 0, sunrise: 0, dhuhr: 0, asr: 0, maghrib: 0, isha: 0 }
  },

  // Background photos. Local photos in app/backgrounds/ are shown first.
  // If there are none, the TV downloads green nature photos from
  // Wikimedia Commons (free licence, credit shown in the corner).
  // If the TV is offline, the bundled green-hills image is used.
  backgrounds: {
    local: [],
    online: true,
    categories: [
      "Category:Featured pictures of forests",
      "Category:Featured pictures of trees",
      "Category:Featured pictures of waterfalls",
      "Category:Quality images of forests"
    ],
    fallback: "backgrounds/fallback-green-hills.jpg",
    changeEverySeconds: 90
  }
};
