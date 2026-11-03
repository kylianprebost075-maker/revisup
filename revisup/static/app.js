"use strict";
// RevisUP — tableau de bord (aucune dépendance obligatoire : marked/DOMPurify/KaTeX améliorent l'affichage s'ils chargent)

const $ = (s, el = document) => el.querySelector(s);
const vue = $("#vue");
let ETAT = null;
let minuterie = null;

// ── utilitaires ──────────────────────────────────────────────────────────
const esc = (t) => String(t ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const JOURS = ["dim.", "lun.", "mar.", "mer.", "jeu.", "ven.", "sam."];
const JOURS_LONGS = ["Dimanche", "Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi"];
const MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];
const d = (iso) => new Date(iso);
const hm = (iso) => d(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" }).replace(":", "h");
const dateCourte = (iso) => { const x = d(iso); return `${JOURS[x.getDay()]} ${x.getDate()} ${MOIS[x.getMonth()]}`; };
const cleJour = (iso) => { const x = d(iso); return `${x.getFullYear()}-${x.getMonth()}-${x.getDate()}`; };
function couleur(texte) {
  let h = 0;
  for (const c of String(texte)) h = (h * 31 + c.charCodeAt(0)) % 360;
  return `hsl(${h} 65% 48%)`;
}
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg; t.hidden = false;
  clearTimeout(t._m); t._m = setTimeout(() => (t.hidden = true), 4000);
}
async function api(url, options = {}) {
  const r = await fetch(url, options);
  const ct = r.headers.get("content-type") || "";
  const corps = ct.includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw new Error((corps && corps.message) || `Erreur ${r.status}`);
  return corps;
}
const post = (url, data) => api(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data || {}) });

function md(texte) {
  if (!window.marked || !window.DOMPurify) return `<pre style="white-space:pre-wrap">${esc(texte)}</pre>`;
  const maths = [];
  let src = String(texte || "")
    .replace(/\\\[([\s\S]+?)\\\]/g, (_, m) => `$$${m}$$`)  // notations LaTeX \[ \] et \( \) (IA locale)
    .replace(/\\\(([\s\S]+?)\\\)/g, (_, m) => `$${m}$`)
    .replace(/\$\$([\s\S]+?)\$\$/g, (_, m) => { maths.push([m, true]); return `@@M${maths.length - 1}@@`; })
    .replace(/(^|[^\\$])\$([^\n$]+?)\$/g, (_, avant, m) => { maths.push([m, false]); return `${avant}@@M${maths.length - 1}@@`; });
  // Le contenu généré est du Markdown, pas du HTML : une balise écrite telle quelle (« <p> », « <img src=…> »,
  // le sujet même d'un cours de Web) doit s'afficher, pas être interprétée. Le code entre ` ` est déjà protégé.
  src = src.split(/(```[\s\S]*?```|`[^`\n]*`)/g).map((m, i) => (i % 2 ? m : m.replace(/</g, "&lt;"))).join("");
  let html = DOMPurify.sanitize(marked.parse(src));
  return html.replace(/@@M(\d+)@@/g, (_, i) => {
    const [m, bloc] = maths[+i];
    if (!window.katex) return esc(bloc ? `$$${m}$$` : `$${m}$`);
    try { return katex.renderToString(m, { displayMode: bloc, throwOnError: false }); } catch { return esc(m); }
  });
}

const STATUTS = {
  a_preparer: ["à préparer", ""], en_cours: ["préparation…", "alerte"], pret: ["pack prêt", "ok"],
  prompt_manuel: ["prompt à lancer", "alerte"], erreur: ["erreur", "danger"],
};
const badgeStatut = (s) => { const [t, c] = STATUTS[s] || [s || "?", ""]; return `<span class="badge ${c}">${esc(t)}</span>`; };
const SOURCES = { edt: "UPplanning", updago: "UPdago", message: "message d'un prof", manuel: "ajouté à la main" };

// ── chargement / rafraîchissement ────────────────────────────────────────
async function charger() {
  try { ETAT = await api("/api/etat"); }
  catch (e) { vue.innerHTML = `<p class="vide">Serveur injoignable : ${esc(e.message)}</p>`; return; }
  const t = $("#tache");
  t.hidden = !ETAT.tache.nom;
  t.textContent = ETAT.tache.nom ? `${ETAT.tache.nom} en cours… (journal dans Réglages)` : "";
  $("#btn-sync").disabled = !!ETAT.tache.nom;
  clearTimeout(minuterie);
  minuterie = setTimeout(rafraichir, ETAT.tache.nom ? 4000 : 30000);
}
async function rafraichir() {
  const enCours = ETAT && ETAT.tache.nom;
  await charger();
  // on ne redessine pas une fiche d'examen (QCM en cours) ni les notes (graphiques), sauf si une tâche vient de finir
  const stable = ["#/examen/", "#/notes", "#/journee", "#/jeux"].some((p) => location.hash.startsWith(p));
  if (!stable || (enCours && !ETAT.tache.nom)) router();
}

$("#btn-sync").onclick = async () => {
  const r = await post("/api/synchro");
  toast(r.ok ? "Synchronisation lancée : EDT, UPdago, IA locale puis Claude." : r.message);
  rafraichir();
};

// ── routeur ──────────────────────────────────────────────────────────────
async function router() {
  if (!ETAT) await charger();
  if (!ETAT) return;
  const [chemin, requete] = location.hash.split("?");
  const [, page, id, sous] = chemin.split("/");
  document.querySelectorAll("nav a").forEach((a) => a.classList.toggle("actif",
    a.dataset.onglet === (page === "examen" ? "examens" : page || "accueil")));
  if (page === "journee") return vueJournee(new URLSearchParams(requete || "").get("choix"));
  if (page === "jeux") return vueJeux(id, sous && decodeURIComponent(sous));
  if (page === "planning") return vuePlanning();
  if (page === "examens") return vueExamens();
  if (page === "examen" && id) return vueExamen(decodeURIComponent(id));
  if (page === "reglages") return vueReglages();
  if (page === "notes") return vueNotes();
  return vueAccueil();
}
window.addEventListener("hashchange", router);

// ── accueil ──────────────────────────────────────────────────────────────
function carteExamen(e) {
  const fait = ETAT.sessions.filter((s) => s.examen_id === e.id && d(s.fin) < new Date() && !s.ratee).length;
  const total = ETAT.sessions.filter((s) => s.examen_id === e.id).length;
  const infos = e.infos || {};
  return `<div class="carte cliquable examen-carte" style="--couleur:${couleur(e.matiere)}" onclick="location.hash='#/examen/${encodeURIComponent(e.id)}'">
    <div class="compte">${e.jours <= 0 ? "Auj." : "J-" + e.jours}<small>${dateCourte(e.debut)}</small></div>
    <div>
      <div class="titre">${esc(e.matiere)}</div>
      <div class="doux">${hm(e.debut)}${e.salle || infos.salle ? " · " + esc(infos.salle || e.salle) : ""}${e.heure_incertaine ? " · heure à confirmer" : ""}</div>
      <div style="margin-top:.35rem">${badgeStatut(e.statut)} ${total ? `<span class="badge">${fait}/${total} sessions</span>` : ""}</div>
    </div></div>`;
}

function ligneAgenda(item) {
  if (item.kind === "cours")
    return `<div class="ligne-agenda cours"><span class="heure">${hm(item.debut)}–${hm(item.fin)}</span>
      <span class="quoi">${esc(item.titre)} <span class="doux">${esc(item.lieu || "")}</span></span></div>`;
  if (item.kind === "examen")
    return `<div class="ligne-agenda examen"><span class="heure">${hm(item.debut)}–${hm(item.fin)}</span>
      <a class="quoi" href="#/examen/${encodeURIComponent(item.id)}">🎓 EXAMEN ${esc(item.matiere)} <span class="doux">${esc(item.salle || "")}</span></a></div>`;
  const passe = d(item.fin) < new Date();
  const classe = item.ratee ? "ratee" : item.faite || passe ? "faite" : "";
  return `<div class="ligne-agenda ${classe}" style="--couleur:${couleur(item.matiere)}">
    <span class="heure">${hm(item.debut)}–${hm(item.fin)}</span>
    <span class="quoi"><a href="#/examen/${encodeURIComponent(item.examen_id)}"><b>${esc(item.matiere)}</b></a> — ${esc(item.tache)}</span>
    <span class="actions">
      ${item.ratee ? `<button class="btn petit" onclick="marquer('${esc(item.cle)}','annuler')">↺</button>`
        : `${passe || item.faite ? "" : `<button class="btn petit" title="Déjà faite" onclick="marquer('${esc(item.cle)}','faite')">✓</button>`}
           <button class="btn petit" title="Ratée : la replanifier" onclick="marquer('${esc(item.cle)}','ratee')">✗</button>`}
    </span></div>`;
}
window.marquer = async (cle, statut) => {
  await post("/api/session/marquer", { cle, statut });
  toast(statut === "ratee" ? "Session replanifiée plus tard." : statut === "faite" ? "Bravo ! Planning mis à jour." : "Marque retirée.");
  await charger(); router();
};

function elementsDuJour(jour) {
  const k = cleJour(jour);
  return [
    ...ETAT.cours_edt.filter((c) => cleJour(c.debut) === k).map((c) => ({ ...c, kind: "cours" })),
    ...ETAT.examens.filter((e) => cleJour(e.debut) === k).map((e) => ({ ...e, kind: "examen" })),
    ...ETAT.sessions.filter((s) => cleJour(s.debut) === k).map((s) => ({ ...s, kind: "session" })),
  ].sort((a, b) => d(a.debut) - d(b.debut));
}

function vueAccueil() {
  const futurs = ETAT.examens.filter((e) => d(e.fin) >= new Date() && !e.ignore);
  const auj = elementsDuJour(new Date().toISOString());
  const demain = new Date(Date.now() + 864e5);
  const demainItems = elementsDuJour(demain.toISOString()).filter((x) => x.kind !== "cours");
  const s = ETAT.services;
  const aConfigurer = [];
  if (ETAT.demo) aConfigurer.push("<b>mode démo</b> : données fictives, rien n'est envoyé (lance <code>python -m revisup web</code> pour la vraie version)");
  else if (!s.edt.ok) aConfigurer.push("ajoute l'URL iCal UPplanning dans <code>config.toml</code>");
  if (!s.updago.ok) aConfigurer.push("connecte UPdago : <code>python -m revisup connexion</code>");
  if (!s.ia_locale.ok) aConfigurer.push("lance le serveur local de LM Studio");
  vue.innerHTML = `
    ${aConfigurer.length ? `<div class="alerte-boite">À faire : ${aConfigurer.join(" · ")}</div>` : ""}
    ${ETAT.alertes.map((a) => `<div class="alerte-boite">⚠️ ${esc(a)}</div>`).join("")}
    <h1>Prochains examens</h1>
    ${futurs.length ? `<div class="grille">${futurs.map(carteExamen).join("")}</div>`
      : `<p class="vide">Aucun examen détecté pour l'instant. Synchronise, ou ajoute-en un dans Réglages.</p>`}
    <h2>Aujourd'hui</h2>
    ${auj.length ? auj.map(ligneAgenda).join("") : `<p class="doux">Rien de prévu.</p>`}
    ${demainItems.length ? `<h2>Demain</h2>${demainItems.map(ligneAgenda).join("")}` : ""}
    ${ETAT.echeances.length ? `<h2>Échéances UPdago</h2>${ETAT.echeances.map((e) =>
      `<div class="ligne-agenda"><span class="heure">${dateCourte(e.debut)}</span><span class="quoi">${esc(e.titre)}
       <span class="doux">${esc(e.cours_nom)}</span></span></div>`).join("")}` : ""}`;
}

// ── planning ─────────────────────────────────────────────────────────────
function vuePlanning() {
  let html = `<h1>Planning de révision</h1>
    <p class="doux">Sessions placées dans tes créneaux libres (cours retirés). ✓ = déjà faite, ✗ = ratée (replanifiée).
    <a href="/planning.ics">S'abonner / exporter (.ics)</a> · généré ${ETAT.planning_genere_le ? dateCourte(ETAT.planning_genere_le) + " à " + hm(ETAT.planning_genere_le) : "jamais"}
    · <a href="#" onclick="recalculer();return false">recalculer</a></p>
    ${ETAT.alertes.map((a) => `<div class="alerte-boite">⚠️ ${esc(a)}</div>`).join("")}`;
  const debut = new Date(); debut.setHours(0, 0, 0, 0);
  let vu = 0;
  for (let i = 0; i < 21; i++) {
    const jour = new Date(debut.getTime() + i * 864e5);
    const items = elementsDuJour(jour.toISOString());
    if (!items.some((x) => x.kind !== "cours") && i > 0) continue;
    vu++;
    html += `<div class="jour ${i === 0 ? "aujourdhui" : ""}"><h3>${JOURS_LONGS[jour.getDay()]} ${jour.getDate()} ${MOIS[jour.getMonth()]}</h3>
      ${items.length ? items.map(ligneAgenda).join("") : `<p class="doux">Rien de prévu.</p>`}</div>`;
  }
  if (!ETAT.sessions.length) html += `<p class="vide">Pas encore de sessions : il faut au moins un examen à venir.</p>`;
  vue.innerHTML = html;
}
window.recalculer = async () => { await post("/api/planning"); await charger(); router(); toast("Planning recalculé."); };

// ── liste des examens ────────────────────────────────────────────────────
function vueExamens() {
  const tous = ETAT.examens;
  vue.innerHTML = `<h1>Examens</h1>
    ${tous.length ? `<div class="grille">${tous.map(carteExamen).join("")}</div>` : `<p class="vide">Aucun examen.</p>`}
    <h2>Ajouter un examen</h2>${formAjout()}`;
  brancherAjout();
}
function formAjout() {
  return `<form class="ligne carte" id="form-ajout">
    <label>Matière <input name="matiere" required placeholder="Analyse 1"></label>
    <label>Date <input name="date" type="date" required></label>
    <label>Heure <input name="heure" type="time" value="08:30"></label>
    <label>Durée (min) <input name="duree" type="number" value="120" style="width:6rem"></label>
    <label>Salle <input name="salle" placeholder="Amphi A" style="width:8rem"></label>
    <button class="btn principal">Ajouter</button></form>`;
}
function brancherAjout() {
  const f = $("#form-ajout");
  if (!f) return;
  f.onsubmit = async (ev) => {
    ev.preventDefault();
    const r = await post("/api/examens", Object.fromEntries(new FormData(f)));
    toast("Examen ajouté. Lance « Préparer » sur sa fiche.");
    await charger(); location.hash = `#/examen/${encodeURIComponent(r.id)}`;
  };
}

