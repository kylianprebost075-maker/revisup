// Jeux pour apprendre : quiz chrono (QCM des packs), exercices R&T générés à l'infini, cartes mémoire, associations.
// Utilise les outils d'app.js ($, api, post, esc, md, toast, vue).

const hasard = (a, b) => a + Math.floor(Math.random() * (b - a + 1));
const choisir = (t) => t[Math.floor(Math.random() * t.length)];
const melanger = (t) => { for (let i = t.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1)); [t[i], t[j]] = [t[j], t[i]]; } return t; };
const nombreFr = (x, dec = 3) => (Math.round(x * 10 ** dec) / 10 ** dec).toString().replace(".", ",");
const lireNombre = (s) => parseFloat(String(s).trim().replace(/\s/g, "").replace(",", ".").replace(/[^0-9.eE+-].*$/, ""));
const proche = (rep, attendu, tolerance) => Number.isFinite(rep) && Math.abs(rep - attendu) <= tolerance;

let PARTIE = null;  // la partie en cours (son minuteur est arrêté quand on change de page)
function arreterPartie() { if (PARTIE && PARTIE.minuteur) clearInterval(PARTIE.minuteur); PARTIE = null; }
window.addEventListener("hashchange", arreterPartie);

async function vueJeux(type, cle) {
  arreterPartie();
  if (type === "quiz" && cle) return jouerQuiz(cle);
  if (type === "exo" && cle) return jouerExo(cle);
  if (type === "cartes" && cle) return jouerCartes(cle);
  if (type === "associations" && cle) return jouerAssociations(cle);
  return menuJeux();
}

// ── menu ─────────────────────────────────────────────────────────────────
const EMOJI_EXO = { ip: "🌐", binaire: "💾", ohm: "⚡", db: "📶", linux: "🐧" };

async function menuJeux() {
  let t;
  try { t = await api("/api/jeux"); } catch (e) { vue.innerHTML = `<p class="vide">${esc(e.message)}</p>`; return; }
  const lien = (h, texte, cls = "") => `<a class="btn ${cls}" href="${h}">${texte}</a>`;
  vue.innerHTML = `
    <h1>Jeux</h1>
    <div class="tuiles">
      <div class="carte tuile"><div class="etiquette">Série</div><div class="valeur">🔥 ${t.serie}<small> jour${t.serie > 1 ? "s" : ""}</small></div>
        <div class="doux">${t.xp_aujourdhui ? "tu as joué aujourd'hui" : "joue aujourd'hui pour la garder"}</div></div>
      <div class="carte tuile"><div class="etiquette">Aujourd'hui</div><div class="valeur">${t.xp_aujourdhui}<small> XP</small></div></div>
      <div class="carte tuile"><div class="etiquette">Total</div><div class="valeur">⭐ ${t.xp}<small> XP</small></div></div>
    </div>

    <h2>🧮 Entraînement R&T, à l'infini</h2>
    <p class="doux">Des exercices tirés au hasard et corrigés étape par étape. Parfait pour 10 minutes entre deux cours.</p>
    <div class="grille-jeux">
      ${t.exos.map((x) => `<a class="carte cliquable jeu-carte" href="#/jeux/exo/${x.type}">
        <div class="jeu-emoji">${EMOJI_EXO[x.type] || "🧮"}</div>
        <div><b>${esc(x.titre)}</b><div class="doux">${esc(x.modules)}</div>
        <div class="doux">${x.faits ? `${Math.round((100 * x.justes) / x.faits)} % de réussite · record ${x.record}` : "jamais joué"}</div></div></a>`).join("")}
    </div>

    <h2>🎯 Par matière</h2>
    ${t.modules.length ? t.modules.map((m) => `<div class="carte jeu-matiere" style="--couleur:${couleur(m.matiere)}">
      <div><b>${esc(m.matiere)}</b> <span class="doux">examen le ${esc(m.date.split("-").reverse().join("/"))}</span></div>
      <div class="ligne" style="margin-top:.5rem">
        ${m.nb_qcm ? lien(`#/jeux/quiz/${encodeURIComponent(m.examen_id)}`, `🎯 Quiz chrono${m.a_revoir ? ` · ${m.a_revoir} à revoir` : ""}`, "principal") : ""}
        ${m.nb_cartes ? lien(`#/jeux/cartes/${encodeURIComponent(m.examen_id)}`, `🃏 Cartes${m.cartes_dues ? ` · ${m.cartes_dues} à réviser` : " ✓"}`)
          + lien(`#/jeux/associations/${encodeURIComponent(m.examen_id)}`, "🔗 Associations")
          : m.generation ? `<span class="doux">⏳ L'IA prépare les cartes mémoire… (une à deux minutes)</span>`
          : `<button class="btn" data-generer="${esc(m.examen_id)}">🃏 Créer les cartes mémoire</button>`}
      </div>
      ${m.record_quiz ? `<div class="doux" style="margin-top:.3rem">🏆 Record au quiz : ${m.record_quiz}${m.record_associations ? ` · associations : ${m.record_associations}` : ""}</div>` : ""}
    </div>`).join("") : `<p class="doux">Les quiz arrivent dès qu'un pack de révision est prêt.</p>`}`;
  vue.querySelectorAll("[data-generer]").forEach((b) => b.onclick = async () => {
    b.disabled = true;
    await post(`/api/jeux/cartes/${encodeURIComponent(b.dataset.generer)}/generer`);
    toast("L'IA locale prépare tes cartes (une à deux minutes).");
    menuJeux();
  });
  if (t.modules.some((m) => m.generation)) setTimeout(() => { if (location.hash === "#/jeux") menuJeux(); }, 15000);
}

