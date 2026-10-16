const token = document.querySelector("main").dataset.token;
const histories = { local: [], claude: [] },
  lastRuns = {
    local: sessionStorage.getItem("prono-team-local"),
    claude: sessionStorage.getItem("prono-team-claude"),
  };
const status = document.getElementById("status"),
  trace = document.getElementById("team-trace");
const strategy = document.getElementById("strategy"),
  force = document.getElementById("force"),
  selectionCount = document.getElementById("selection-count"),
  preview = document.getElementById("selection-preview");
const model = document.getElementById("model"),
  league = document.getElementById("league"),
  period = document.getElementById("period"),
  provider = document.getElementById("provider"),
  mode = document.getElementById("mode"),
  match = document.getElementById("match");
const initialParams = new URLSearchParams(location.search);
let initialEvent = initialParams.get("event") || "";
const manualIds = new Set();
function manualMode() { return match.value === "manual"; }
function renderManualMatches(data) {
  const box = document.getElementById("manual-matches");
  box.replaceChildren();
  const rows = data?.selection?.rows || [];
  for (const id of manualIds) {
    if (!rows.some(r => r.event_id === id)) manualIds.delete(id);
  }
  for (const row of rows) {
    const label = document.createElement("label"), input = document.createElement("input"), text = document.createElement("span");
    input.type = "checkbox";
    input.value = row.event_id;
    input.checked = manualIds.has(row.event_id);
    input.onchange = () => {
      if (input.checked) manualIds.add(row.event_id);
      else manualIds.delete(row.event_id);
      renderSelection(lastMatchData);
    };
    text.textContent = row.match + (row.exclusions.length ? " · Hors filtre automatique" : "");
    label.append(input, text);
    box.append(label);
  }
}
let busy = false,
  options = null,
  matchLoad = 0,
  lastMatchData = null,
  matchesLoading = true;