// ── fiche d'un examen ────────────────────────────────────────────────────
const NOMS_CAT = { annale: "Anciens examens", corrige: "Corrigés", cours: "Cours", td: "TD", tp: "TP", autre: "Autres", "?": "Pas encore triés" };

async function vueExamen(id) {
  let data;
  try { data = await api(`/api/examen/${encodeURIComponent(id)}`); }
  catch { vue.innerHTML = `<p class="vide">Examen introuvable.</p>`; return; }
  const { examen: e, pack, messages, documents, cours, lecons_en_cours, lecons_lues } = data;
  const infos = e.infos || {};
  const occupe = !!ETAT.tache.nom;
  const lignesInfos = [["Salle", infos.salle || e.salle], ["Durée", infos.duree], ["Documents autorisés", infos.documents_autorises],
    ["Programme", infos.programme], ["Consignes", infos.consignes]].filter(([, v]) => v);

  vue.innerHTML = `
    <p><a href="#/examens">← Examens</a></p>
    <div class="carte examen-carte" style="--couleur:${couleur(e.matiere)}">
      <div class="compte">${e.jours <= 0 ? "Auj." : "J-" + e.jours}<small>${dateCourte(e.debut)}</small></div>
      <div style="flex:1">
        <h1 style="margin:0">${esc(e.matiere)}</h1>
        <div class="doux">${esc(e.titre || "")} · ${hm(e.debut)}–${hm(e.fin)} · détecté via ${esc(SOURCES[e.source] || e.source)}
          ${e.cours_nom ? ` · cours UPdago : <b>${esc(e.cours_nom)}</b>` : ""}</div>
        <div style="margin-top:.5rem;display:flex;gap:.4rem;flex-wrap:wrap;align-items:center">
          ${badgeStatut(e.statut)}
          <button class="btn ${pack ? "" : "principal"}" id="btn-preparer" ${occupe ? "disabled" : ""}>${pack ? "↻ Régénérer le pack" : "▶ Préparer le pack"}</button>
          <button class="btn" id="btn-ignorer">${e.ignore ? "Ne plus ignorer" : "Ignorer cet examen"}</button>
        </div>
        ${e.erreur ? `<div class="alerte-boite" style="margin-top:.6rem">${esc(e.erreur)}</div>` : ""}
      </div>
    </div>

    ${!e.cours_id && cours.length ? `<div class="carte" style="margin-top:.8rem">
      <b>Quel cours UPdago correspond à cet examen ?</b>
      <form class="ligne" id="form-cours" style="margin-top:.4rem"><select name="cours_id">${cours.map((c) => `<option value="${c.id}">${esc(c.nom)}</option>`).join("")}</select>
      <button class="btn principal">Associer</button></form></div>` : ""}

    ${e.statut === "prompt_manuel" ? `<div class="carte" style="margin-top:.8rem">
      <b>Mode manuel</b> : <a href="/api/examen/${encodeURIComponent(e.id)}/prompt" target="_blank">ouvre le prompt</a>, copie-le dans claude.ai,
      puis colle la réponse JSON ici :<textarea id="reponse-json" placeholder='{"synthese_markdown": "...", ...}'></textarea>
      <button class="btn principal" id="btn-importer">Importer la réponse</button></div>` : ""}

    <h2>Infos pratiques</h2>
    <div class="carte">
      ${lignesInfos.length ? lignesInfos.map(([k, v]) => `<div><b>${k} :</b> ${esc(v)}</div>`).join("") : `<p class="doux" style="margin:0">Aucune info trouvée dans les messages des profs.</p>`}
      <details><summary class="doux">Compléter à la main</summary>
        <form class="ligne" id="form-infos" style="margin-top:.5rem">
          <label>Salle <input name="salle" value="${esc(infos.salle || "")}"></label>
          <label>Documents autorisés <input name="documents_autorises" value="${esc(infos.documents_autorises || "")}"></label>
          <label style="flex:1;min-width:14rem">Programme <input name="programme" value="${esc(infos.programme || "")}"></label>
          <button class="btn">Enregistrer</button></form></details>
    </div>

    ${pack ? `<div class="onglets" id="onglets">
        <button data-o="lecons" class="actif">🎓 Leçons</button>
        <button data-o="synthese">Fiche</button>
        <button data-o="exercices">Exercices (${pack.exercices.length})</button>
        <button data-o="qcm">QCM (${pack.qcm.length})</button>
        <button data-o="essentiel">L'essentiel</button>
        <button data-o="sources">Sources</button></div>
      <div id="contenu-onglet"></div>`
    : `<h2>Sources trouvées</h2><div id="contenu-onglet"></div>`}`;

  const onglets = {
    lecons: () => `<div id="lecons"></div>`,
    synthese: () => `<div class="carte md">${md(pack.synthese_markdown)}</div>`,
    exercices: () => pack.exercices.map((x, i) => `<div class="carte" style="margin-bottom:.7rem">
        <h3 style="margin-top:0">${i + 1}. ${esc(x.titre)} <span class="badge ${x.difficulte === "difficile" ? "danger" : x.difficulte === "moyen" ? "alerte" : "ok"}">${esc(x.difficulte)}</span>
        <span class="doux">${esc(x.chapitre)}</span></h3>
        <div class="md">${md(x.enonce_markdown)}</div>
        <details><summary>Voir le corrigé</summary><div class="md">${md(x.corrige_markdown)}</div></details>
        <div class="zone-ia" data-ex="${i}"></div></div>`).join(""),
    qcm: () => `<div id="qcm"></div>`,
    essentiel: () => `
      <div class="carte"><h3 style="margin-top:0">Chapitres et temps de révision estimé</h3>
        ${pack.chapitres.map((c) => `<div style="margin:.4rem 0"><b>${esc(c.titre)}</b> ${"★".repeat(Math.max(1, Math.min(5, c.importance)))}
          <span class="doux">· ~${c.heures_estimees} h</span><div class="doux">${esc(c.resume)}</div></div>`).join("")}</div>
      <h3>Points clés</h3><div class="carte md"><ul>${pack.points_cles.map((p) => `<li>${md(p)}</li>`).join("")}</ul></div>
      <h3>Pièges classiques</h3><div class="carte md"><ul>${pack.pieges.map((p) => `<li>${md(p)}</li>`).join("")}</ul></div>
      <h3>Ce que disent les annales</h3><div class="carte md">${md(pack.analyse_annales)}</div>
      <h3>Le jour J</h3><div class="carte md">${md(pack.methode_jour_j)}</div>`,
    sources: () => sources(messages, documents, pack),
  };
  const zone = $("#contenu-onglet");
  if (pack) {
    const afficher = (o) => {
      document.querySelectorAll("#onglets button").forEach((b) => b.classList.toggle("actif", b.dataset.o === o));
      zone.innerHTML = onglets[o]();
      if (o === "qcm") qcm(pack.qcm, $("#qcm"));
      if (o === "lecons") vueLecons($("#lecons"), e, pack, lecons_en_cours, lecons_lues);
      if (o === "exercices") zone.querySelectorAll("[data-ex]").forEach((z) => {
        const x = pack.exercices[+z.dataset.ex];
        boiteIA(z, { type: "exercice", matiere: e.matiere, titre: x.titre, enonce: x.enonce_markdown, corrige: x.corrige_markdown });
      });
    };
    document.querySelectorAll("#onglets button").forEach((b) => (b.onclick = () => afficher(b.dataset.o)));
    afficher("lecons");
  } else {
    zone.innerHTML = sources(messages, documents, null);
  }

  $("#btn-preparer").onclick = async () => {
    const r = await post(`/api/examen/${encodeURIComponent(e.id)}/preparer`);
    toast(r.ok ? "Préparation lancée : IA locale (tri, messages, fichiers) puis Claude. Ça peut prendre quelques minutes." : r.message);
    await charger(); router();
  };
  $("#btn-ignorer").onclick = async () => {
    await post(`/api/examen/${encodeURIComponent(e.id)}/modifier`, { ignore: !e.ignore });
    await charger(); router();
  };
  const fc = $("#form-cours");
  if (fc) fc.onsubmit = async (ev) => {
    ev.preventDefault();
    await post(`/api/examen/${encodeURIComponent(e.id)}/modifier`, { cours_id: new FormData(fc).get("cours_id") });
    toast("Cours associé. Clique sur « Préparer le pack »."); await charger(); router();
  };
  const fi = $("#form-infos");
  fi.onsubmit = async (ev) => {
    ev.preventDefault();
    await post(`/api/examen/${encodeURIComponent(e.id)}/modifier`, { infos: Object.fromEntries(new FormData(fi)) });
    toast("Infos enregistrées (elles seront données à Claude)."); await charger(); router();
  };
  const bi = $("#btn-importer");
  if (bi) bi.onclick = async () => {
    try {
      await api(`/api/examen/${encodeURIComponent(e.id)}/pack`, { method: "POST", body: $("#reponse-json").value });
      toast("Pack importé !"); await charger(); router();
    } catch (err) { toast(err.message); }
  };
}