// ── fin de partie (commune à tous les jeux) ───────────────────────────────
async function finPartie({ jeu, cle, titre, score, justes, total, reponses = [], details = "", rejouer }) {
  arreterPartie();
  let r = {};
  try { r = await post("/api/jeux/resultat", { jeu, cle, score, justes, total, reponses }); } catch (e) { toast(e.message); }
  const bravo = total && justes / total >= 0.8 ? "Excellent ! 🎉" : total && justes / total >= 0.5 ? "Pas mal 👍" : "On continue 💪";
  vue.innerHTML = `
    <h1>${esc(titre)}</h1>
    <div class="carte fin-partie">
      <div class="gros-score">${score}<small> points</small></div>
      <p><b>${bravo}</b> ${justes} / ${total} juste${justes > 1 ? "s" : ""}</p>
      <p>${r.nouveau_record ? "🏆 <b>Nouveau record !</b>" : r.record ? `Record : ${r.record}` : ""}
        ${r.xp_gagne != null ? ` · +${r.xp_gagne} XP` : ""}${r.serie ? ` · 🔥 série de ${r.serie} jour${r.serie > 1 ? "s" : ""}` : ""}</p>
      <div class="ligne"><button class="btn principal" id="j-rejouer">Rejouer</button><a class="btn" href="#/jeux">Autres jeux</a></div>
    </div>
    ${details}`;
  $("#j-rejouer").onclick = rejouer;
  if (window.renderMathInElement) renderMathInElement(vue, { delimiters: [{ left: "$$", right: "$$", display: true }, { left: "$", right: "$", display: false }] });
}

const coeurs = (n) => "❤️".repeat(Math.max(0, n)) + "🤍".repeat(Math.max(0, 3 - n));

// ── quiz chrono : QCM du pack, 20 s par question, 3 vies, bonus de série ────────
const SECONDES_QUESTION = 20;

async function jouerQuiz(eid) {
  let q;
  try { q = await api(`/api/jeux/quiz/${encodeURIComponent(eid)}`); } catch (e) { vue.innerHTML = `<p class="vide">${esc(e.message)}</p>`; return; }
  const P = PARTIE = { i: 0, score: 0, combo: 0, vies: 3, justes: 0, reponses: [], erreurs: [] };
  const titre = `Quiz · ${q.matiere}`;

  const question = () => {
    const x = q.questions[P.i];
    vue.innerHTML = `
      <div class="jeu-entete"><a href="#/jeux" class="doux">← Jeux</a><span>${coeurs(P.vies)}</span>
        <span>Question ${P.i + 1}/${q.questions.length}</span><b>${P.score} pts</b>${P.combo >= 2 ? `<span class="combo">🔥 ×${P.combo}</span>` : ""}</div>
      <div class="barre-temps"><div id="q-temps"></div></div>
      ${x.a_revoir ? `<p class="doux">↺ Ratée la dernière fois</p>` : ""}
      <div class="carte"><div class="md question-quiz">${md(x.question)}</div></div>
      <div class="choix-quiz">${x.choix.map((c, k) => `<button class="btn" data-k="${k}"><span class="lettre">${"ABCDEF"[k]}</span> <span class="md">${md(c)}</span></button>`).join("")}</div>
      <div id="q-suite"></div>`;
    const debut = Date.now();
    P.minuteur = setInterval(() => {
      const reste = SECONDES_QUESTION - (Date.now() - debut) / 1000;
      const barre = $("#q-temps");
      if (barre) { barre.style.width = `${Math.max(0, (100 * reste) / SECONDES_QUESTION)}%`; barre.classList.toggle("urgent", reste < 5); }
      if (reste <= 0) repondre(-1, 0);
    }, 100);
    vue.querySelectorAll("[data-k]").forEach((b) => b.onclick = () => repondre(+b.dataset.k, SECONDES_QUESTION - (Date.now() - debut) / 1000));
  };

  const repondre = (k, reste) => {
    if (P.repondu === P.i) return;
    P.repondu = P.i;
    clearInterval(P.minuteur);
    const x = q.questions[P.i], juste = k === x.bonne_reponse;
    vue.querySelectorAll("[data-k]").forEach((b) => {
      b.disabled = true;
      if (+b.dataset.k === x.bonne_reponse) b.classList.add("bon");
      else if (+b.dataset.k === k) b.classList.add("mauvais");
    });
    let gain = 0;
    if (juste) {
      P.combo += 1; P.justes += 1;
      gain = Math.round((100 + Math.max(0, reste) * 5) * (1 + 0.25 * (P.combo - 1)));
      P.score += gain;
    } else {
      P.combo = 0; P.vies -= 1;
      P.erreurs.push(x);
    }
    P.reponses.push({ id: x.id, juste });
    const fini = P.vies <= 0 || P.i + 1 >= q.questions.length;
    $("#q-suite").innerHTML = `<div class="carte ${juste ? "retour-bon" : "retour-mauvais"}">
      <b>${juste ? `✅ Bien joué ! +${gain}` : k === -1 ? "⏱️ Temps écoulé" : "❌ Raté"}</b>
      <div class="md">${md(x.explication)}</div>
      <button class="btn principal" id="q-suivant">${fini ? "Voir mon score" : "Question suivante →"}</button></div>`;
    $("#q-suivant").onclick = () => { if (fini) terminer(); else { P.i += 1; question(); } };
    $("#q-suivant").focus();
  };

  const terminer = () => finPartie({
    jeu: "quiz", cle: eid, titre, score: P.score, justes: P.justes, total: P.reponses.length, reponses: P.reponses,
    rejouer: () => jouerQuiz(eid),
    details: P.erreurs.length ? `<h2>À revoir</h2>${P.erreurs.map((x) => `<div class="carte" style="margin-bottom:.5rem">
      <div class="md">${md(x.question)}</div><p>✅ <b>${md(x.choix[x.bonne_reponse])}</b></p><div class="md doux">${md(x.explication)}</div></div>`).join("")}
      <p class="doux">Ces questions reviendront en premier à ta prochaine partie.</p>` : "",
  });
  question();
}

