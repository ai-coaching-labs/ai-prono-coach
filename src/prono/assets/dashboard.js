const main = document.querySelector("main"),
  token = main?.dataset.token,
  labStatus = document.getElementById("lab-status");
async function labJson(response) {
  const data = await response.json();
  if (!response.ok) throw Error(data.error || "Demande refusée.");
  return data;
}
function labBusy(busy) {
  for (const id of ["evaluate", "track-capture", "track-results"]) {
    const el = document.getElementById(id);
    if (el) el.disabled = busy;
  }
}
async function labAction(url, data) {
  labBusy(true);
  labStatus.textContent = "Calcul en cours…";
  try {
    const result = await labJson(
      await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Prono-Token": token },
        body: JSON.stringify(data),
      }),
    );
    if (url === "/api/evaluation") {
      while (true) {
        const job = await labJson(
          await fetch("/api/evaluation", {
            headers: { "X-Prono-Token": token },
          }),
        );
        labStatus.textContent =
          "Comparaison en cours · " + (job.current_league || "préparation");
        if (job.status === "completed") break;
        if (job.status === "error") throw Error(job.error);
        await new Promise((r) => setTimeout(r, 1000));
      }
    }
    location.reload();
  } catch (e) {
    labStatus.textContent = e.message;
    labBusy(false);
  }
}
document
  .getElementById("track-capture")
  ?.addEventListener("click", () =>
    labAction("/api/tracking", { action: "capture" }),
  );
document
  .getElementById("track-results")
  ?.addEventListener("click", () =>
    labAction("/api/tracking", { action: "results" }),
  );
document
  .getElementById("evaluate")
  ?.addEventListener("click", () =>
    labAction("/api/evaluation", {
      league: new URLSearchParams(location.search).get("league") || "all",
      mode: document.getElementById("evaluation-mode").value,
    }),
  );