function sources(messages, documents, pack) {
  const parCat = {};
  documents.forEach((x) => (parCat[x.categorie] = parCat[x.categorie] || []).push(x));
  const nonInclus = pack?._meta?.documents_non_inclus || [];
  return `
    <h3>Messages des enseignants (${messages.length})</h3>
    ${messages.length ? messages.map((m) => `<details class="carte"><summary>${esc(m.sujet)}
        <span class="doux">— ${esc(m.auteur || "")} · ${esc(m.source)}${m.date ? " · " + dateCourte(m.date) : ""}</span></summary>
        ${m.analyse?.resume ? `<p><span class="badge">résumé IA locale</span> ${esc(m.analyse.resume)}</p>` : ""}
        <div style="white-space:pre-wrap">${esc(m.texte)}</div></details>`).join("") : `<p class="doux">Aucun message lié trouvé.</p>`}
    <h3>Fichiers du cours (${documents.length})</h3>
    ${documents.length ? Object.entries(parCat).map(([cat, liste]) => `<details class="carte" ${cat === "annale" ? "open" : ""}>
        <summary>${esc(NOMS_CAT[cat] || cat)} (${liste.length})</summary><ul class="liste-docs">
        ${liste.map((x) => `<li>${x.local ? `<a href="/fichiers/${x.local.split("/").map(encodeURIComponent).join("/")}" target="_blank">${esc(x.nom)}</a>` : esc(x.nom)}
          <span class="doux">${esc(x.section)}</span></li>`).join("")}</ul></details>`).join("")
      : `<p class="doux">Aucun fichier (cours UPdago non associé, ou pas encore synchronisé).</p>`}
    ${nonInclus.length ? `<div class="alerte-boite">Non transmis à Claude : ${nonInclus.map((x) => `${esc(x.nom)} (${esc(x.raison)})`).join(", ")}.
      Augmente <code>budget_caracteres</code> dans config.toml si besoin.</div>` : ""}
    ${pack?._meta ? `<p class="doux">Pack généré le ${pack._meta.genere_le ? dateCourte(pack._meta.genere_le) + " à " + hm(pack._meta.genere_le) : "?"}
      · mode ${esc(pack._meta.mode || "")} ${pack._meta.modele ? "· " + esc(pack._meta.modele) : ""}
      ${pack._meta.jetons_entree ? `· ${pack._meta.jetons_entree.toLocaleString("fr-FR")} jetons lus, ${pack._meta.jetons_sortie.toLocaleString("fr-FR")} écrits` : ""}</p>` : ""}`;
}

// ── QCM interactif ───────────────────────────────────────────────────────
function qcm(questions, el) {
  let ordre = questions.map((_, i) => i);
  let reponses = {};
  const dessiner = () => {
    const faites = Object.keys(reponses).length;
    const bonnes = Object.entries(reponses).filter(([i, r]) => questions[i].bonne_reponse === r).length;
    el.innerHTML = `<div class="carte" style="display:flex;gap:.6rem;align-items:center;flex-wrap:wrap;margin-bottom:.8rem">
        <span class="score">${bonnes} / ${faites}</span><span class="doux">sur ${ordre.length} questions</span>
        <span style="flex:1"></span>
        <button class="btn petit" id="q-melanger">Mélanger et recommencer</button>
        <button class="btn petit" id="q-erreurs" ${faites - bonnes ? "" : "disabled"}>Refaire mes erreurs</button></div>
      ${ordre.map((i, n) => {
        const q = questions[i];
        const r = reponses[i];
        return `<div class="carte qcm-q"><div class="md"><b>${n + 1}.</b> ${md(q.question)}</div>
          ${q.choix.map((c, k) => `<button class="choix ${r === undefined ? "" : k === q.bonne_reponse ? "bon" : k === r ? "faux" : ""}"
             data-q="${i}" data-k="${k}" ${r === undefined ? "" : "disabled"}>${md(c)}</button>`).join("")}
          ${r === undefined ? "" : `<div class="explication md">${r === q.bonne_reponse ? "✅" : "❌"} ${md(q.explication)}
             <span class="doux">— ${esc(q.chapitre)}</span></div>`}</div>`;
      }).join("")}`;
    el.querySelectorAll(".choix").forEach((b) => (b.onclick = () => { reponses[+b.dataset.q] = +b.dataset.k; dessiner(); }));
    $("#q-melanger").onclick = () => { ordre = ordre.sort(() => Math.random() - 0.5); reponses = {}; dessiner(); };
    $("#q-erreurs").onclick = () => {
      ordre = ordre.filter((i) => reponses[i] !== undefined && reponses[i] !== questions[i].bonne_reponse);
      reponses = {}; dessiner();
    };
  };
  dessiner();
}

// ── demander à l'IA : une discussion sur l'exercice ou la leçon affichée ──────────────
const SUGGESTIONS_IA = ["Je bloque, donne-moi un indice", "Explique-moi la méthode", "Donne-moi un exemple concret"];
const texteDe = (html) => { const t = document.createElement("div"); t.innerHTML = html; return t.innerText.trim(); };