function syncBackLink() {
  document.getElementById("back-pronos").href =
    "/?" +
    new URLSearchParams({
      tab: "pronos",
      league: league.value,
      horizon: period.value,
    });
}
function appendMarkdownInline(parent, text) {
  const pattern = /\*\*([^*]+)\*\*|`([^`]+)`|\[([^\]]+)\]\(([^\s)]+)\)/g;
  let cursor = 0, part;
  while ((part = pattern.exec(text))) {
    parent.append(document.createTextNode(text.slice(cursor, part.index)));
    let node;
    if (part[1] !== undefined) {
      node = document.createElement("strong");
      node.textContent = part[1];
    } else if (part[2] !== undefined) {
      node = document.createElement("code");
      node.textContent = part[2];
    } else {
      try {
        const url = new URL(part[4]);
        if (!["http:", "https:"].includes(url.protocol) || url.username || url.password) throw Error();
        node = document.createElement("a");
        node.href = url.href;
        node.target = "_blank";
        node.rel = "noopener noreferrer";
        node.textContent = part[3];
      } catch {
        node = document.createTextNode(part[0]);
      }
    }
    parent.append(node);
    cursor = pattern.lastIndex;
  }
  parent.append(document.createTextNode(text.slice(cursor)));
}
function markdownCells(line) {
  const cells = [];
  let cell = "", escaped = false, code = false;
  for (const char of line.trim().replace(/^\|/, "").replace(/\|$/, "")) {
    if (escaped) { cell += char === "|" ? char : "\\" + char; escaped = false; }
    else if (char === "\\") escaped = true;
    else if (char === "`") { code = !code; cell += char; }
    else if (char === "|" && !code) { cells.push(cell.trim()); cell = ""; }
    else cell += char;
  }
  if (escaped) cell += "\\";
  cells.push(cell.trim());
  return cells;
}
function renderMarkdown(text) {
  const body = document.createElement("div");
  body.className = "markdown-body";
  const lines = String(text).replace(/\r\n?/g, "\n").split("\n");
  const isTable = (i) => lines[i]?.includes("|") && i + 1 < lines.length &&
    markdownCells(lines[i + 1]).length === markdownCells(lines[i]).length &&
    markdownCells(lines[i + 1]).every(cell => /^:?-{3,}:?$/.test(cell));
  for (let i = 0; i < lines.length;) {
    const line = lines[i], heading = /^(#{1,6})\s+(.+)$/.exec(line);
    if (!line.trim()) { i++; continue; }
    if (isTable(i)) {
      const headers = markdownCells(line), wrap = document.createElement("div"),
        table = document.createElement("table"), head = document.createElement("thead"),
        headRow = document.createElement("tr"), rows = document.createElement("tbody");
      wrap.className = "markdown-table-scroll";
      wrap.tabIndex = 0;
      wrap.setAttribute("role", "region");
      wrap.setAttribute("aria-label", "Tableau de l’analyse, défilement horizontal disponible");
      for (const value of headers) {
        const cell = document.createElement("th");
        cell.scope = "col"; appendMarkdownInline(cell, value); headRow.append(cell);
      }
      head.append(headRow); table.append(head); i += 2;
      while (i < lines.length && lines[i].trim() && lines[i].includes("|")) {
        const values = markdownCells(lines[i]), row = document.createElement("tr");
        for (let col = 0; col < headers.length; col++) {
          const cell = document.createElement("td");
          appendMarkdownInline(cell, col === headers.length - 1 ? values.slice(col).join(" | ") : (values[col] || ""));
          row.append(cell);
        }
        rows.append(row); i++;
      }
      table.append(rows); wrap.append(table); body.append(wrap); continue;
    }
    if (/^\s*```/.test(line)) {
      const pre = document.createElement("pre"), code = document.createElement("code"), content = [];
      i++;
      while (i < lines.length && !/^\s*```/.test(lines[i])) content.push(lines[i++]);
      code.textContent = content.join("\n"); pre.append(code); body.append(pre);
      if (i < lines.length) i++;
      continue;
    }
    if (heading) {
      const node = document.createElement("h" + Math.min(6, heading[1].length + 1));
      appendMarkdownInline(node, heading[2]); body.append(node); i++; continue;
    }
    if (/^\s*(?:-{3,}|\*{3,}|_{3,})\s*$/.test(line)) { body.append(document.createElement("hr")); i++; continue; }
    const listPattern = /^\s*[-*+]\s+/.test(line) ? /^\s*[-*+]\s+(.*)$/ : /^\s*\d+[.)]\s+/.test(line) ? /^\s*\d+[.)]\s+(.*)$/ : null;
    if (listPattern) {
      const list = document.createElement(/^\s*\d/.test(line) ? "ol" : "ul");
      while (i < lines.length) {
        const item = listPattern.exec(lines[i]);
        if (!item) break;
        const node = document.createElement("li"); appendMarkdownInline(node, item[1]); list.append(node); i++;
      }
      body.append(list); continue;
    }
    const paragraph = document.createElement("p");
    appendMarkdownInline(paragraph, line); i++;
    while (i < lines.length && lines[i].trim() && !isTable(i) && !/^\s*(?:#{1,6}\s|[-*+]\s|\d+[.)]\s|```|---|\*\*\*)/.test(lines[i])) {
      paragraph.append(document.createElement("br")); appendMarkdownInline(paragraph, lines[i++]);
    }
    body.append(paragraph);
  }
  return body;
}
function bubble(role, text) {
  const box = document.createElement("div");
  box.className = "bubble " + role;
  const who = document.createElement("small");
  who.textContent =
    role === "user"
      ? "VOUS"
      : provider.value === "claude"
        ? "CLAUDE"
        : "COACH LOCAL";
  box.append(who, role === "assistant" ? renderMarkdown(text) : document.createTextNode(text));
  document.getElementById("messages").append(box);
  box.scrollIntoView({ behavior: "smooth", block: "end" });
}
async function jsonResponse(response) {
  if (!response.ok) {
    let data;
    try {
      data = await response.json();
    } catch {}
    throw Error(
      data?.error ||
        "La demande a échoué. Rechargez le chat si le dashboard vient d’être relancé.",
    );
  }
  return response.json();
}
async function post(url, payload) {
  return jsonResponse(
    await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Prono-Token": token },
      body: JSON.stringify(payload),
    }),
  );
}
async function getJob(id) {
  return jsonResponse(
    await fetch("/api/chat/jobs/" + encodeURIComponent(id), {
      headers: { "X-Prono-Token": token },
    }),
  );
}
function available() {
  return (
    options &&
    (provider.value === "claude"
      ? options.claude.available
      : options.models.length > 0)
  );
}
function updateControls() {
  document.getElementById("send").disabled = busy || !available() || matchesLoading || (manualMode() && manualIds.size === 0);
  for (const control of [
    provider,
    model,
    league,
    period,
    mode,
    match,
    strategy,
    force,
    selectionCount,
  ])
    control.disabled = busy;
  document.getElementById("manual-selection").hidden = !manualMode();
  document.getElementById("manual-count").textContent = manualIds.size + " / 5 matchs choisis";
  for (const input of document.querySelectorAll("#manual-matches input"))
    input.disabled = busy || matchesLoading || (!input.checked && manualIds.size >= 5);
  match.disabled = busy || matchesLoading;
  selectionCount.disabled = busy || !!match.value;
  document.getElementById("prepare").disabled =
    busy ||
    !available() ||
    matchesLoading ||
    !lastMatchData ||
    (manualMode() ? manualIds.size === 0 : (!match.value && lastMatchData?.selection.selected === 0));
  for (const id of ["markets", "history", "xg"])
    document.getElementById(id).disabled = busy;
}
function usageLabel(stats) {
  if (!stats.usage_available) return "";
  if (stats.usage_schema_version !== 2) {
    return " · " + (stats.input_tokens + stats.output_tokens) +
      " tokens rapportés, cache inclus · ancien relevé sans ventilation";
  }
  return " · " + stats.input_tokens + " tokens d’entrée hors cache · " +
    stats.output_tokens + " de sortie · " +
    (stats.cache_usage_complete
      ? stats.cache_read_input_tokens + " lus en cache · " + stats.cache_creation_input_tokens + " mis en cache"
      : "cache : détail indisponible ou incomplet") +
    (stats.usage_calls < stats.model_calls ? " · mesure partielle" : "");
}
function renderTeam(job) {
  trace.hidden = false;
  trace.replaceChildren();
  const title = document.createElement("h3");
  title.textContent =
    job.archived ? "Consultation archivée" : job.status === "completed"
      ? "Consultations terminées"
      : job.status === "error"
        ? "Analyse interrompue"
        : "L’équipe prépare son analyse";
  trace.append(title);
  const scope = document.createElement("p");
  scope.textContent =
    "Périmètre : " +
    (job.scope?.length
      ? job.scope.map((r) => r.match).join(" · ")
      : "Préparation des matchs…");
  trace.append(scope);
  const selection = job.result?.selection || job.selection,
    method = document.createElement("p");
  method.textContent = selection
    ? selection.mode === "manual"
      ? "Match choisi manuellement · critères automatiques conservés dans la trace."
      : "Pré-tri Python : " +
        selection.scanned +
        " rencontres examinées, " +
        selection.eligible +
        " admissibles, " +
        selection.selected +
        " retenues pour les spécialistes."
    : "Règle de sélection absente de cette archive.";
  trace.append(method);
  const list = document.createElement("ul"),
    labels = {
      pending: "En attente",
      running: "En cours",
      completed: "Avis reçu",
      cached: "Avis archivé réutilisé",
      error: "Échec",
    };
  for (const row of job.reviews || []) {
    const li = document.createElement("li");
    li.textContent =
      row.name +
      " · " +
      (labels[row.status] || row.status) +
      (row.status === "cached" ? " · " + row.completed_at : "");
    list.append(li);
    if (row.answer && row.role !== "coach") {
      const details = document.createElement("details"),
        summary = document.createElement("summary"),
        report = document.createElement("div");
      summary.textContent = "Lire l’avis · " + row.name;
      report.append(renderMarkdown(row.answer));
      details.append(summary, report);
      trace.append(details);
    }
    if (row.error) {
      const error = document.createElement("p");
      error.textContent = row.name + " : " + row.error;
      trace.append(error);
    }
  }
  trace.insertBefore(list, trace.children[3] || null);
  const stats = job.result?.stats || job.stats;
  if (stats) {
    const info = document.createElement("p");
    info.textContent =
      (job.archived ? "Consommation lors de l’analyse initiale : " : "") +
      stats.model_calls +
      " appel(s) au modèle · " +
      stats.reused_reports +
      " avis réutilisé(s)" +
      (stats.elapsed_seconds !== undefined
        ? " · " + stats.elapsed_seconds + " s"
        : "") +
      usageLabel(stats);
    trace.append(info);
  }
}
async function pollJob(id) {
  while (true) {
    const job = await getJob(id);
    renderTeam(job);
    const done = (job.reviews || []).filter(
      (r) =>
        r.status === "completed" ||
        r.status === "cached" ||
        r.status === "error",
    ).length;
    status.textContent =
      "Équipe IA · " +
      done +
      "/" +
      (job.reviews?.length || "?") +
      " interventions terminées.";
    if (job.status === "completed") return job.result;
    if (job.status === "error")
      throw Error(job.error || "Analyse interrompue.");
    await new Promise((resolve) => setTimeout(resolve, 1500));
  }
}
function renderDomesticForm(data, chosen) {
  const candidates = chosen
    .map((r) => data.matches.find((m) => m.event_id === r.event_id))
    .filter((r) => r?.domestic_form);
  if (!candidates.length) return;
  const section = document.createElement("details"),
    title = document.createElement("summary");
  title.textContent = "Forme en championnat · données fournies aux analystes";
  section.append(title);
  for (const row of candidates) {
    const heading = document.createElement("h4");
    heading.textContent = row.name;
    section.append(heading);
    for (const side of ["home", "away"]) {
      const form = row.domestic_form[side],
        p = document.createElement("p");
      if (!form.available) {
        p.textContent = form.team + " : " + form.reason;
        section.append(p);
        continue;
      }
      const a = form.last5,
        b = form.last10;
      p.textContent =
        form.team +
        " · " +
        a.played +
        " derniers matchs chargés : " +
        a.wins +
        " V / " +
        a.draws +
        " N / " +
        a.losses +
        " D · buts " +
        a.goals_for +
        " pour / " +
        a.goals_against +
        " contre. Sur " +
        b.played +
        " matchs : " +
        b.wins +
        " V / " +
        b.draws +
        " N / " +
        b.losses +
        " D. Dernier match : " +
        form.latest_kickoff.slice(0, 10) +
        ". " +
        form.warnings.join(" ");
      section.append(p);
      const details = document.createElement("details"),
        label = document.createElement("summary"),
        list = document.createElement("ul");
      label.textContent = "Résultats et sources · " + form.team;
      for (const game of form.matches_newest_first) {
        const li = document.createElement("li");
        li.textContent =
          game.kickoff.slice(0, 10) +
          " · " +
          game.competition +
          " · " +
          (game.venue === "home" ? "domicile" : "extérieur") +
          " contre " +
          game.opponent +
          " : " +
          game.goals_for +
          "–" +
          game.goals_against +
          " · connu le " +
          game.result_known_at.slice(0, 10) +
          " ";
        if (/^https?:\/\//.test(game.source)) {
          const link = document.createElement("a");
          link.href = game.source;
          link.textContent = "Source";
          link.target = "_blank";
          link.rel = "noopener noreferrer";
          li.append(link);
        } else li.append(document.createTextNode(game.source));
        list.append(li);
      }
      details.append(label, list);
      section.append(details);
    }
    const warning = document.createElement("p");
    warning.textContent = row.domestic_form.notice;
    section.append(warning);
  }
  const info = document.createElement("p");
  info.textContent =
    "Le bilan est calculé localement. La lecture des comptes rendus et déclarations sur le contenu des prestations est demandée au journaliste lors de la consultation Équipe IA avec Claude ; elle n’est pas exécutée par cet aperçu.";
  section.append(info);
  preview.append(section);
}