// ── exercices R&T générés ─────────────────────────────────────────────────
// Chaque générateur renvoie { enonce, unite?, choix?, bonne?, verifier(rep), reponse, explication }.

const ip2s = (n) => [24, 16, 8, 0].map((d) => (n >>> d) & 255).join(".");
const s2ip = (s) => {
  const p = String(s).trim().split(".");
  if (p.length !== 4 || p.some((x) => !/^\d{1,3}$/.test(x) || +x > 255)) return null;
  return p.reduce((acc, x) => ((acc << 8) | +x) >>> 0, 0);
};
const octetBin = (n) => n.toString(2).padStart(8, "0");

function genIP() {
  const cidr = choisir([8, 16, 20, 22, 23, 24, 24, 25, 26, 26, 27, 27, 28, 28, 29, 30]);
  const ip = ((hasard(1, 223) << 24) | (hasard(0, 255) << 16) | (hasard(0, 255) << 8) | hasard(1, 254)) >>> 0;
  if (ip >>> 24 === 127) return genIP();
  const masque = cidr === 0 ? 0 : (0xffffffff << (32 - cidr)) >>> 0;
  const reseau = (ip & masque) >>> 0, diffusion = (reseau | ~masque) >>> 0, hotes = 2 ** (32 - cidr) - 2;
  const k = Math.min(3, Math.floor(cidr / 8));  // l'octet où le masque « coupe »
  const mOct = (masque >>> (24 - 8 * k)) & 255, iOct = (ip >>> (24 - 8 * k)) & 255, bloc = 256 - mOct;
  const notation = `${ip2s(ip)}/${cidr}`;
  const calcul = cidr % 8 === 0
    ? `<p>/${cidr} : les ${cidr / 8} premiers octets sont le réseau, le reste est à 0 (réseau) ou à 255 (diffusion).</p>`
    : `<p>Le masque /${cidr} coupe dans le ${k + 1}ᵉ octet : <code>${mOct}</code> = <code>${octetBin(mOct)}</code>.
       Taille de bloc = 256 − ${mOct} = <b>${bloc}</b>.</p>
       <p>Octet de l'adresse : ${iOct} = <code>${octetBin(iOct)}</code> → multiple de ${bloc} juste en dessous :
       <b>${Math.floor(iOct / bloc) * bloc}</b> (réseau) ; diffusion = ${Math.floor(iOct / bloc) * bloc} + ${bloc} − 1 = <b>${Math.floor(iOct / bloc) * bloc + bloc - 1}</b>.</p>`;
  const recap = `<p>Réseau <b>${ip2s(reseau)}</b> · diffusion <b>${ip2s(diffusion)}</b> · hôtes de ${ip2s(reseau + 1)} à ${ip2s(diffusion - 1)}
    · 2<sup>${32 - cidr}</sup> − 2 = <b>${hotes.toLocaleString("fr-FR")}</b> hôtes · masque <b>${ip2s(masque)}</b></p>`;
  const adresse = (attendu) => (rep) => s2ip(rep) === attendu;
  const sorte = choisir(["reseau", "reseau", "diffusion", "diffusion", "hotes", "masque", "cidr", "premiere", "derniere"]);
  const Q = {
    reseau: [`Quelle est l'<b>adresse du réseau</b> de <code>${notation}</code> ?`, adresse(reseau), ip2s(reseau)],
    diffusion: [`Quelle est l'<b>adresse de diffusion</b> (broadcast) de <code>${notation}</code> ?`, adresse(diffusion), ip2s(diffusion)],
    hotes: [`Combien d'<b>adresses d'hôtes utilisables</b> dans un réseau <code>/${cidr}</code> ?`, (r) => lireNombre(r) === hotes, String(hotes)],
    masque: [`Écris le masque <code>/${cidr}</code> en <b>notation décimale pointée</b>.`, adresse(masque), ip2s(masque)],
    cidr: [`Le masque <code>${ip2s(masque)}</code> s'écrit <b>/ combien</b> ?`, (r) => lireNombre(String(r).replace("/", "")) === cidr, `/${cidr}`],
    premiere: [`Quelle est la <b>première adresse d'hôte</b> de <code>${notation}</code> ?`, adresse(reseau + 1), ip2s(reseau + 1)],
    derniere: [`Quelle est la <b>dernière adresse d'hôte</b> de <code>${notation}</code> ?`, adresse(diffusion - 1), ip2s(diffusion - 1)],
  }[sorte];
  return { enonce: Q[0], verifier: Q[1], reponse: Q[2], explication: (sorte === "hotes" || sorte === "cidr" || sorte === "masque" ? "" : calcul) + recap,
           placeholder: sorte === "hotes" ? "nombre" : sorte === "cidr" ? "/24" : "192.168.1.0" };
}