// contexte : objet ou fonction qui le renvoie (lu à chaque question : la réponse de l'étudiant a pu changer)
function boiteIA(el, contexte, suggestions = SUGGESTIONS_IA) {
  if (!el) return;
  const fil = [];
  let attente = false;
  const envoyer = async (question) => {
    question = question.trim();
    if (!question || attente) return;
    fil.push({ role: "user", content: question });
    attente = true; dessiner();
    try {
      const r = await post("/api/aide", { contexte: typeof contexte === "function" ? contexte() : contexte,
        question, historique: fil.slice(0, -1) });
      fil.push({ role: "assistant", content: r.reponse });
    } catch (e) { fil.push({ role: "assistant", content: `⚠️ ${e.message}` }); }
    attente = false; dessiner();
    const champ = el.querySelector("textarea");
    if (champ) champ.focus();
  };
  const dessiner = () => {
    el.innerHTML = `<div class="boite-ia">
      <div class="ia-titre">💬 Demande à l'IA</div>
      ${fil.length || attente ? `<div class="ia-fil">${fil.map((m) => `<div class="ia-msg ${m.role === "user" ? "moi" : "ia md"}">${m.role === "user" ? esc(m.content) : md(m.content)}</div>`).join("")}
        ${attente ? `<div class="ia-msg ia doux">L'IA réfléchit…</div>` : ""}</div>` : ""}
      ${fil.length ? "" : `<div class="ia-suggestions">${suggestions.map((s) => `<button type="button" class="btn petit" data-s="${esc(s)}">${esc(s)}</button>`).join("")}</div>`}
      <form class="ia-saisie"><textarea rows="2" placeholder="Pose ta question sur ${esc(suggestions === SUGGESTIONS_LECON ? "cette leçon" : "cet exercice")}…" ${attente ? "disabled" : ""}></textarea>
        <button class="btn principal" ${attente ? "disabled" : ""}>Envoyer</button></form></div>`;
    el.querySelectorAll("[data-s]").forEach((b) => (b.onclick = () => envoyer(b.dataset.s)));
    const f = el.querySelector("form"), champ = el.querySelector("textarea");
    f.onsubmit = (ev) => { ev.preventDefault(); envoyer(champ.value); };
    champ.onkeydown = (ev) => { if (ev.key === "Enter" && !ev.shiftKey) { ev.preventDefault(); envoyer(champ.value); } };
    const zone = el.querySelector(".ia-fil");
    if (zone) zone.scrollTop = zone.scrollHeight;
  };
  el.innerHTML = `<button type="button" class="btn petit">💬 Demander à l'IA</button>`;
  el.querySelector("button").onclick = () => { dessiner(); el.querySelector("textarea").focus(); };
}

