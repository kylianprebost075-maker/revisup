// Service worker de l'app RevisUP : notifications (Web Push). Pas de cache hors ligne : les données sont sur le PC.

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (ev) => ev.waitUntil(self.clients.claim()));

self.addEventListener("push", (ev) => {
  let d = {};
  try { d = ev.data ? ev.data.json() : {}; } catch { d = { texte: ev.data ? ev.data.text() : "" }; }
  ev.waitUntil(self.registration.showNotification(d.titre || "RevisUP", {
    body: d.texte || "",
    tag: d.tag || undefined,
    icon: "/static/icones/icone-192.png",
    badge: "/static/icones/icone-192.png",
    data: { url: d.url || "/#/" },
    actions: d.actions || [],  // boutons (ordinateur, Android) ; sur iPhone, toucher la notification ouvre la page
  }));
});

self.addEventListener("notificationclick", (ev) => {
  ev.notification.close();
  let url = (ev.notification.data && ev.notification.data.url) || "/#/";
  if (ev.action) url = `/#/journee?choix=${encodeURIComponent(ev.action)}`;
  ev.waitUntil((async () => {
    const fenetres = await self.clients.matchAll({ type: "window", includeUncontrolled: true });
    for (const f of fenetres) {
      if ("focus" in f) {
        await f.focus();
        if ("navigate" in f) await f.navigate(url);
        return;
      }
    }
    await self.clients.openWindow(url);
  })());
});