function genBinaire() {
  const n = hasard(1, 255), grand = hasard(16, 4095);
  const bin = (x) => x.toString(2), hex = (x) => x.toString(16).toUpperCase();
  const puissances = (x) => {
    const bits = octetBin(x).split("");
    return `<table class="tableau bits"><tr>${[128, 64, 32, 16, 8, 4, 2, 1].map((p) => `<th>${p}</th>`).join("")}</tr>
      <tr>${bits.map((b) => `<td class="${b === "1" ? "un" : ""}">${b}</td>`).join("")}</tr></table>
      <p>${[128, 64, 32, 16, 8, 4, 2, 1].filter((p, i) => bits[i] === "1").join(" + ")} = <b>${x}</b></p>`;
  };
  const quartets = (x) => {
    const b = x.toString(2).padStart(Math.ceil(x.toString(2).length / 4) * 4, "0").match(/.{4}/g);
    return `<p>On coupe en paquets de 4 bits : ${b.map((q) => `<code>${q}</code> = ${hex(parseInt(q, 2))}`).join(" · ")}</p>`;
  };
  const estBin = (r, x) => /^[01\s]+$/.test(r) && parseInt(r.replace(/\s/g, ""), 2) === x;
  const estHex = (r, x) => /^(0x)?[0-9a-f]+$/i.test(r.trim()) && parseInt(r.trim().replace(/^0x/i, ""), 16) === x;
  const sorte = choisir(["d2b", "b2d", "d2h", "h2d", "b2h", "h2b"]);
  return {
    d2b: { enonce: `Écris <b>${n}</b> (décimal) en <b>binaire</b>.`, verifier: (r) => estBin(r, n), reponse: octetBin(n), explication: puissances(n), placeholder: "0101…" },
    b2d: { enonce: `Combien vaut <code>${octetBin(n)}</code> (binaire) en <b>décimal</b> ?`, verifier: (r) => lireNombre(r) === n, reponse: String(n), explication: puissances(n), placeholder: "nombre" },
    d2h: { enonce: `Écris <b>${grand}</b> (décimal) en <b>hexadécimal</b>.`, verifier: (r) => estHex(r, grand), reponse: hex(grand),
           explication: `<p>${grand} = ${bin(grand)} en binaire.</p>${quartets(grand)}`, placeholder: "A3F" },
    h2d: { enonce: `Combien vaut <code>0x${hex(grand)}</code> en <b>décimal</b> ?`, verifier: (r) => lireNombre(r) === grand, reponse: String(grand),
           explication: `<p>${hex(grand).split("").reverse().map((c, i) => `${parseInt(c, 16)} × 16<sup>${i}</sup>`).reverse().join(" + ")} = <b>${grand}</b></p>`, placeholder: "nombre" },
    b2h: { enonce: `Écris <code>${octetBin(n)}</code> (binaire) en <b>hexadécimal</b>.`, verifier: (r) => estHex(r, n), reponse: hex(n), explication: quartets(n), placeholder: "A3" },
    h2b: { enonce: `Écris <code>0x${hex(n)}</code> en <b>binaire</b> (8 bits).`, verifier: (r) => estBin(r, n), reponse: octetBin(n),
           explication: `<p>Chaque chiffre hexa donne 4 bits : ${hex(n).padStart(2, "0").split("").map((c) => `${c} = <code>${parseInt(c, 16).toString(2).padStart(4, "0")}</code>`).join(" · ")}</p>`, placeholder: "0101…" },
  }[sorte];
}

function genOhm() {
  const R = choisir([100, 150, 220, 330, 470, 680, 1000, 1500, 2200, 3300, 4700, 10000]);
  const ohms = (r) => (r >= 1000 ? `${nombreFr(r / 1000)} kΩ` : `${r} Ω`);
  const sorte = choisir(["U", "I", "R", "P", "diviseur", "diviseur", "serie", "parallele"]);
  const tol = (x) => Math.max(Math.abs(x) * 0.01, 0.005);
  if (sorte === "U" || sorte === "I" || sorte === "R") {
    const I = choisir([1, 2, 5, 10, 12, 15, 20, 25, 30, 50].filter((ma) => (R * ma) / 1000 <= 24)) / 1000, U = R * I;  // A, V (≤ 24 V : du réaliste)
    if (sorte === "U") return { enonce: `Une résistance de <b>${ohms(R)}</b> est traversée par <b>${nombreFr(I * 1000)} mA</b>. Quelle est la <b>tension</b> à ses bornes ?`,
      unite: "V", verifier: (r) => proche(lireNombre(r), U, tol(U)), reponse: `${nombreFr(U)} V`,
      explication: `<p>Loi d'Ohm : <b>U = R × I</b> = ${R} Ω × ${nombreFr(I)} A = <b>${nombreFr(U)} V</b>.</p><p class="doux">Pense à convertir les mA en A (÷ 1000).</p>` };
    if (sorte === "I") return { enonce: `On applique <b>${nombreFr(U)} V</b> sur une résistance de <b>${ohms(R)}</b>. Quel <b>courant</b> la traverse ?`,
      unite: "mA", verifier: (r) => proche(lireNombre(r), I * 1000, tol(I * 1000)), reponse: `${nombreFr(I * 1000)} mA`,
      explication: `<p><b>I = U / R</b> = ${nombreFr(U)} V / ${R} Ω = ${nombreFr(I, 4)} A = <b>${nombreFr(I * 1000)} mA</b>.</p>` };
    return { enonce: `Une résistance a <b>${nombreFr(U)} V</b> à ses bornes et est traversée par <b>${nombreFr(I * 1000)} mA</b>. Quelle est sa <b>valeur</b> ?`,
      unite: "Ω", verifier: (r) => proche(lireNombre(r), R, tol(R)), reponse: `${R} Ω`,
      explication: `<p><b>R = U / I</b> = ${nombreFr(U)} V / ${nombreFr(I)} A = <b>${R} Ω</b>.</p>` };
  }
  if (sorte === "P") {
    const U = choisir([3.3, 5, 9, 12, 24]), I = choisir([10, 20, 50, 100, 200, 500]) / 1000, P = U * I;
    return { enonce: `Un composant alimenté en <b>${nombreFr(U)} V</b> consomme <b>${nombreFr(I * 1000)} mA</b>. Quelle <b>puissance</b> consomme-t-il ?`,
      unite: "W", verifier: (r) => proche(lireNombre(r), P, tol(P)), reponse: `${nombreFr(P)} W`,
      explication: `<p><b>P = U × I</b> = ${nombreFr(U)} V × ${nombreFr(I)} A = <b>${nombreFr(P)} W</b> (= ${nombreFr(P * 1000)} mW).</p>` };
  }
  if (sorte === "diviseur") {
    const Ve = choisir([5, 9, 10, 12, 15, 24]), R1 = choisir([1000, 2200, 3300, 4700, 10000]), R2 = choisir([1000, 2200, 3300, 4700, 10000]);
    const Vs = (Ve * R2) / (R1 + R2);
    return { enonce: `Pont diviseur : <b>Ve = ${Ve} V</b>, <b>R1 = ${ohms(R1)}</b> (en haut), <b>R2 = ${ohms(R2)}</b> (en bas, côté masse). Quelle est la tension <b>Vs</b> aux bornes de R2 ?`,
      unite: "V", verifier: (r) => proche(lireNombre(r), Vs, tol(Vs)), reponse: `${nombreFr(Vs, 2)} V`,
      explication: `<p><b>Vs = Ve × R2 / (R1 + R2)</b> = ${Ve} × ${R2} / (${R1} + ${R2}) = <b>${nombreFr(Vs, 2)} V</b>.</p><p class="doux">Vérifie : Vs est toujours plus petite que Ve.</p>` };
  }
  const R1 = choisir([100, 220, 330, 470, 1000, 2200, 4700]), R2 = choisir([100, 220, 330, 470, 1000, 2200, 4700]);
  if (sorte === "serie") return { enonce: `<b>${ohms(R1)}</b> et <b>${ohms(R2)}</b> sont montées <b>en série</b>. Quelle est la résistance équivalente ?`,
    unite: "Ω", verifier: (r) => proche(lireNombre(r), R1 + R2, tol(R1 + R2)), reponse: `${R1 + R2} Ω`,
    explication: `<p>En série, les résistances s'additionnent : ${R1} + ${R2} = <b>${R1 + R2} Ω</b>.</p>` };
  const Req = (R1 * R2) / (R1 + R2);
  return { enonce: `<b>${ohms(R1)}</b> et <b>${ohms(R2)}</b> sont montées <b>en parallèle</b>. Quelle est la résistance équivalente ?`,
    unite: "Ω", verifier: (r) => proche(lireNombre(r), Req, tol(Req)), reponse: `${nombreFr(Req, 1)} Ω`,
    explication: `<p>En parallèle : <b>Req = R1 × R2 / (R1 + R2)</b> = ${R1} × ${R2} / ${R1 + R2} = <b>${nombreFr(Req, 1)} Ω</b>.</p><p class="doux">Req est toujours plus petite que la plus petite des deux.</p>` };
}