function renderSelection(data) {
  preview.replaceChildren();
  const report = data?.selection;
  if (!report) return;
  const heading = document.createElement("h3");
  heading.textContent = match.value
    ? (manualMode() ? "Matchs choisis manuellement" : "Match choisi manuellement")
    : "Sélection automatique · à approfondir";
  preview.append(heading);
  const intro = document.createElement("p");
  intro.textContent =
    report.scanned +
    " rencontres examinées par Python · " +
    report.calculable +
    " choix calculables · " +
    report.eligible +
    " admissibles au filtre." +
    (match.value
      ? (manualMode() ? " " + manualIds.size + " choisis manuellement." : " Choix manuel.")
      : " " +
        report.selected +
        " proposés sur " +
        report.requested +
        " demandés.");
  preview.append(intro);
  const chosen = report.rows.filter((r) =>
      manualMode() ? manualIds.has(r.event_id) : match.value ? r.event_id === match.value : r.selected,
    ),
    table = document.createElement("table"),
    head = document.createElement("tr");
  for (const text of [
    "Match",
    "Choix Python",
    "Probabilité",
    "Matchs récents",
    "Cotes du choix",
  ]) {
    const cell = document.createElement("th");
    cell.textContent = text;
    head.append(cell);
  }
  table.append(head);
  for (const row of chosen) {
    const tr = document.createElement("tr");
    for (const value of [
      row.match,
      { home: "1", draw: "N", away: "2" }[row.model_pick] || "Indisponible",
      row.pick_probability === null
        ? "—"
        : (100 * row.pick_probability).toFixed(1) + " %",
      row.recent_home === null || row.recent_home === undefined
        ? "—"
        : row.recent_home + " / " + row.recent_away,
      row.prices?.length
        ? row.prices
            .map((p) => p.bookmaker + " " + p.odds.toFixed(2))
            .join(" · ")
        : "Indisponibles",
    ]) {
      const cell = document.createElement("td");
      cell.textContent = value;
      tr.append(cell);
    }
    table.append(tr);
  }
  preview.append(table);
  if (!chosen.length) {
    const empty = document.createElement("p");
    empty.textContent =
      manualMode() ? "Cochez les matchs que vous souhaitez approfondir." : "Aucun match ne satisfait ce filtre. Les premiers matchs ne sont pas ajoutés pour remplir la liste ; un choix manuel reste possible.";
    preview.append(empty);
  }
  const rule = document.createElement("p");
  rule.textContent =
    "Filtre : probabilité ≥ " +
    (100 * report.criteria.min_pick_probability).toFixed(0) +
    " %, écart ≥ " +
    (100 * report.criteria.min_probability_gap).toFixed(0) +
    " points, au moins " +
    report.criteria.min_recent_matches_per_team +
    " matchs par équipe sur deux ans et dernier match historique dans les " +
    report.criteria.max_team_history_age_days +
    " derniers jours. Tri par probabilité du modèle, puis écart et échantillon récent.";
  preview.append(rule);
  const limits = document.createElement("p");
  limits.textContent = report.notice;
  preview.append(limits);
  const details = document.createElement("details"),
    summary = document.createElement("summary"),
    list = document.createElement("ul");
  summary.textContent = "Pourquoi ces matchs et pas les autres ?";
  for (const row of report.rows) {
    const li = document.createElement("li");
    li.textContent =
      row.match +
      " : " +
      (row.exclusions.length
        ? row.exclusions.join(" · ")
        : "Rang " +
          row.rank +
          " · " +
          (row.selection_reason || "admissible, rang inférieur") +
          (row.selected
            ? ""
            : " · non retenu dans les " + report.requested + " premiers"));
    list.append(li);
  }
  details.append(summary, list);
  preview.append(details);
  renderDomesticForm(data, chosen);
  if (match.value) {
    for (const row of chosen.filter(r => r.exclusions.length)) {
      const warning = document.createElement("p");
      warning.textContent = row.match + " · Hors filtre automatique : " + row.exclusions.join(" · ");
      preview.append(warning);
    }
  }
  updateControls();
}
async function loadMatches() {
  const serial = ++matchLoad,
    previous = initialEvent || match.value;
  initialEvent = "";
  syncBackLink();
  matchesLoading = true;
  updateControls();
  try {
    const data = await jsonResponse(
      await fetch(
        "/api/chat/matches?league=" +
          encodeURIComponent(league.value) +
          "&period=" +
          period.value +
          "&count=" +
          selectionCount.value,
      ),
    );
    if (serial !== matchLoad) return;
    lastMatchData = data;
    match.replaceChildren();
    const all = document.createElement("option");
    all.value = "";
    all.textContent = "Sélection automatique classée";
    match.append(all);
    const manual = document.createElement("option");
    manual.value = "manual";
    manual.textContent = "Choisir plusieurs matchs";
    match.append(manual);
    for (const row of data.matches) {
      const opt = document.createElement("option");
      opt.value = row.event_id;
      opt.textContent = row.name;
      match.append(opt);
    }
    if (previous === "manual" || data.matches.some((r) => r.event_id === previous))
      match.value = previous;
    renderManualMatches(data);
    matchesLoading = false;
    renderSelection(data);
  } catch (e) {
    if (serial === matchLoad) {
      lastMatchData = null;
      matchesLoading = false;
      preview.textContent = "Sélection indisponible : " + e.message;
      status.textContent = e.message;
      updateControls();
    }
  }
}
const archivePanel = document.getElementById("analysis-history");
let archiveOffset = 0, archiveSerial = 0;
function archiveDate(value) {
  return value ? new Date(value).toLocaleString("fr-FR", {dateStyle: "medium", timeStyle: "short"}) : "Date indisponible";
}
async function loadArchivedReviews(reset = false) {
  if (reset) archiveOffset = 0;
  const serial = ++archiveSerial;
  const info = document.getElementById("history-status");
  info.textContent = "Lecture des analyses enregistrées…";
  try {
    const query = new URLSearchParams({q: document.getElementById("history-query").value, offset: archiveOffset, limit: 5});
    const data = await jsonResponse(await fetch("/api/chat/analyses?" + query, {headers: {"X-Prono-Token": token}}));
    if (serial !== archiveSerial) return;
    const list = document.getElementById("history-list");
    list.replaceChildren();
    for (const row of data.analyses) {
      const entry = document.createElement("article"), text = document.createElement("div"),
        title = document.createElement("strong"), date = document.createElement("small"), button = document.createElement("button");
      entry.className = "history-entry";
      title.textContent = row.scope.map(r => r.match).join(" · ") || "Consultation";
      date.textContent = archiveDate(row.created_at) + " · " + (row.provider === "claude" ? "Claude" : "Coach local") +
        (row.status === "error" ? " · analyse interrompue" : "");
      button.type = "button";
      button.textContent = "Ouvrir l’analyse";
      button.onclick = () => openArchivedReview(row.run_id);
      text.append(title, date); entry.append(text, button); list.append(entry);
    }
    info.textContent = data.total ? (archiveOffset + 1) + "–" + (archiveOffset + data.analyses.length) + " sur " + data.total + " analyse(s)" : "Aucune analyse enregistrée pour cette recherche.";
    if (data.skipped) info.textContent += " · " + data.skipped + " archive(s) illisible(s) ou incomplète(s).";
    document.getElementById("history-prev").hidden = archiveOffset === 0;
    document.getElementById("history-next").hidden = archiveOffset + data.analyses.length >= data.total;
  } catch (error) {
    if (serial === archiveSerial) info.textContent = error.message;
  }
}
async function openArchivedReview(id) {
  if (busy) return;
  busy = true;
  updateControls();
  try {
    const job = await jsonResponse(await fetch("/api/chat/analyses/" + encodeURIComponent(id), {headers: {"X-Prono-Token": token}}));
    if (["claude", "local"].includes(job.provider)) provider.value = job.provider;
    document.getElementById("model-label").hidden = provider.value === "claude";
    document.getElementById("messages").replaceChildren();
    histories[provider.value] = [];
    bubble("assistant", "Analyse archivée du " + archiveDate(job.created_at) + " · données et avis de cette date, aucune nouvelle recherche.");
    if (job.question) {
      bubble("user", job.question);
      histories[provider.value].push({role: "user", content: job.question});
    }
    renderTeam(job);
    if (job.result) {
      bubble("assistant", job.result.answer);
      histories[provider.value].push({role: "assistant", content: job.result.answer});
    } else bubble("assistant", "Analyse interrompue : " + (job.error || "verdict indisponible."));
    lastRuns[provider.value] = id;
    sessionStorage.setItem("prono-team-" + provider.value, id);
    const url = new URL(location.href);
    url.searchParams.set("analysis", id);
    window.history.replaceState(null, "", url);
    status.textContent = "Analyse archivée ouverte · aucun appel au modèle.";
    document.getElementById("messages").scrollIntoView({block: "start", behavior: "smooth"});
  } catch (error) { status.textContent = error.message; }
  finally { busy = false; updateControls(); }
}
archivePanel.addEventListener("toggle", () => { if (archivePanel.open) loadArchivedReviews(); });
document.getElementById("history-search").addEventListener("submit", event => { event.preventDefault(); loadArchivedReviews(true); });
document.getElementById("history-prev").onclick = () => { archiveOffset = Math.max(0, archiveOffset - 5); loadArchivedReviews(); };
document.getElementById("history-next").onclick = () => { archiveOffset += 5; loadArchivedReviews(); };
function selectCoach(restorePrevious = true) {
  document.getElementById("model-label").hidden = provider.value === "claude";
  document.getElementById("messages").replaceChildren();
  trace.hidden = true;
  const history = histories[provider.value];
  for (const row of history) bubble(row.role, row.content);
  if (!history.length)
    bubble(
      "assistant",
      provider.value === "claude"
        ? "Choisis un match et lance l’équipe IA pour consulter les spécialistes, ou pose une question au coach."
        : "Le coach local et ses spécialistes utilisent les données chargées. La recherche web nécessite Claude.",
    );
  status.textContent =
    provider.value === "claude"
      ? options?.claude.message || "Vérification de Claude…"
      : options?.models.length
        ? "Coach local prêt."
        : "Démarrez Ollama avec un modèle local.";
  updateControls();
  if (restorePrevious !== false && lastRuns[provider.value]) restoreRun(lastRuns[provider.value]);
}
async function restoreRun(id) {
  busy = true;
  updateControls();
  try {
    const job = await getJob(id);
    renderTeam(job);
    const result =
      job.status === "queued" || job.status === "running"
        ? await pollJob(id)
        : job.status === "completed"
          ? job.result
          : null;
    if (
      result &&
      !histories[provider.value].some(
        (r) => r.role === "assistant" && r.content === result.answer,
      )
    ) {
      bubble("assistant", result.answer);
      histories[provider.value].push({
        role: "assistant",
        content: result.answer,
      });
      status.textContent =
        "Consultation archivée retrouvée · aucune nouvelle recherche.";
    }
  } catch (e) {
    status.textContent = e.message;
  } finally {
    busy = false;
    updateControls();
  }
}
fetch("/api/chat/options")
  .then((r) => jsonResponse(r))
  .then((data) => {
    options = data;
    selectionCount.value = String(data.selection_default_count || 3);
    model.replaceChildren();
    for (const name of data.models) {
      const opt = document.createElement("option");
      opt.value = opt.textContent = name;
      model.append(opt);
    }
    if (!data.models.length) {
      const opt = document.createElement("option");
      opt.textContent = "Démarrer Ollama avec un modèle local";
      model.append(opt);
    }
    for (const row of data.leagues) {
      const opt = document.createElement("option");
      opt.value = row.code;
      opt.textContent = row.name;
      league.append(opt);
    }
    if (data.leagues.some((r) => r.code === initialParams.get("league")))
      league.value = initialParams.get("league");
    if (["today", "next3"].includes(initialParams.get("period")))
      period.value = initialParams.get("period");
    selectCoach(!initialParams.has("analysis"));
    if (initialParams.has("analysis")) openArchivedReview(initialParams.get("analysis"));
    if (!available()) document.getElementById("coach-settings").open = true;
    loadMatches();
  })
  .catch((e) => {
    status.textContent = e.message;
    updateControls();
  });