// ── leçons vivantes : la fiche du pack réécrite par Claude, chapitre par chapitre ──────
const SUGGESTIONS_LECON = ["Explique-moi autrement", "Donne-moi un autre exemple", "Pose-moi une question pour vérifier"];
const motsDe = (t) => new Set(String(t).toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").split(/[^a-z0-9]+/).filter((m) => m.length > 3));

// les QCM du pack rangés par leçon (chaque question va à la leçon dont le titre lui ressemble le plus)
function qcmParLecon(lecons, qcm) {
  const mots = lecons.map((l) => motsDe(l.titre));
  const res = lecons.map(() => []);
  qcm.forEach((q) => {
    const m = motsDe(q.chapitre);
    let meilleur = -1, score = 0;
    mots.forEach((ml, i) => { const s = [...m].filter((x) => ml.has(x)).length / Math.max(1, Math.min(m.size, ml.size)); if (s > score) { score = s; meilleur = i; } });
    if (meilleur >= 0 && score >= 0.34) res[meilleur].push(q);
  });
  return res;
}

function vueLecons(el, e, pack, enCours, lues) {
  const L = pack.lecons || [];
  if (!L.length) {
    el.innerHTML = `<div class="carte lecons-vide"><div class="gros-emoji">🎓</div>
      <h3>Des leçons vivantes plutôt qu'une fiche</h3>
      <p>Claude réécrit ta fiche chapitre par chapitre : une situation concrète pour commencer, une image pour comprendre,
        un exemple résolu pas à pas, le piège à éviter, la phrase à retenir et un petit défi. Avec l'IA pour répondre à tes questions.</p>
      ${enCours ? `<p><b>⏳ Claude prépare tes leçons…</b> <span class="doux">(quelques minutes ; la page se met à jour toute seule)</span></p>`
        : `<button class="btn principal" id="l-creer">✨ Créer les leçons</button>`}</div>`;
    const b = $("#l-creer");
    if (b) b.onclick = async () => { await post(`/api/examen/${encodeURIComponent(e.id)}/lecons`); vueLecons(el, e, pack, true, lues); attendreLecons(el, e, lues); };
    if (enCours) attendreLecons(el, e, lues);
    return;
  }
  const parLecon = qcmParLecon(L, pack.qcm || []);
  const lu = new Set(lues);
  const total = L.reduce((s, l) => s + (l.minutes || 10), 0);

  const sommaire = () => {
    el.innerHTML = `<div class="lecons-entete"><b>${lu.size}/${L.length} leçons comprises</b>
        <div class="barre-progression"><div style="width:${(100 * lu.size) / L.length}%"></div></div>
        <span class="doux">~${Math.round(total / 6) / 10} h en tout</span></div>
      <div class="grille-lecons">${L.map((l, i) => `<button class="carte carte-lecon ${lu.has(i) ? "lue" : ""}" data-i="${i}">
          <span class="num-lecon">${lu.has(i) ? "✓" : i + 1}</span>
          <b>${esc(l.titre)}</b><span class="doux">${esc(l.accroche)}</span>
          <span class="doux petit">⏱ ${l.minutes} min${parLecon[i].length ? ` · ${parLecon[i].length} QCM` : ""}</span></button>`).join("")}</div>`;
    el.querySelectorAll("[data-i]").forEach((b) => (b.onclick = () => lecon(+b.dataset.i)));
  };

  const lecon = (i) => {
    const l = L[i];
    el.innerHTML = `<div class="lecon">
      <div class="lecons-entete"><button class="btn petit" id="l-sommaire">← Toutes les leçons</button>
        <span>Leçon ${i + 1}/${L.length} · ⏱ ${l.minutes} min</span>
        <div class="barre-progression"><div style="width:${(100 * (i + 1)) / L.length}%"></div></div></div>
      <h2 class="titre-lecon">${esc(l.titre)}</h2>
      <p class="accroche">${esc(l.accroche)}</p>
      <div class="encadre analogie"><b>💡 L'image à garder en tête</b><div class="md">${md(l.analogie)}</div></div>
      <div class="carte md texte-lecon">${md(l.explication_markdown)}</div>
      <div class="encadre exemple"><b>🧪 Exemple pas à pas</b><div class="md">${md(l.exemple_markdown)}</div></div>
      <div class="encadre piege"><b>⚠️ Le piège</b><div class="md">${md(l.piege)}</div></div>
      <div class="encadre retenir"><b>📌 À retenir</b><p>${esc(l.a_retenir)}</p></div>
      <div class="encadre defi"><b>🎯 Défi</b><div class="md">${md(l.defi_question)}</div>
        <details><summary>Voir la réponse</summary><div class="md">${md(l.defi_reponse_markdown)}</div></details></div>
      ${parLecon[i].length ? `<h3>✅ Vérifie avec le QCM</h3><div id="l-qcm"></div>` : ""}
      <div id="l-ia" class="zone-ia"></div>
      <div class="nav-lecon">
        ${i > 0 ? `<button class="btn" id="l-prec">← Précédente</button>` : "<span></span>"}
        <button class="btn principal" id="l-compris">${i + 1 < L.length ? "✓ J'ai compris, leçon suivante →" : "✓ J'ai compris, terminé !"}</button></div></div>`;
    if (parLecon[i].length) qcm(parLecon[i], $("#l-qcm"));
    boiteIA($("#l-ia"), { type: "lecon", matiere: e.matiere, titre: l.titre,
      enonce: [l.accroche, l.analogie, l.explication_markdown, l.exemple_markdown, `Piège : ${l.piege}`, `À retenir : ${l.a_retenir}`].join("\n\n") }, SUGGESTIONS_LECON);
    if (window.renderMathInElement) renderMathInElement(el, { delimiters: [{ left: "$$", right: "$$", display: true }, { left: "$", right: "$", display: false }] });
    $("#l-sommaire").onclick = sommaire;
    const p = $("#l-prec");
    if (p) p.onclick = () => lecon(i - 1);
    $("#l-compris").onclick = async () => {
      lu.add(i);
      post(`/api/examen/${encodeURIComponent(e.id)}/lecon-lue`, { index: i, lue: true }).catch(() => {});
      if (i + 1 < L.length) lecon(i + 1); else { sommaire(); toast("Bravo, toutes les leçons sont faites ! Passe au quiz chrono pour ancrer."); }
    };
    el.scrollIntoView({ behavior: "smooth", block: "start" });
  };
  sommaire();
}

// pendant que Claude écrit les leçons : on revérifie toutes les 20 s, tant que l'onglet est affiché
function attendreLecons(el, e, lues) {
  clearTimeout(el._attente);
  el._attente = setTimeout(async () => {
    if (!document.body.contains(el)) return;
    try {
      const d = await api(`/api/examen/${encodeURIComponent(e.id)}`);
      if (d.pack?.lecons?.length || !d.lecons_en_cours) vueLecons(el, e, d.pack, d.lecons_en_cours, d.lecons_lues);
      else attendreLecons(el, e, lues);
    } catch { attendreLecons(el, e, lues); }
  }, 20000);
}

// ── notes ────────────────────────────────────────────────────────────────
let GRAPHIQUES = [];
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const f2 = (v) => (v == null ? "—" : v.toFixed(2).replace(".", ","));
const sur20 = (n) => (n.sur ? (n.note / n.sur) * 20 : n.note);
const libelleNote = (n) => n.module + (n.evaluation ? ` — ${n.evaluation}` : "");

async function vueNotes() {
  let d;
  try { d = await api("/api/notes"); } catch (e) { vue.innerHTML = `<p class="vide">${esc(e.message)}</p>`; return; }
  GRAPHIQUES.forEach((g) => g.destroy());
  GRAPHIQUES = [];
  const s = d.stats, N = s.annee_courante, P = s.annee_precedente;
  const mN = s.moyennes_generales[N], mP = s.moyennes_generales[P];
  const ecart = s.ecart_commun;
  const uesN = s.ue.filter((u) => u.par_annee[N] && u.par_annee[N].promo_moy != null);
  const rang = (c) => (c && c.rang ? `${c.rang}/${c.effectif}` : "—");
  const a = d.analyse;
  const occupe = !!d.tache.nom;
  const nbN = d.liste.filter((n) => n.annee === N).length, nbP = d.liste.filter((n) => n.annee === P).length;

  vue.innerHTML = `
    <h1>Mes notes</h1>
    ${d.fournisseur === "webmail" && d.configure && d.auto ? "" : d.fournisseur === "webmail" ? `<div class="carte connexion-mail">
      <h2>${d.configure ? "Reconnexion automatique de ta messagerie" : "Connecte ta messagerie de l'université"}</h2>
      ${d.connexion_en_cours
        ? `<p><b>Une fenêtre Edge s'est ouverte sur le PC, sur la page de connexion de l'université.</b> Connecte-toi comme sur l'ENT ;
           elle se ferme toute seule quand c'est bon, puis la lecture de tes notes démarre.</p>
           <button class="btn petit" onclick="vueNotes()">Actualiser</button>`
        : `<p class="doux">${d.configure ? "La session de l'ENT expire au bout de quelques heures : sans ça, il faut se reconnecter à la main. " : ""}
           RevisUP se reconnecte tout seul quand la session expire, puis relit tes mails à chaque synchro.
           Ton mot de passe est rangé dans le coffre de Windows du PC (jamais dans un fichier) et n'est tapé que sur la page de l'ENT.
           Un seul essai à chaque fois : ton compte ne peut pas être bloqué.</p>
           <form class="ligne" id="form-auto">
             <label>Identifiant de l'ENT <input name="identifiant" value="${esc((d.identifiant || "").split("@")[0])}" autocomplete="username" required style="width:11rem"></label>
             <label>Mot de passe <input name="mdp" type="password" autocomplete="current-password" required style="width:13rem"></label>
             <button class="btn principal" id="auto-ok">Se connecter</button></form>
           <p class="doux" id="auto-etat" role="status"></p>
           ${d.configure ? "" : `<p class="doux">Ou sans garder ton mot de passe : <button class="btn petit" id="mail-web">ouvrir la page de l'ENT sur le PC</button>
             (à refaire à chaque expiration).</p>`}
           ${d.erreur_connexion ? `<p class="erreur">Dernier essai : ${esc(d.erreur_connexion)}</p>` : ""}`}</div>`
      : d.fournisseur === "microsoft" ? `<div class="alerte-boite">Pour lire tes notes dans ta boîte mail, double-clique sur <b>mail-connexion.bat</b>
      (dans le dossier de RevisUP) et connecte-toi sur la page Microsoft qui s'ouvre. RevisUP ne garde qu'un jeton de lecture, jamais ton mot de passe.</div>`
      : `<form class="carte connexion-mail" id="form-mail">
      <h2>Connecte ta messagerie de l'université</h2>
      <p class="doux">Pour retrouver tes notes dans tes mails. Le mot de passe est rangé dans le coffre de Windows, jamais dans un fichier.</p>
      <div class="ligne">
        <label>Identifiant de l'ENT <input name="identifiant" value="${esc(d.identifiant || "")}" autocomplete="username" required style="width:12rem"></label>
        <label>Mot de passe <input name="mdp" type="password" autocomplete="current-password" required style="width:14rem"></label>
        <button class="btn principal" id="mail-ok">Connexion</button>
      </div>
      <p class="doux" id="mail-etat" role="status"></p></form>`}
    ${d.auto ? `<p class="doux">🔁 Reconnexion automatique activée (${esc(d.auto)}) : tes mails sont relus à chaque synchro.
      <button class="btn petit" id="auto-off">Désactiver et effacer le mot de passe</button></p>` : ""}
    <p class="doux">${d.mails_lus} mail(s) lu(s) · dernière lecture ${d.maj ? dateCourte(d.maj) + " à " + hm(d.maj) : "jamais"}
      &nbsp;<button class="btn petit" id="n-sync" ${occupe || !d.configure ? "disabled" : ""}>📬 Lire mes mails de notes</button>
      <button class="btn petit" id="n-analyse" ${occupe || !d.liste.length ? "disabled" : ""}>✨ Analyser avec Claude</button></p>

    <div class="tuiles">
      <div class="carte tuile"><div class="etiquette"><span class="pastille" style="background:var(--serie-1)"></span>Moyenne ${N}</div>
        <div class="valeur">${f2(mN)}<small> /20</small></div><div class="doux">${nbN} note(s)</div></div>
      <div class="carte tuile"><div class="etiquette"><span class="pastille" style="background:var(--serie-2)"></span>Moyenne ${P}</div>
        <div class="valeur">${f2(mP)}<small> /20</small></div><div class="doux">${nbP} note(s), année précédente</div></div>
      <div class="carte tuile"><div class="etiquette">Par rapport à l'an dernier</div>
        <div class="valeur">${ecart == null ? "—" : (ecart >= 0 ? "+" : "−") + f2(Math.abs(ecart))}</div>
        <div class="delta ${ecart == null ? "" : ecart >= 0 ? "hausse" : "baisse"}">${ecart == null ? "pas encore comparable" : (ecart >= 0 ? "▲ en progrès" : "▼ en recul") + ` · ${s.nb_communs} module(s) communs`}</div></div>
      <div class="carte tuile"><div class="etiquette">Modules sous 10 cette année</div>
        <div class="valeur">${s.sous_10.length}</div><div class="doux">${s.sous_10.length ? esc(s.sous_10.slice(0, 2).join(", ")) : "aucun"}</div></div>
    </div>
    <p class="doux">Moyennes simples des modules (sans les coefficients d'UE). « Par rapport à l'an dernier » : écart moyen sur les modules notés les deux années.</p>

    ${s.ue.length ? `
    <h2>Où je me situe : mes UE et mon rang</h2>
    ${uesN.length ? `<div class="carte"><div class="graphique" style="--h:${uesN.length * 64 + 90}px"><canvas id="g-ue"
      aria-label="Moyenne de chaque UE en ${N} et ${P}, face à la promo"></canvas></div>
      <p class="doux" style="margin:.4rem 0 0">Bande grise : de la plus basse à la plus haute moyenne de la promo ${N}. Trait gris : moyenne de la promo.</p></div>` : ""}
    <div class="carte defile"><table class="tableau">
      <tr><th>UE (compétence)</th><th class="num">${P}</th><th class="num">Rang</th><th class="num">${N}</th><th class="num">Rang</th><th class="num">Promo ${N}</th></tr>
      ${s.ue.map((u) => {
        const cP = u.par_annee[P] || {}, cN = u.par_annee[N] || {};
        const cap = cN.capitalisee || cP.capitalisee;
        return `<tr><td>${esc(u.code)} ${esc(u.nom)}${cap ? `<br><span class="doux">capitalisée le ${esc(cap.le)} (${f2(cap.moyenne)})</span>` : ""}</td>
          <td class="num ${cP.moyenne != null && cP.moyenne < 10 ? "sous10" : ""}">${f2(cP.moyenne)}</td><td class="num">${rang(cP)}</td>
          <td class="num ${cN.moyenne != null && cN.moyenne < 10 ? "sous10" : ""}">${f2(cN.moyenne)}</td><td class="num">${rang(cN)}</td>
          <td class="num">${f2(cN.promo_moy)}</td></tr>`;
      }).join("")}</table></div>
    <p class="doux">D'après tes relevés de notes ScoDoc (provisoires). Une UE se valide à 10/20.</p>` : ""}

    ${d.liste.length ? `
    <h2>Par module : ${N} face à ${P}</h2>
    <div class="carte"><div class="graphique" style="--h:${Math.max(220, modulesComparables(s).length * 46 + 70)}px"><canvas id="g-modules"
      aria-label="Moyenne par module, ${N} et ${P}"></canvas></div></div>
    <h2>Ma moyenne au fil de l'année</h2>
    <div class="carte"><div class="graphique"><canvas id="g-evolution" aria-label="Moyenne cumulée au fil de l'année"></canvas></div>
      <p class="doux" style="margin:.4rem 0 0">Ligne : moyenne cumulée. Points : chaque note. L'an dernier est calé sur le même calendrier (septembre → juin).</p></div>` : ""}

    <h2>Analyse de Claude</h2>
    ${a ? analyseNotes(a) : `<p class="doux">${d.liste.length ? "Clique sur « Analyser avec Claude » pour savoir où tu en es et quoi travailler en priorité." : "L'analyse sera possible dès que des notes auront été trouvées."}</p>`}

    ${s.modules.length ? `<h2>Détail par module</h2><div class="carte defile"><table class="tableau">
      <tr><th>Module</th><th class="num">${P}</th><th class="num">${N}</th><th class="num">Évolution</th><th class="num">Promo ${N}</th></tr>
      ${s.modules.map((m) => {
        const vN = m.moyennes[N], vP = m.moyennes[P];
        return `<tr><td>${esc(m.nom)}</td><td class="num">${f2(vP)}</td><td class="num ${vN != null && vN < 10 ? "sous10" : ""}">${f2(vN)}</td>
          <td class="num ${m.evolution == null ? "" : m.evolution >= 0 ? "delta hausse" : "delta baisse"}">${m.evolution == null ? "—" : (m.evolution >= 0 ? "▲ +" : "▼ −") + f2(Math.abs(m.evolution))}</td>
          <td class="num">${f2(m.classe[N])}</td></tr>`;
      }).join("")}</table></div>` : ""}

    ${d.liste.length ? `<h2>Toutes les notes (${d.liste.length})</h2><div class="carte defile"><table class="tableau">
      <tr><th>Date</th><th>Module</th><th class="num">Note</th><th class="num">Coef</th><th class="num">Promo</th><th>Année</th><th></th></tr>
      ${d.liste.slice().reverse().map((n) => `<tr><td>${esc(n.date.split("-").reverse().join("/"))}</td>
        <td>${esc(libelleNote(n))}${n.source === "mail" ? ` <span class="doux" title="${esc(n.sujet_mail || "")}">✉</span>` : ""}</td>
        <td class="num ${sur20(n) < 10 ? "sous10" : ""}">${f2(n.note)}/${n.sur}</td><td class="num">${n.coefficient || "—"}</td>
        <td class="num">${n.moyenne_classe || "—"}</td><td>${esc(n.annee)}</td>
        <td><button class="btn petit" title="Supprimer (erreur de lecture)" onclick="supprimerNote('${esc(n.id)}')">✕</button></td></tr>`).join("")}
      </table></div>` : ""}

    <h2>Ajouter une note à la main</h2>
    <form class="ligne carte" id="form-note">
      <label>Module <input name="module" required placeholder="R108 Bases des systèmes d'exploitation" style="min-width:16rem"></label>
      <label>Évaluation <input name="evaluation" placeholder="ctrl TP" style="width:7rem"></label>
      <label>Note <input name="note" required inputmode="decimal" style="width:4.5rem"></label>
      <label>Sur <input name="sur" value="20" inputmode="decimal" style="width:3.5rem"></label>
      <label>Coef <input name="coefficient" inputmode="decimal" style="width:3.5rem"></label>
      <label>Date <input name="date" type="date" required></label>
      <button class="btn principal">Ajouter</button></form>`;

  const bw = $("#mail-web");
  if (bw) bw.onclick = async () => {
    bw.disabled = true;
    try {
      await post("/api/mail/connexion-web");
      toast("Une fenêtre Edge s'ouvre : connecte-toi avec l'ENT.");
      await charger();
      vueNotes();
    } catch (err) { toast(err.message); bw.disabled = false; }
  };
  const fa = $("#form-auto");
  if (fa) fa.onsubmit = async (ev) => {
    ev.preventDefault();
    const etat = $("#auto-etat"), bouton = $("#auto-ok");
    bouton.disabled = true;
    etat.className = "doux";
    etat.textContent = "Connexion à l'ENT sur le PC… (jusqu'à une minute)";
    try {
      const r = await post("/api/mail/auto", Object.fromEntries(new FormData(fa)));
      toast(`Messagerie connectée (${r.adresse}). Lecture de tes mails de notes lancée.`);
      await charger();
      vueNotes();
    } catch (err) {
      etat.className = "erreur";
      etat.textContent = err.message + " — vérifie l'identifiant et le mot de passe de l'ENT.";
      bouton.disabled = false;
    }
  };
  const ao = $("#auto-off");
  if (ao) ao.onclick = async () => {
    await api("/api/mail/auto", { method: "DELETE" });
    toast("Reconnexion automatique désactivée, mot de passe effacé.");
    vueNotes();
  };
  const fm = $("#form-mail");
  if (fm) fm.onsubmit = async (ev) => {
    ev.preventDefault();
    const etat = $("#mail-etat"), bouton = $("#mail-ok");
    bouton.disabled = true;
    etat.className = "doux";
    etat.textContent = "Connexion à la messagerie…";
    try {
      const r = await post("/api/mail/connexion", Object.fromEntries(new FormData(fm)));
      toast(`Messagerie connectée (${r.identifiant}). Lecture de tes mails de notes lancée.`);
      await charger();
      vueNotes();
    } catch (err) {
      etat.className = "erreur";
      etat.textContent = err.message + " — vérifie le mot de passe (2 essais max d'affilée pour ne pas bloquer ton compte).";
      bouton.disabled = false;
    }
  };
  const bs = $("#n-sync");
  if (bs) bs.onclick = async () => {
    const r = await post("/api/notes/synchro");
    toast(r.ok ? "Lecture de ta boîte lancée : l'IA locale cherche tes notes (quelques minutes)." : r.message);
    await charger();
  };
  $("#n-analyse").onclick = async () => {
    const r = await post("/api/notes/analyser");
    toast(r.ok ? "Claude analyse tes notes (une à deux minutes)…" : r.message);
    await charger();
  };
  const fn = $("#form-note");
  fn.onsubmit = async (ev) => {
    ev.preventDefault();
    try { await post("/api/notes/ajouter", Object.fromEntries(new FormData(fn))); toast("Note ajoutée."); vueNotes(); }
    catch (err) { toast(err.message); }
  };
  if (window.Chart && d.liste.length) dessinerNotes(s, d.liste);
}

window.supprimerNote = async (id) => {
  if (!confirm("Supprimer cette note ?")) return;
  await post(`/api/notes/${id}/supprimer`);
  vueNotes();
};

function analyseNotes(a) {
  return `<div class="carte md">${md(a.situation)}</div>
    <h3>Par rapport à l'an dernier</h3><div class="carte md">${md(a.comparaison_annee_precedente)}</div>
    <h3>Tes points forts</h3><div class="carte md"><ul>${a.points_forts.map((p) => `<li>${md(p)}</li>`).join("")}</ul></div>
    <h3>À améliorer en priorité</h3>
    ${a.points_a_ameliorer.map((p) => `<div class="carte" style="margin-bottom:.6rem"><b>${esc(p.module)}</b>
      <div class="md">${md(p.constat)}</div><ul>${p.actions.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div>`).join("")}
    ${a.objectifs.length ? `<h3>Objectifs pour les prochains contrôles</h3><div class="carte defile"><table class="tableau">
      <tr><th>Module</th><th class="num">Cible</th><th>Comment</th></tr>
      ${a.objectifs.map((o) => `<tr><td>${esc(o.module)}</td><td class="num">${f2(o.note_cible)}</td><td>${esc(o.conseil)}</td></tr>`).join("")}
      </table></div>` : ""}
    <h3>Conseils</h3><div class="carte md">${md(a.conseils_generaux)}</div>
    <p class="doux">Analyse du ${dateCourte(a._meta.genere_le)} à ${hm(a._meta.genere_le)}, sur ${a._meta.nb_notes} notes.</p>`;
}

// semestre d'un module d'après son code (r101 → 1, sae24 → 2) ; null si inconnu
const semestreModule = (cle) => { const m = /^(?:r|sae|s)(\d)/.exec(cle); return m ? m[1] : null; };

function modulesComparables(s) {
  const N = s.annee_courante;
  const semestres = new Set(s.modules.filter((m) => m.moyennes[N] != null).map((m) => semestreModule(m.cle)));
  if (!semestres.size) return s.modules;
  return s.modules.filter((m) => m.moyennes[N] != null || semestres.has(semestreModule(m.cle)));
}

function dessinerNotes(s, liste) {
  const N = s.annee_courante, P = s.annee_precedente;
  const c1 = css("--serie-1"), c2 = css("--serie-2"), surface = css("--carte");
  const encre = css("--encre-2"), muette = css("--encre-muette"), grille = css("--grille"), axe = css("--axe");
  Chart.defaults.font.family = 'system-ui, -apple-system, "Segoe UI", sans-serif';
  Chart.defaults.color = encre;
  const infobulle = { backgroundColor: css("--texte"), titleColor: css("--fond"), bodyColor: css("--fond"), padding: 8, cornerRadius: 6 };

  // trait pointillé « 10/20 » : le seuil de validation d'une compétence en BUT
  const seuil = {
    id: "seuil",
    afterDatasetsDraw(chart) {
      const echelle = chart.options.indexAxis === "y" ? chart.scales.x : chart.scales.y;
      const p = echelle.getPixelForValue(10), { ctx, chartArea: z } = chart;
      ctx.save();
      ctx.strokeStyle = muette; ctx.setLineDash([4, 4]); ctx.lineWidth = 1; ctx.beginPath();
      if (chart.options.indexAxis === "y") { ctx.moveTo(p, z.top); ctx.lineTo(p, z.bottom); }
      else { ctx.moveTo(z.left, p); ctx.lineTo(z.right, p); }
      ctx.stroke(); ctx.setLineDash([]); ctx.fillStyle = muette; ctx.font = "11px system-ui";
      if (chart.options.indexAxis === "y") ctx.fillText("10 : validation", p + 4, z.top + 10);
      else ctx.fillText("10 : validation", z.left + 4, p - 4);
      ctx.restore();
    },
  };

  // 0. UE : bande min → max de la promo, trait = moyenne de la promo, repères = moi (cette année / l'an dernier)
  const ues = s.ue.filter((u) => u.par_annee[N] && u.par_annee[N].promo_moy != null);
  if (ues.length && $("#g-ue")) {
    const repere = (v, l) => (v == null ? null : [Math.max(0, v - l), Math.min(20, v + l)]);
    const cases = ues.map((u) => [u.par_annee[N], u.par_annee[P] || {}]);
    GRAPHIQUES.push(new Chart($("#g-ue"), {
      type: "bar",
      data: {
        labels: ues.map((u) => `${u.code} ${u.nom.length > 28 ? u.nom.slice(0, 27) + "…" : u.nom}`),
        datasets: [
          { label: `Promo ${N} (min → max)`, data: cases.map(([c]) => [c.promo_min, c.promo_max]), backgroundColor: grille,
            barPercentage: 0.45, borderRadius: 4, borderSkipped: false, order: 4 },
          { label: "Moyenne de la promo", data: cases.map(([c]) => repere(c.promo_moy, 0.06)), backgroundColor: muette,
            barPercentage: 0.75, order: 3 },
          { label: `Toi en ${P}`, data: cases.map(([, p]) => repere(p.moyenne, 0.16)), backgroundColor: c2,
            barPercentage: 0.75, borderRadius: 2, order: 2 },
          { label: `Toi en ${N}`, data: cases.map(([c]) => repere(c.moyenne, 0.16)), backgroundColor: c1,
            barPercentage: 0.75, borderRadius: 2, order: 1 },
        ].map((ds) => ({ ...ds, grouped: false, borderSkipped: false, borderColor: surface, borderWidth: 1 })),
      },
      options: {
        indexAxis: "y", responsive: true, maintainAspectRatio: false,
        scales: {
          x: { min: 0, max: 20, ticks: { stepSize: 5, color: muette }, grid: { color: grille }, border: { color: axe } },
          y: { ticks: { color: encre }, grid: { display: false }, border: { color: axe } },
        },
        plugins: {
          legend: { position: "top", align: "start", labels: { boxWidth: 12, boxHeight: 12, useBorderRadius: true, borderRadius: 3 } },
          tooltip: { ...infobulle, callbacks: {
            title: (it) => `${ues[it[0].dataIndex].code} ${ues[it[0].dataIndex].nom}`,
            label: (c) => {
              const [cn, cp] = cases[c.dataIndex];
              if (c.datasetIndex === 0) return `Promo : de ${f2(cn.promo_min)} à ${f2(cn.promo_max)}`;
              if (c.datasetIndex === 1) return `Moyenne de la promo : ${f2(cn.promo_moy)}`;
              const x = c.datasetIndex === 2 ? cp : cn;
              return `${c.dataset.label} : ${f2(x.moyenne)}/20${x.rang ? ` · rang ${x.rang}/${x.effectif}` : ""}`;
            } } },
        },
      },
      plugins: [seuil],
    }));
  }

  // 1. barres groupées par module (seulement les semestres de cette année : on compare S1 à S1)
  const mods = modulesComparables(s);
  const court = (nom) => (nom.length > 34 ? nom.slice(0, 33) + "…" : nom);
  GRAPHIQUES.push(new Chart($("#g-modules"), {
    type: "bar",
    data: {
      labels: mods.map((m) => court(m.nom)),
      datasets: [
        { label: N, data: mods.map((m) => m.moyennes[N] ?? null), backgroundColor: c1 },
        { label: `${P} (année précédente)`, data: mods.map((m) => m.moyennes[P] ?? null), backgroundColor: c2 },
      ].map((ds) => ({ ...ds, borderRadius: 4, borderSkipped: "start", borderColor: surface, borderWidth: 2, barPercentage: 0.8, categoryPercentage: 0.7 })),
    },
    options: {
      indexAxis: "y", responsive: true, maintainAspectRatio: false,
      scales: {
        x: { min: 0, max: 20, ticks: { stepSize: 5, color: muette }, grid: { color: grille }, border: { color: axe } },
        y: { ticks: { color: encre }, grid: { display: false }, border: { color: axe } },
      },
      plugins: {
        legend: { position: "top", align: "start", labels: { boxWidth: 12, boxHeight: 12, useBorderRadius: true, borderRadius: 3 } },
        tooltip: { ...infobulle, callbacks: { title: (it) => mods[it[0].dataIndex].nom, label: (c) => `${c.dataset.label} : ${f2(c.raw)}/20` } },
      },
    },
    plugins: [seuil],
  }));

  // 2. moyenne cumulée au fil de l'année, les deux années sur le même calendrier
  const jour = (date, annee) => (new Date(date) - new Date(+annee.slice(0, 4), 7, 15)) / 864e5;
  const series = [];
  [[N, c1], [P, c2]].forEach(([annee, couleur]) => {
    const notes = liste.filter((n) => n.annee === annee).sort((x, y) => x.date.localeCompare(y.date));
    if (!notes.length) return;
    let somme = 0, poids = 0;
    const cumul = notes.map((n) => {
      const p = n.coefficient || 1;
      somme += sur20(n) * p; poids += p;
      return { x: jour(n.date, annee), y: +(somme / poids).toFixed(2) };
    });
    series.push({ type: "line", label: `${annee} · moyenne cumulée`, data: cumul, borderColor: couleur, backgroundColor: couleur,
                  borderWidth: 2, pointRadius: 0, pointHoverRadius: 5, tension: 0.25 });
    series.push({ type: "scatter", label: `${annee} · notes`, data: notes.map((n) => ({ x: jour(n.date, annee), y: +sur20(n).toFixed(2), n: libelleNote(n) })),
                  backgroundColor: couleur + "99", borderColor: surface, borderWidth: 2, pointRadius: 4, pointHoverRadius: 6 });
  });
  const MOIS_COURTS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];
  GRAPHIQUES.push(new Chart($("#g-evolution"), {
    data: { datasets: series },
    options: {
      responsive: true, maintainAspectRatio: false,
      interaction: { mode: "nearest", intersect: false },
      scales: {
        x: { type: "linear", min: 15, max: 320, grid: { color: grille }, border: { color: axe },
             ticks: { stepSize: 30.4, color: muette, callback: (v) => MOIS_COURTS[new Date(2026, 7, 15 + v).getMonth()] } },
        y: { min: 0, max: 20, ticks: { stepSize: 5, color: muette }, grid: { color: grille }, border: { color: axe } },
      },
      plugins: {
        legend: { position: "top", align: "start", labels: { boxWidth: 12, boxHeight: 12, useBorderRadius: true, borderRadius: 3 } },
        tooltip: { ...infobulle, callbacks: {
          title: () => "",
          label: (c) => (c.raw.n ? `${c.raw.n} : ${f2(c.raw.y)}/20` : `${c.dataset.label} : ${f2(c.raw.y)}/20`),
        } },
      },
    },
    plugins: [seuil],
  }));
}

// ── réglages ─────────────────────────────────────────────────────────────
// ── aujourd'hui : « qu'est-ce que tu fais aujourd'hui ? » + message libre ─────────────
async function vueJournee(choixNotif) {
  if (choixNotif) {  // bouton d'une notification (ordinateur) : on enregistre puis on nettoie l'adresse
    try { await post("/api/journee", { choix: choixNotif }); toast("C'est noté, ton planning est à jour."); } catch (e) { toast(e.message); }
    history.replaceState(null, "", "#/journee");
  }
  let j;
  try { j = await api("/api/journee"); } catch (e) { vue.innerHTML = `<p class="vide">${esc(e.message)}</p>`; return; }
  const BOUTONS = ["salle", "course", "rien", "soiree", "autre"];
  const lignes = [
    ...(j.cours ? [{ debut: j.cours.debut, fin: j.cours.fin, nom: "Cours", type: "cours" }] : []),
    ...j.bloque.map((b) => ({ ...b, type: "occupe" })),
    ...j.sessions.map((s) => ({ debut: s.debut, fin: s.fin, nom: `${s.matiere} — ${s.tache}`, type: "revision", id: s.examen_id })),
  ].sort((a, b) => a.debut.localeCompare(b.debut));
  const icone = { cours: "🎓", occupe: "⛔", revision: "📚" };
  vue.innerHTML = `
    <h1>Aujourd'hui <small class="doux">${esc(j.jour)} ${esc(j.date.split("-").reverse().join("/"))}</small></h1>
    <p class="doux">${j.cours ? `Cours de ${hm(j.cours.debut)} à ${hm(j.cours.fin)}.` : "Pas de cours."}
      D'habitude ce jour-là : ${j.habituel.length ? esc(j.habituel.join(", ")) : "rien de prévu"}.</p>

    <div class="carte">
      <h2>Qu'est-ce que tu fais aujourd'hui ?</h2>
      <div class="choix-journee">
        ${BOUTONS.map((c) => `<button class="btn ${j.choix === c ? "principal" : ""}" data-choix="${c}">${esc(j.libelles[c])}</button>`).join("")}
        ${j.choix ? `<button class="btn" data-choix="habituel">${esc(j.libelles.habituel)}</button>` : ""}
      </div>
      <form class="ligne" id="j-heures" hidden>
        <label>Quoi <input name="nom" placeholder="Ciné, repas de famille…" style="width:12rem"></label>
        <label>De <input name="debut" type="time" required></label>
        <label>À <input name="fin" type="time" required></label>
        <button class="btn principal">OK</button>
      </form>
    </div>

    <div class="carte">
      <h2>Écris ce qui change</h2>
      <p class="doux">Pour aujourd'hui ou les jours suivants. Exemples : « ce soir ciné de 20h à 23h », « jeudi pas de course »,
        « demain je suis malade », « samedi je bosse de 9h à 13h ».</p>
      <textarea id="j-texte" rows="3" maxlength="600" placeholder="Écris comme tu parles…"></textarea>
      <div class="ligne" style="margin-top:.5rem"><button class="btn principal" id="j-envoyer">Adapter mon planning</button>
        <span class="doux" id="j-etat" role="status"></span></div>
      ${j.texte ? `<p class="doux">Pour aujourd'hui, tu as écrit : « ${esc(j.texte)} »</p>` : ""}
    </div>

    <h2>Ma journée</h2>
    ${lignes.length ? lignes.map((l) => `<div class="ligne-agenda ${l.type === "revision" ? "" : "cours"}" ${l.type === "revision" ? `style="--couleur:${couleur(l.nom)}"` : ""}>
        <span class="heure">${hm(l.debut)} – ${hm(l.fin)}</span>
        <span class="quoi">${icone[l.type]} ${l.id ? `<a href="#/examen/${encodeURIComponent(l.id)}">${esc(l.nom)}</a>` : esc(l.nom)}</span></div>`).join("")
      : `<p class="doux">Rien de prévu aujourd'hui.</p>`}
    ${j.sessions.length ? "" : `<p class="doux">Pas de session de révision placée aujourd'hui.</p>`}

    ${j.prochains.length ? `<h2>Déjà prévu les prochains jours</h2>
      ${j.prochains.map((p) => `<div class="carte ligne" style="justify-content:space-between;margin-bottom:.5rem">
        <span><b>${esc(p.jour)} ${esc(p.date.split("-").reverse().slice(0, 2).join("/"))}</b> —
          ${p.activites.length ? esc(p.activites.map((a) => a.nom + (a.debut ? ` ${a.debut.replace(":", "h")}-${a.fin.replace(":", "h")}` : " après les cours")).join(", ")) : "libre pour réviser"}
          ${p.texte ? `<br><span class="doux">« ${esc(p.texte)} »</span>` : ""}</span>
        <button class="btn petit" data-annuler="${esc(p.date)}">Annuler</button></div>`).join("")}` : ""}`;

  const formHeures = $("#j-heures");
  let choixHeures = null;
  const repondre = async (corps) => {
    try { await post("/api/journee", corps); toast("C'est noté, ton planning est à jour."); await charger(); vueJournee(); }
    catch (e) { toast(e.message); }
  };
  vue.querySelectorAll("[data-choix]").forEach((b) => b.onclick = () => {
    const c = b.dataset.choix;
    if (c === "autre" || (c === "salle" && !j.cours)) {  // sans cours, « après les cours » ne veut rien dire : on demande l'heure
      choixHeures = c; formHeures.hidden = false; formHeures.nom.parentElement.hidden = c !== "autre"; formHeures.debut.focus();
      return;
    }
    repondre({ choix: c });
  });
  formHeures.onsubmit = (ev) => { ev.preventDefault(); repondre({ choix: choixHeures, ...Object.fromEntries(new FormData(formHeures)) }); };
  vue.querySelectorAll("[data-annuler]").forEach((b) => b.onclick = () => repondre({ choix: "habituel", date: b.dataset.annuler }));
  $("#j-envoyer").onclick = async () => {
    const texte = $("#j-texte").value.trim(), etat = $("#j-etat"), bouton = $("#j-envoyer");
    if (!texte) return $("#j-texte").focus();
    bouton.disabled = true;
    etat.textContent = "L'IA lit ton message et recalcule ton planning… (jusqu'à une minute)";
    try {
      const r = await post("/api/journee/texte", { texte });
      await charger();
      await vueJournee();
      toast(r.jours.length ? r.resume : "Je n'ai rien trouvé à changer dans ton message.");
      $("#j-etat").textContent = r.resume ? `Compris : ${r.resume}` : "";
    } catch (e) { etat.textContent = e.message; bouton.disabled = false; }
  };
}

// ── notifications sur ce téléphone (app installée sur l'écran d'accueil) ──────────
const IOS = /iPhone|iPad|iPod/.test(navigator.userAgent);
const INSTALLEE = window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
// (un iPad récent se présente comme un Mac, mais tactile)
const MAC = /Macintosh/.test(navigator.userAgent) && navigator.maxTouchPoints < 2;
const nomAppareil = () => (IOS ? "iPhone" : MAC ? "Mac" : /Android/.test(navigator.userAgent) ? "Android" : /Windows/.test(navigator.userAgent) ? "PC Windows" : "navigateur");
const b64EnOctets = (b64) => {
  const brut = atob((b64 + "=".repeat((4 - (b64.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(brut, (c) => c.charCodeAt(0));
};

async function etatNotifications() {
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || !window.isSecureContext) {
    return IOS && !INSTALLEE ? "installer" : "impossible";
  }
  // ready ne répond jamais si le navigateur a refusé le service worker
  const enr = await Promise.race([navigator.serviceWorker.ready, new Promise((r) => setTimeout(r, 5000))]);
  if (!enr) return "impossible";
  return (await enr.pushManager.getSubscription()) ? "actives" : "inactives";
}

async function activerNotifications() {
  const enr = await navigator.serviceWorker.ready;
  if ((await Notification.requestPermission()) !== "granted") throw new Error(IOS
    ? "Notifications refusées : autorise-les dans Réglages > Notifications > RevisUP."
    : "Notifications refusées : autorise-les pour ce site (cadenas à gauche de l'adresse), et sur Mac dans Réglages Système > Notifications.");
  const { cle } = await api("/api/push/cle");
  const abonnement = await enr.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64EnOctets(cle) });
  await post("/api/push/abonner", { abonnement: abonnement.toJSON(), appareil: nomAppareil() });
}

async function blocNotifications() {
  const el = $("#bloc-notifs");
  if (!el) return;
  const etat = await etatNotifications();
  const { appareils } = await api("/api/push/cle").catch(() => ({ appareils: [] }));
  el.innerHTML = {
    installer: `<p>Sur l'iPhone, installe d'abord l'app : dans Safari, touche <b>Partager</b> <span aria-hidden="true">⎋</span> puis
      <b>Sur l'écran d'accueil</b>. Ouvre ensuite RevisUP depuis son icône et reviens ici.</p>`,
    impossible: `<p class="doux">Ce navigateur ne gère pas les notifications de RevisUP (il faut une adresse en https://, ou localhost).</p>`,
    inactives: `<p>Reçois sur cet appareil les rappels d'examen, le programme du jour et la question de midi.</p>
      <button class="btn principal" id="n-activer">🔔 Activer les notifications</button>`,
    actives: `<p>✅ Notifications activées sur cet appareil.</p><button class="btn" id="n-test">Envoyer une notification de test</button>`,
  }[etat] + (appareils.length ? `<p class="doux">Appareils qui reçoivent les notifications : ${esc(appareils.join(", "))}</p>` : "");
  const a = $("#n-activer");
  if (a) a.onclick = async () => {
    a.disabled = true;
    try { await activerNotifications(); toast("Notifications activées !"); blocNotifications(); }
    catch (e) { toast(e.message); a.disabled = false; }
  };
  const t = $("#n-test");
  if (t) t.onclick = async () => { const r = await post("/api/push/test"); toast(r.ok ? "Notification envoyée." : r.message); };
}

const CONNEXIONS = {
  edt: ["Emploi du temps UPplanning", null],
  updago: ["UPdago (cours, messages des profs)", "Se reconnecter"],
  messagerie: ["Messagerie (tes notes)", "Se reconnecter"],
  claude: ["Claude (packs de révision, analyses)", "Reconnecter Claude"],
  ia_locale: ["IA locale (LM Studio)", "Démarrer LM Studio"],
};

function blocConnexions() {
  const S = ETAT.sante || {}, srv = S.services || {}, enCours = S.en_cours || [];
  const s = ETAT.services, quand = (iso) => (iso ? `${dateCourte(iso)} à ${hm(iso)}` : "jamais");
  const plus = { edt: s.edt.ok ? ` · ${s.edt.nb} créneaux` : "", updago: s.updago.ok ? ` · ${s.updago.nb_cours} cours` : "" };
  return `<div class="services">${Object.entries(CONNEXIONS).map(([cle, [titre, bouton]]) => {
    const r = srv[cle], ok = r ? r.ok : null;
    const reparation = enCours.includes(cle) || (cle === "messagerie" && enCours.includes("messagerie"));
    return `<div class="carte"><b>${ok === true ? "✅" : ok === false ? "❌" : "⚪"} ${titre}</b>
      <div class="doux">${esc(r ? r.detail : "pas encore vérifié")}${plus[cle] || ""}</div>
      ${ok !== true && cle === "messagerie" ? `<a class="btn petit" href="#/notes" style="margin-top:.4rem">${bouton}</a>`
      : ok !== true && bouton ? (reparation ? `<p class="doux">⏳ En cours… regarde l'écran du PC.</p>`
        : `<button class="btn petit" data-reparer="${cle}" style="margin-top:.4rem">${bouton}</button>
           ${cle !== "ia_locale" ? `<span class="doux"> (la fenêtre s'ouvre sur le PC)</span>` : ""}`) : ""}</div>`;
  }).join("")}</div>
  <p class="doux">Vérifié ${S.verifie_le ? `le ${quand(S.verifie_le)}` : "jamais"} · à chaque synchronisation (toutes les 3 h)
    · une notification te prévient si une connexion lâche.
    ${enCours.includes("verification") ? "⏳ Vérification en cours…" : `<button class="btn petit" id="sante-verifier">Revérifier maintenant</button>`}</p>`;
}

function vueReglages() {
  vue.innerHTML = `<h1>Réglages</h1>
    <h2>Connexions</h2>
    ${blocConnexions()}
    <h2>Notifications sur cet appareil</h2>
    <div class="carte" id="bloc-notifs"><p class="doux">Vérification…</p></div>
    <h2>Calendrier de l'iPhone</h2>
    <p class="doux">Le fichier <a href="/planning.ics">planning.ics</a> contient tes sessions et tes examens.
      Ouvre-le sur l'iPhone (même Wi-Fi, avec <code>hote = "0.0.0.0"</code>) ou envoie-le toi par mail pour l'importer.</p>
    <h2>Ajouter un examen à la main</h2>${formAjout()}
    <h2>Journal</h2>
    <div class="journal">${ETAT.journal.map((j) => `<div class="${esc(j.niveau)}">${esc(j.date.slice(5, 16).replace("T", " "))} ${esc(j.texte)}</div>`).join("") || "Vide."}</div>`;
  brancherAjout();
  blocNotifications();
  vue.querySelectorAll("[data-reparer]").forEach((b) => b.onclick = async () => {
    b.disabled = true;
    try {
      const r = await post(`/api/reparer/${b.dataset.reparer}`);
      toast(r.ok === false ? r.message : b.dataset.reparer === "ia_locale" ? "LM Studio démarre (jusqu'à 2 min)…"
        : "Une fenêtre s'ouvre sur le PC : connecte-toi dedans.");
    } catch (e) { toast(e.message); }
    await charger(); vueReglages();
  });
  const v = $("#sante-verifier");
  if (v) v.onclick = async () => { await post("/api/sante"); toast("Vérification lancée (une minute environ)."); await charger(); vueReglages(); };
}

if ("serviceWorker" in navigator && window.isSecureContext) navigator.serviceWorker.register("/sw.js").catch(() => {});
router();
