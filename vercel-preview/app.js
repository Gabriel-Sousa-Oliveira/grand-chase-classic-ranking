const candidates = [
  { character: "Ronan", nick: "Syntaxii", time: "01:01", video: "CvAo55yFntg", accent: "#59e1d9" },
  { character: "Sieghart", nick: "user000", time: "01:11", video: "V-7UZzmpQO4", accent: "#ffbd59" },
  { character: "Iris", nick: "Borkaz", time: "01:18", video: "tQ1pSPCFnlQ", accent: "#9b8cff" },
  { character: "Rin / Lin", nick: "Borkaz", time: "01:21", video: "tt4-bEt6Zps", accent: "#67d48b" },
  { character: "Ereb", nick: "Borkaz", time: "01:32", video: "WZeUJAw4pmU", accent: "#ff7b90" },
  { character: "Lass", nick: "Choco", time: "01:36", video: "GdikH5OH_sM", accent: "#62a4ff" },
  { character: "Asin", nick: "Grunkar Totohondry", time: "02:56", video: "SXpJZhQ3h2k", accent: "#ff8b66" }
];

document.querySelector("#boards").innerHTML = candidates.map((run, index) => `
  <article class="board" style="--accent:${run.accent}">
    <div class="character"><small>PERSONAGEM</small><h3>${run.character}</h3><span>Candidato #${index + 1}</span></div>
    <a class="run" href="https://youtu.be/${run.video}" target="_blank" rel="noreferrer" aria-label="Assistir run de ${run.character} no YouTube">
      <span class="position">#1</span>
      <span class="runner"><strong>${run.nick}</strong><small>Aguardando validação</small></span>
      <time>${run.time}</time>
      <span class="play">▶</span>
    </a>
    <div class="open"><span>#2</span><p><strong>Vaga aberta</strong><small>Aguardando nova run válida</small></p><time>—</time></div>
    <div class="open"><span>#3</span><p><strong>Vaga aberta</strong><small>Aguardando nova run válida</small></p><time>—</time></div>
    <div class="open"><span>#4</span><p><strong>Vaga aberta</strong><small>Aguardando nova run válida</small></p><time>—</time></div>
  </article>`).join("");
