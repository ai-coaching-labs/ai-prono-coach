(() => {
  const panel = document.getElementById('combo-preparation');
  if (!panel) return;
  const progress = document.getElementById('combo-progress');
  const button = document.getElementById('combo-analyze');
  const token = document.querySelector('main').dataset.token;
  const scope = {league: panel.dataset.league, period: panel.dataset.period,
    quote_mode: panel.dataset.quoteMode};
  const storageKey = 'prono-combo-job-' + scope.league + '-' + scope.period + '-' + scope.quote_mode;
  let busy = false;
  const chosenKey = storageKey + '-matches';
  const cards = [...panel.querySelectorAll('.combo-match')];
  const selectionMode = document.getElementById('combo-selection-mode');
  try {
    const remembered = JSON.parse(sessionStorage.getItem(chosenKey) || 'null');
    if (remembered?.mode === 'manual' && Array.isArray(remembered.ids)) {
      selectionMode.value = 'manual';
      for (const card of cards) card.querySelector('.combo-choice').checked = remembered.ids.includes(card.dataset.eventId);
    }
  } catch (_) { sessionStorage.removeItem(chosenKey); }
  function chosenIds() {
    return cards.filter(c => selectionMode.value === 'auto' ? c.dataset.autoSelected === 'true' : c.querySelector('.combo-choice').checked).map(c => c.dataset.eventId);
  }
  for (const card of cards) card.querySelector('.combo-choice').addEventListener('change', () => {
    sessionStorage.setItem(chosenKey, JSON.stringify({mode: selectionMode.value, ids: chosenIds()}));
  });
  function updateSelection() {
    const auto = selectionMode.value === 'auto';
    for (const card of cards) {
      card.querySelector('.combo-choice').disabled = auto || busy;
      if (auto) card.querySelector('.combo-choice').checked = card.dataset.autoSelected === 'true';
    }
    button.textContent = auto ? 'Analyser la sélection automatique avec Claude' : 'Analyser mes matchs avec Claude';
    sessionStorage.setItem(chosenKey, JSON.stringify({mode: selectionMode.value, ids: chosenIds()}));
  }
  selectionMode.addEventListener('change', updateSelection);
  updateSelection();
  document.getElementById('combo-budget').addEventListener('submit', event => {
    const ids = chosenIds();
    if (ids.length < 2 || ids.length > 15) {
      event.preventDefault();
      progress.textContent = 'Choisis de deux à quinze matchs pour construire les tickets.';
      progress.scrollIntoView({block: 'center'});
      return;
    }
    document.getElementById('combo-event-ids').value = JSON.stringify(ids);
  });
  const delay = () => new Promise(resolve => setTimeout(resolve, 1500));
  async function json(url, body) {
    const response = await fetch(url, {
      method: body ? 'POST' : 'GET',
      headers: {'Content-Type': 'application/json', 'X-Prono-Token': token},
      ...(body ? {body: JSON.stringify(body)} : {})
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || 'La demande n’a pas abouti. Réessaye.');
    return data;
  }
  function setBusy(value) {
    busy = value;
    button.disabled = value;
    for (const el of panel.querySelectorAll('.combo-choice, .combo-quote input, .combo-quote button'))
      el.disabled = value;
    selectionMode.disabled = value;
    if (!value) updateSelection();
  }
  async function save(card) {
    const form = card.querySelector('.combo-quote');
    if (!form.reportValidity()) {
      card.querySelector('details').open = true;
      form.reportValidity();
      throw new Error('Renseigne les cotes, leur heure réelle et la source pour ce match.');
    }
    const fields = new FormData(form);
    const quoted = new Date(fields.get('quoted_at'));
    if (Number.isNaN(quoted.getTime())) throw new Error('Heure de cotation invalide.');
    await json('/api/accumulators/quote', {
      ...scope, division: card.dataset.division, event_id: card.dataset.eventId,
      kickoff: card.dataset.kickoff, bookmaker: fields.get('bookmaker'),
      source_url: fields.get('source_url'), quoted_at: quoted.toISOString(),
      odds: Object.fromEntries(['home', 'draw', 'away'].map(k => [k, Number(fields.get(k))]))
    });
    card.dataset.quoteReady = 'true';
    form.dataset.dirty = 'false';
  }
  for (const card of cards) {
    const form = card.querySelector('.combo-quote');
    form.addEventListener('input', () => {form.dataset.dirty = 'true';});
    form.addEventListener('submit', async event => {
      event.preventDefault();
      if (busy) return;
      try {
        await save(card);
        progress.textContent = 'Cotes enregistrées, ancienne capture conservée. Tu peux lancer l’équipe.';
      } catch (error) { progress.textContent = error.message; }
    });
  }
  async function poll(jobId) {
    setBusy(true);
    try {
      while (true) {
        const job = await json('/api/chat/jobs/' + encodeURIComponent(jobId));
        if (job.status === 'error') throw new Error(job.error || 'La consultation a échoué.');
        if (job.status === 'completed') {
          sessionStorage.setItem(storageKey, JSON.stringify({job_id: jobId, completed: true,
            answer: job.result?.answer || ''}));
          const url = new URL(location.href);
          url.searchParams.delete('budget');
          url.searchParams.set('prepared', jobId);
          url.hash = 'combo-progress';
          if (url.href === location.href) location.reload();
          else location.replace(url.href);
          return;
        }
        const active = (job.reviews || []).filter(r => r.status === 'running').map(r => r.name || r.role);
        progress.textContent = 'Consultation en cours' + (active.length ? ' : ' + active.join(', ') : '…') +
          ' Les avis seront archivés automatiquement.';
        await delay();
      }
    } catch (error) {
      sessionStorage.removeItem(storageKey);
      progress.textContent = error.message + ' Tu peux réessayer ; aucune mise n’a été créée.';
      setBusy(false);
    }
  }
  button.addEventListener('click', async () => {
    if (busy) return;
    const ids = chosenIds();
    const selected = cards.filter(card => ids.includes(card.dataset.eventId));
    if (selected.length < 2 || selected.length > 15) {
      progress.textContent = selectionMode.value === 'auto' ? 'Moins de deux matchs compatibles en automatique. Essaie une autre période ou compétition.' : 'Choisis de deux à quinze matchs.';
      return;
    }
    // Les cotes ne sont enregistrées que sur une action explicite de l’utilisateur.
    try {
      for (const card of selected) {
        if (card.dataset.quoteReady !== 'true' || card.querySelector('form').dataset.dirty === 'true')
          await save(card);
      }
      setBusy(true);
      progress.textContent = 'Démarrage de Claude et de l’équipe…';
      const data = await json('/api/accumulators/prepare', {
        ...scope, selection_mode: selectionMode.value, event_ids: selected.map(card => card.dataset.eventId)
      });
      sessionStorage.setItem(storageKey, JSON.stringify({job_id: data.job_id}));
      await poll(data.job_id);
    } catch (error) {
      progress.textContent = error.message;
      setBusy(false);
    }
  });
  try {
    const job = JSON.parse(sessionStorage.getItem(storageKey) || 'null');
    if (job?.completed) {
      progress.textContent = panel.dataset.ready === 'true' ?
        'L’équipe a terminé. Choisis maintenant ton budget fictif ci-dessous.' :
        'L’équipe a terminé. Aucun combiné admissible pour le moment : consulte ses verdicts et réserves ci-dessous.';
      document.getElementById('combo-verdict').hidden = false;
      document.getElementById('combo-answer').textContent = job.answer;
    } else if (job?.job_id) poll(job.job_id);
  } catch (_) { sessionStorage.removeItem(storageKey); }
  if (cards.length < 2) {
    button.disabled = true;
    progress.textContent = 'Moins de deux matchs exploitables. Choisis une autre période ou compétition ; les exclusions sont indiquées ci-dessus.';
  }
})();