function genDb() {
  const sorte = choisir(["gain", "gain", "dbm", "mw", "cable", "chaine"]);
  const tol = 0.15;
  if (sorte === "gain") {
    const ratio = choisir([2, 4, 10, 20, 100, 1000, 0.5, 0.1, 0.01]), Pe = choisir([1, 2, 5, 10]), Ps = Pe * ratio, G = 10 * Math.log10(ratio);
    return { enonce: `Un étage reçoit <b>${nombreFr(Pe)} mW</b> et fournit <b>${nombreFr(Ps)} mW</b>. Quel est son <b>gain en dB</b> ?`,
      unite: "dB", verifier: (r) => proche(lireNombre(r), G, tol), reponse: `${nombreFr(G, 1)} dB`,
      explication: `<p><b>G = 10 × log(Ps / Pe)</b> = 10 × log(${nombreFr(ratio)}) = <b>${nombreFr(G, 1)} dB</b>.</p><p class="doux">Repères : ×2 = +3 dB, ×10 = +10 dB, ÷2 = −3 dB, ÷10 = −10 dB.</p>` };
  }
  if (sorte === "dbm") {
    const P = choisir([1, 2, 10, 20, 50, 100, 500, 1000, 0.1, 0.5]), dbm = 10 * Math.log10(P);
    return { enonce: `Convertis <b>${nombreFr(P)} mW</b> en <b>dBm</b>.`, unite: "dBm", verifier: (r) => proche(lireNombre(r), dbm, tol), reponse: `${nombreFr(dbm, 1)} dBm`,
      explication: `<p><b>P(dBm) = 10 × log(P / 1 mW)</b> = 10 × log(${nombreFr(P)}) = <b>${nombreFr(dbm, 1)} dBm</b>.</p><p class="doux">0 dBm = 1 mW ; 10 dBm = 10 mW ; 20 dBm = 100 mW ; 30 dBm = 1 W.</p>` };
  }
  if (sorte === "mw") {
    const dbm = choisir([-10, -3, 0, 3, 7, 10, 13, 20, 23, 30]), P = 10 ** (dbm / 10);
    return { enonce: `Convertis <b>${dbm} dBm</b> en <b>mW</b>.`, unite: "mW", verifier: (r) => proche(lireNombre(r), P, Math.max(P * 0.03, 0.01)), reponse: `${nombreFr(P, 2)} mW`,
      explication: `<p><b>P = 10<sup>dBm/10</sup></b> mW = 10<sup>${nombreFr(dbm / 10, 1)}</sup> = <b>${nombreFr(P, 2)} mW</b>.</p>` };
  }
  if (sorte === "cable") {
    const a = choisir([0.2, 0.25, 0.5, 2, 3, 5, 10, 20]), L = choisir([2, 4, 5, 10, 25, 40]), unite = a >= 2 ? "100 m" : "km";
    const longueur = unite === "km" ? `${L} km` : `${L * 100} m`, A = a * L, Pe = choisir([0, 5, 10, 20]), Ps = Pe - A;
    return { enonce: `Un câble atténue de <b>${nombreFr(a)} dB/${unite}</b>. On injecte <b>${Pe} dBm</b> sur <b>${longueur}</b>. Quelle puissance reçoit-on en sortie ?`,
      unite: "dBm", verifier: (r) => proche(lireNombre(r), Ps, tol), reponse: `${nombreFr(Ps, 1)} dBm`,
      explication: `<p>Atténuation totale = ${nombreFr(a)} dB × ${L} = <b>${nombreFr(A, 1)} dB</b>.</p><p>En dB, on soustrait : ${Pe} − ${nombreFr(A, 1)} = <b>${nombreFr(Ps, 1)} dBm</b>.</p>` };
  }
  const Pe = choisir([-10, -5, 0, 3]), G1 = choisir([10, 15, 20]), A1 = choisir([3, 6, 8, 12]), G2 = choisir([6, 10, 13]), Ps = Pe + G1 - A1 + G2;
  return { enonce: `Une chaîne reçoit <b>${Pe} dBm</b>, puis passe dans un ampli de <b>+${G1} dB</b>, un câble de <b>${A1} dB</b> de pertes et un second ampli de <b>+${G2} dB</b>. Puissance en sortie ?`,
    unite: "dBm", verifier: (r) => proche(lireNombre(r), Ps, tol), reponse: `${Ps} dBm`,
    explication: `<p>En dB tout s'additionne : ${Pe} + ${G1} − ${A1} + ${G2} = <b>${Ps} dBm</b>.</p><p class="doux">C'est tout l'intérêt des dB : on additionne au lieu de multiplier.</p>` };
}

