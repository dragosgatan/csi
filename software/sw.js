// service worker for the CSI security PWA: job is to show the alarm
// notification when the server pushes, even with the app closed.

self.addEventListener("install", (event) => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(clients.claim()));

// chrome will not offer to install the app unless the worker has a fetch handler
self.addEventListener("fetch", (event) => { return; });

self.addEventListener("push", (event) => {
  let data = { title: "Intruder detected", body: "Movement in a room that should be empty." };
  try { if (event.data) data = event.data.json(); } catch (err) { /* keep the default text */ }

  event.waitUntil(self.registration.showNotification(data.title, {
    body: data.body,
    tag: "csi-intruder",          // one alarm at a time
    renotify: true,
    requireInteraction: true,     // an intruder alert must not auto-dismiss unseen
    vibrate: [400, 200, 400, 200, 400],
    data: { url: "/mobile" },
  }));
});

// tapping the alarm opens the app, which is what plays the siren
self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  event.waitUntil(clients.matchAll({ type: "window", includeUncontrolled: true }).then((list) => {
    for (const client of list) {
      if (client.url.includes("/mobile")) return client.focus();
    }
    return clients.openWindow("/mobile");
  }));
});