provider.onchange = selectCoach;
league.onchange = loadMatches;
period.onchange = loadMatches;
selectionCount.onchange = loadMatches;
match.onchange = () => renderSelection(lastMatchData);
updateControls();
document.getElementById("chat").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (busy || !available()) return;
  const input = document.getElementById("question"),
    text = input.value.trim();
  if (!text) return;
  busy = true;
  updateControls();
  input.value = "";
  bubble("user", text);
  status.textContent =
    mode.value === "team"
      ? "Consultation de l’équipe IA…"
      : "Le coach prépare sa réponse…";
  const history = histories[provider.value];
  try {
    let data = await post("/api/chat", {
      message: text,
      provider: provider.value,
      model: model.value,
      league: league.value,
      period: period.value,
      mode: mode.value,
      strategy: strategy.value,
      force_refresh: force.checked,
      selection_count: Number(selectionCount.value),
      event_id: manualMode() ? "" : match.value,
      event_ids: manualMode() ? [...manualIds] : null,
      history: history.slice(-12),
      last_team_run: lastRuns[provider.value],
    });
    if (data.job_id) {
      lastRuns[provider.value] = data.job_id;
      sessionStorage.setItem("prono-team-" + provider.value, data.job_id);
      data = await pollJob(data.job_id);
    }
    bubble("assistant", data.answer);
    history.push(
      { role: "user", content: text },
      { role: "assistant", content: data.answer },
    );
    status.textContent = data.run_id
      ? "Synthèse de l’équipe reçue · avis archivés et consultables ci-dessus."
      : "Réponse de " +
        data.model +
        " · vérifier les chiffres dans le dashboard.";
    if (data.run_id && archivePanel.open) loadArchivedReviews(true);
  } catch (err) {
    status.textContent = err.message;
  } finally {
    busy = false;
    mode.value = "coach";
    updateControls();
  }
});
async function refresh(action) {
  if (busy) return;
  busy = true;
  updateControls();
  status.textContent = "Mise à jour demandée en cours…";
  try {
    const data = await post("/api/refresh", { action, league: league.value });
    bubble("assistant", data.message);
    await loadMatches();
    status.textContent = "Mise à jour terminée.";
  } catch (err) {
    status.textContent = err.message;
  } finally {
    busy = false;
    updateControls();
  }
}
document.getElementById("markets").onclick = () => refresh("markets");
document.getElementById("history").onclick = () => refresh("history");
document.getElementById("xg").onclick = () => refresh("xg");
document.getElementById("pronos").onclick = () =>
  (location.href =
    "/?tab=pronos&league=" +
    encodeURIComponent(league.value) +
    "&horizon=" +
    period.value);
document.getElementById("prepare").onclick = () => {
  mode.value = "team";
  force.checked = true;
  document.getElementById("question").value =
    "Analyse les matchs choisis avec l’équipe sélectionnée. Le journaliste vérifie les nouvelles, effectifs et dernières prestations ; l’analyste sportif évalue le match sans les prévisions du modèle ; le coach tranche. Commence par le tableau des verdicts, puis une raison décisive et une réserve par match. Formule un avis indépendant à partir des faits sportifs, cite les sources décisives et signale les informations manquantes. Aucun renfort spécialisé supplémentaire sauf demande précise ou choix de l’équipe complète.";
  document.getElementById("chat").requestSubmit();
};