const COMMANDES_LINUX = [
  ["Afficher le dossier où tu te trouves", "pwd", ["cd", "ls", "whoami"]],
  ["Lister les fichiers, cachés compris", "ls -a", ["ls -l", "ls -h", "dir -c"]],
  ["Lister avec les droits, le propriétaire et la taille", "ls -l", ["ls -a", "ls -r", "stat -a"]],
  ["Remonter au dossier parent", "cd ..", ["cd /", "cd ~", "cd -p"]],
  ["Créer un dossier et ses parents d'un coup", "mkdir -p a/b/c", ["mkdir -r a/b/c", "touch a/b/c", "md a/b/c"]],
  ["Supprimer un dossier et tout son contenu", "rm -r dossier", ["rmdir dossier", "rm dossier", "del -r dossier"]],
  ["Copier un dossier et son contenu", "cp -r src dst", ["cp src dst", "mv -r src dst", "copy src dst"]],
  ["Renommer un fichier", "mv ancien nouveau", ["rn ancien nouveau", "cp ancien nouveau", "rename -f ancien"]],
  ["Afficher les 5 premières lignes d'un fichier", "head -n 5 f", ["tail -n 5 f", "cat -5 f", "less -n 5 f"]],
  ["Suivre un journal en direct", "tail -f f", ["head -f f", "cat -f f", "watch f"]],
  ["Chercher « erreur » sans tenir compte des majuscules", "grep -i erreur f", ["grep -v erreur f", "find -i erreur f", "grep -c erreur f"]],
  ["Trouver les fichiers nommés notes.txt sous /home", "find /home -name notes.txt", ["grep -r notes.txt /home", "locate -d /home notes.txt", "ls -R /home notes.txt"]],
  ["Voir tous les processus", "ps aux", ["ps -l", "jobs", "top -n"]],
  ["Tuer de force le processus 1234", "kill -9 1234", ["kill 1234 -f", "stop 1234", "pkill -9"]],
  ["Espace libre des disques, lisible", "df -h", ["du -h", "free -h", "fdisk -l"]],
  ["Taille totale d'un dossier", "du -sh dossier", ["df -h dossier", "ls -s dossier", "size dossier"]],
  ["Changer le propriétaire d'un fichier", "chown alice f", ["chmod alice f", "chgrp alice f", "own alice f"]],
  ["Écrire la sortie d'une commande à la fin d'un fichier", "cmd >> f", ["cmd > f", "cmd | f", "cmd < f"]],
  ["Envoyer la sortie de ls vers grep", "ls | grep txt", ["ls > grep txt", "ls >> grep txt", "ls & grep txt"]],
  ["Voir l'adresse IP de la machine", "ip a", ["ip r", "ping -a", "hostname -r"]],
  ["Lancer une commande en administrateur", "sudo cmd", ["su cmd", "root cmd", "admin cmd"]],
  ["Lire le manuel d'une commande", "man ls", ["help -m ls", "info -l ls", "ls --man"]],
  ["Décompresser une archive .tar.gz", "tar -xzf a.tar.gz", ["tar -czf a.tar.gz", "unzip a.tar.gz", "gzip -x a.tar.gz"]],
  ["Savoir sous quel utilisateur tu es connecté", "whoami", ["who", "id -g", "users"]],
];
const rwx = (d) => ["r", "w", "x"].map((c, i) => (d & (4 >> i) ? c : "-")).join("");

function genLinux() {
  if (Math.random() < 0.45) {  // droits : octal ↔ rwx, généré
    const chiffres = [hasard(4, 7), hasard(0, 7), hasard(0, 7)], octal = chiffres.join(""), lettres = chiffres.map(rwx).join("");
    const detail = `<p>${chiffres.map((d, i) => `${["propriétaire", "groupe", "autres"][i]} : ${d} = ${[4, 2, 1].filter((p) => d & p).join(" + ") || "0"} → <code>${rwx(d)}</code>`).join("<br>")}</p><p class="doux">r = 4, w = 2, x = 1.</p>`;
    if (Math.random() < 0.5) return { enonce: `Avec <code>chmod ${octal} fichier</code>, quels droits obtient-on ? (9 lettres, comme <code>rwxr-x---</code>)`,
      verifier: (r) => r.trim().replace(/^-/, "").toLowerCase() === lettres, reponse: lettres, explication: detail, placeholder: "rwxr-x---" };
    return { enonce: `Quel nombre donner à <code>chmod</code> pour obtenir <code>${lettres}</code> ?`,
      verifier: (r) => r.trim() === octal, reponse: octal, explication: detail, placeholder: "755" };
  }
  const [q, bonne, faux] = choisir(COMMANDES_LINUX);
  const choix = melanger([bonne, ...faux]);
  return { enonce: `${q} ?`, choix: choix.map((c) => `<code>${esc(c)}</code>`), bonne: choix.indexOf(bonne),
           verifier: (k) => k === choix.indexOf(bonne), reponse: bonne, explication: `<p>Réponse : <code>${esc(bonne)}</code></p>` };
}

const GENERATEURS = { ip: genIP, binaire: genBinaire, ohm: genOhm, db: genDb, linux: genLinux };
const TITRES_EXO = { ip: "Adressage IP", binaire: "Binaire / hexa", ohm: "Loi d'Ohm", db: "Décibels", linux: "Linux" };
const NB_EXOS = 10;

function jouerExo(type) {
  const generer = GENERATEURS[type];
  if (!generer) { location.hash = "#/jeux"; return; }
  const P = PARTIE = { i: 0, score: 0, combo: 0, justes: 0, ratees: [] };
  const titre = `${EMOJI_EXO[type]} ${TITRES_EXO[type]}`;

  const exercice = () => {
    const x = P.x = generer();
    P.debut = Date.now();
    vue.innerHTML = `
      <div class="jeu-entete"><a href="#/jeux" class="doux">← Jeux</a><span>${esc(titre)}</span>
        <span>${P.i + 1}/${NB_EXOS}</span><b>${P.score} pts</b>${P.combo >= 2 ? `<span class="combo">🔥 ×${P.combo}</span>` : ""}</div>
      <div class="carte"><p class="enonce-exo">${x.enonce}</p>
        ${x.choix ? `<div class="choix-quiz">${x.choix.map((c, k) => `<button class="btn" data-k="${k}"><span class="lettre">${"ABCD"[k]}</span> ${c}</button>`).join("")}</div>`
          : `<form class="ligne" id="e-form"><input id="e-rep" autocomplete="off" autocapitalize="off" spellcheck="false"
               inputmode="${/^(V|mA|Ω|W|dB|dBm|mW)$/.test(x.unite || "") || x.placeholder === "nombre" ? "decimal" : "text"}"
               placeholder="${esc(x.placeholder || "ta réponse")}" style="flex:1;min-width:9rem;font-size:1.1rem">
             ${x.unite ? `<span class="unite">${x.unite}</span>` : ""}<button class="btn principal">Valider</button></form>`}
      </div>
      <div id="e-suite"></div>`;
    if (x.choix) vue.querySelectorAll("[data-k]").forEach((b) => b.onclick = () => corriger(+b.dataset.k));
    else { $("#e-form").onsubmit = (ev) => { ev.preventDefault(); const v = $("#e-rep").value; if (v.trim()) corriger(v); }; $("#e-rep").focus(); }
  };

  const corriger = (rep) => {
    if (P.corrige === P.i) return;
    P.corrige = P.i;
    const x = P.x, juste = x.verifier(rep), secondes = (Date.now() - P.debut) / 1000;
    if (x.choix) vue.querySelectorAll("[data-k]").forEach((b) => {
      b.disabled = true;
      if (+b.dataset.k === x.bonne) b.classList.add("bon"); else if (+b.dataset.k === rep) b.classList.add("mauvais");
    });
    else { $("#e-rep").disabled = true; $("#e-form button").disabled = true; $("#e-rep").classList.add(juste ? "bon" : "mauvais"); }
    let gain = 0;
    if (juste) {
      P.combo += 1; P.justes += 1;
      gain = Math.round((100 + Math.max(0, 60 - secondes)) * (1 + 0.25 * (P.combo - 1)));
      P.score += gain;
    } else { P.combo = 0; P.ratees.push(x); }
    const fini = P.i + 1 >= NB_EXOS;
    $("#e-suite").innerHTML = `<div class="carte ${juste ? "retour-bon" : "retour-mauvais"}">
      <b>${juste ? `✅ Juste ! +${gain}` : `❌ La bonne réponse : ${esc(x.reponse)}`}</b>${x.explication}
      <button class="btn principal" id="e-suivant">${fini ? "Voir mon score" : "Exercice suivant →"}</button></div>`;
    $("#e-suivant").onclick = () => {
      if (!fini) { P.i += 1; exercice(); return; }
      finPartie({ jeu: "exo", cle: type, titre, score: P.score, justes: P.justes, total: NB_EXOS, rejouer: () => jouerExo(type),
        details: P.ratees.length ? `<h2>Tes erreurs, corrigées</h2>${P.ratees.map((r) => `<div class="carte" style="margin-bottom:.5rem">
          <p>${r.enonce}</p><p>✅ <b>${esc(r.reponse)}</b></p>${r.explication}</div>`).join("")}` : "" });
    };
    $("#e-suivant").focus();
  };
  exercice();
}

// ── cartes mémoire (boîtes de Leitner : une carte sue revient de plus en plus tard) ──────
async function jouerCartes(eid, toutes = false) {
  let r;
  try { r = await api(`/api/jeux/cartes/${encodeURIComponent(eid)}${toutes ? "?toutes=1" : ""}`); } catch (e) { vue.innerHTML = `<p class="vide">${esc(e.message)}</p>`; return; }
  const cartes = r.cartes.slice(0, 20);
  if (!cartes.length) {
    vue.innerHTML = `<div class="jeu-entete"><a href="#/jeux" class="doux">← Jeux</a></div>
      <div class="carte fin-partie"><div class="gros-score">🎉</div><p><b>Rien à réviser aujourd'hui en ${esc(r.matiere)}.</b>
      Les cartes que tu connais reviennent dans quelques jours.</p>
      <div class="ligne"><button class="btn principal" id="c-toutes">Les revoir quand même</button><a class="btn" href="#/jeux">Autres jeux</a></div></div>`;
    $("#c-toutes").onclick = () => jouerCartes(eid, true);
    return;
  }
  const P = PARTIE = { i: 0, sues: 0 };
  const titre = `Cartes · ${r.matiere}`;
  const carte = () => {
    const c = cartes[P.i];
    vue.innerHTML = `
      <div class="jeu-entete"><a href="#/jeux" class="doux">← Jeux</a><span>${esc(r.matiere)}</span><span>${P.i + 1}/${cartes.length}</span>
        <span class="doux">${c.boite ? `boîte ${c.boite}/5` : "nouvelle"}</span></div>
      <button class="carte-memoire" id="c-carte" aria-label="Retourner la carte">
        <span class="face recto"><span class="md">${md(c.recto)}</span><small class="doux">Touche pour voir la réponse</small></span>
        <span class="face verso"><span class="md">${md(c.verso)}</span>${c.chapitre ? `<small class="doux">${esc(c.chapitre)}</small>` : ""}</span>
      </button>
      <div class="ligne reponses-carte" id="c-boutons" hidden>
        <button class="btn mauvais-btn" data-su="0">😕 À revoir</button><button class="btn bon-btn" data-su="1">✅ Je savais</button></div>`;
    $("#c-carte").onclick = () => { $("#c-carte").classList.add("retournee"); $("#c-boutons").hidden = false; };
    vue.querySelectorAll("[data-su]").forEach((b) => b.onclick = async () => {
      const su = b.dataset.su === "1";
      if (su) P.sues += 1;
      post("/api/jeux/carte", { id: c.id, su }).catch(() => {});
      if (P.i + 1 < cartes.length) { P.i += 1; carte(); }
      else finPartie({ jeu: "cartes", cle: eid, titre, score: P.sues * 50, justes: P.sues, total: cartes.length,
        rejouer: () => jouerCartes(eid), details: `<p class="doux">Les cartes « à revoir » reviendront dès demain ; celles que tu savais, dans quelques jours.</p>` });
    });
  };
  carte();
}

// ── associations : relier chaque notion à sa définition, contre la montre ──────
async function jouerAssociations(eid) {
  let r;
  try { r = await api(`/api/jeux/cartes/${encodeURIComponent(eid)}?toutes=1`); } catch (e) { vue.innerHTML = `<p class="vide">${esc(e.message)}</p>`; return; }
  if (r.cartes.length < 4) { toast("Il faut au moins 4 cartes pour jouer."); location.hash = "#/jeux"; return; }
  const manches = [];
  const paquet = melanger(r.cartes.slice()).slice(0, 18);
  for (let i = 0; i < paquet.length; i += 6) if (paquet.length - i >= 3) manches.push(paquet.slice(i, i + 6));
  const P = PARTIE = { m: 0, erreurs: 0, trouvees: 0, debut: Date.now() };
  const titre = `Associations · ${r.matiere}`;

  const manche = () => {
    const paires = manches[P.m];
    const gauche = melanger(paires.slice()), droite = melanger(paires.slice());
    vue.innerHTML = `
      <div class="jeu-entete"><a href="#/jeux" class="doux">← Jeux</a><span>${esc(r.matiere)}</span>
        <span>Manche ${P.m + 1}/${manches.length}</span><span id="a-temps">0 s</span><span>❌ ${P.erreurs}</span></div>
      <p class="doux">Touche une notion, puis sa définition.</p>
      <div class="assoc">
        <div>${gauche.map((c) => `<button class="btn assoc-g" data-id="${esc(c.id)}">${md(c.recto)}</button>`).join("")}</div>
        <div>${droite.map((c) => `<button class="btn assoc-d" data-id="${esc(c.id)}">${md(c.verso)}</button>`).join("")}</div>
      </div>`;
    let choisie = null, restantes = paires.length;
    vue.querySelectorAll(".assoc-g").forEach((b) => b.onclick = () => {
      vue.querySelectorAll(".assoc-g").forEach((x) => x.classList.remove("choisie"));
      b.classList.add("choisie"); choisie = b;
    });
    vue.querySelectorAll(".assoc-d").forEach((b) => b.onclick = () => {
      if (!choisie) { toast("Choisis d'abord une notion à gauche."); return; }
      if (b.dataset.id === choisie.dataset.id) {
        [b, choisie].forEach((x) => { x.classList.remove("choisie"); x.classList.add("trouvee"); x.disabled = true; });
        choisie = null; P.trouvees += 1; restantes -= 1;
        if (!restantes) setTimeout(() => { if (P.m + 1 < manches.length) { P.m += 1; manche(); } else terminer(); }, 450);
      } else {
        P.erreurs += 1;
        b.classList.add("mauvais"); setTimeout(() => b.classList.remove("mauvais"), 500);
        const compteur = vue.querySelector(".jeu-entete span:last-child"); if (compteur) compteur.textContent = `❌ ${P.erreurs}`;
      }
    });
  };
  P.minuteur = setInterval(() => { const t = $("#a-temps"); if (t) t.textContent = `${Math.round((Date.now() - P.debut) / 1000)} s`; }, 500);
  const terminer = () => {
    const secondes = Math.round((Date.now() - P.debut) / 1000);
    const score = Math.max(0, P.trouvees * 100 - P.erreurs * 30 + Math.max(0, P.trouvees * 8 - secondes) * 5);
    finPartie({ jeu: "associations", cle: eid, titre, score, justes: P.trouvees, total: P.trouvees + P.erreurs,
      rejouer: () => jouerAssociations(eid), details: `<p class="doux">${P.trouvees} paires en ${secondes} s, ${P.erreurs} erreur${P.erreurs > 1 ? "s" : ""}.</p>` });
  };
  manche();
}
