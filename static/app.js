const socket = io();
const $ = (id) => document.getElementById(id);
let gameState = null;
let myHand = {function: [], x: [], y: []};
let selected = {function: null, x: null, y: null};
let myToken = localStorage.getItem("parabola_token") || "";
let savedCode = localStorage.getItem("parabola_room") || "";
let toastTimer;
let lastAnimatedPlay = 0;
let animationFrame = null;
let previousHandSize = 0;

function toast(message) {
  $("toast").textContent = message;
  $("toast").classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $("toast").classList.remove("show"), 2400);
}

function identityPayload() {
  return {name: $("nickname").value.trim(), code: $("invite-code").value.trim().toUpperCase(), token: myToken};
}

function enterGame() {
  $("entry-view").classList.add("hidden");
  $("game-view").classList.remove("hidden");
}

function escapeHtml(value) {
  const node = document.createElement("div");
  node.textContent = value;
  return node.innerHTML;
}

function renderPlayers(state) {
  $("player-count").textContent = `${state.players.length} / 4`;
  $("players").innerHTML = state.players.map((player, index) => {
    const tags = [player.token === state.hostToken ? "방장" : "", player.token === myToken ? "나" : "", !player.connected ? "재접속 대기" : ""].filter(Boolean).join(" · ");
    const orderText = player.orderNumber == null ? "" : `<span class="order-number">${player.orderNumber}</span>`;
    const gameMeta = state.status === "dealing"
      ? `<span class="player-score">${player.cardsDrawn}<small>/ 15장</small></span>`
      : state.status === "playing" ? `<span class="player-score">${player.score}<small>${player.cardsRemaining}턴</small></span>` : `<span class="player-score">${player.score}</span>`;
    return `<div class="player ${player.token === state.turnToken ? "active" : ""}">
      <span class="player-dot" style="background:${player.color}"></span>
      <span class="player-name">${escapeHtml(player.name)}<small>${tags || `${index + 1}번 플레이어`}</small></span>
      ${state.status === "ordering" ? orderText || '<span class="order-wait">대기</span>' : gameMeta}
    </div>`;
  }).join("");
}

function renderHand() {
  const isMyTurn = gameState?.status === "playing" && gameState.turnToken === myToken;
  const isDealing = gameState?.status === "dealing";
  for (const category of ["function", "x", "y"]) {
    const container = $(`${category}-hand`);
    const cards = myHand[category] || [];
    if (!cards.length) {
      container.innerHTML = `<span class="no-cards">${isDealing ? "위 카드 더미에서 뽑으세요" : gameState?.status === "playing" ? "사용 완료" : "게임 시작 후 공개"}</span>`;
      continue;
    }
    container.innerHTML = cards.map((card, index) => `<button type="button" class="hand-card ${selected[category] === card.id ? "selected" : ""}" data-category="${category}" data-card-id="${card.id}" ${isMyTurn ? "" : "disabled"} style="--deal-index:${index}">${escapeHtml(card.label)}</button>`).join("");
  }
  const ready = isMyTurn && selected.function && selected.x && selected.y;
  $("deck-area").classList.toggle("hidden", !isDealing);
  $("hand").classList.toggle("drawing-hand", isDealing);
  $("play-button").classList.toggle("hidden", isDealing);
  for (const category of ["function", "x", "y"]) {
    const count = myHand[category]?.length || 0;
    $(`${category}-draw-count`).textContent = `${count} / 5`;
    const button = document.querySelector(`.deck-button[data-category="${category}"]`);
    button.disabled = !isDealing || count >= 5;
    button.classList.toggle("complete", count >= 5);
  }
  const totalDrawn = ["function", "x", "y"].reduce((total, category) => total + (myHand[category]?.length || 0), 0);
  $("draw-progress-bar").style.width = `${totalDrawn / 15 * 100}%`;
  $("play-button").disabled = !ready;
  $("play-button").textContent = isMyTurn ? ready ? "선택한 카드 배치" : "카드 3장을 선택하세요" : "상대 차례 기다리는 중";
}

function showCardReveal(category, cards) {
  const names = {function: "함수 카드", x: "x축 이동 카드", y: "y축 이동 카드"};
  const symbols = {function: "ƒ", x: "X", y: "Y"};
  const positions = [-168, -84, 0, 84, 168];
  const angles = [-14, -7, 0, 7, 14];
  $("reveal-title").textContent = `${names[category]} 5장`;
  $("reveal-cards").innerHTML = cards.map((card, index) => `
    <article class="reveal-card reveal-${category}" style="--x:${positions[index]}px;--angle:${angles[index]}deg;--delay:${index * 110}ms;--z:${index + 1}">
      <span>${symbols[category]}</span>
      <strong>${escapeHtml(card.label)}</strong>
      <small>PARABOLA</small>
    </article>`).join("");
  $("reveal-close").disabled = true;
  $("card-reveal").classList.remove("hidden");
  setTimeout(() => {
    $("reveal-close").disabled = false;
    $("reveal-close").focus();
  }, 1550);
}

function render(state) {
  const newPlay = state.lastPlay?.playNumber || 0;
  const shouldAnimate = newPlay > lastAnimatedPlay;
  gameState = state;
  enterGame();
  $("room-code").textContent = state.testMode ? "TEST MODE" : state.code;
  $("copy-code").classList.toggle("hidden", state.testMode);
  renderPlayers(state);
  $("round-label").textContent = `ROUND ${state.round}`;
  $("turn-progress").textContent = `${state.turnsPlayed} / ${state.totalTurns}턴`;

  const isHost = myToken === state.hostToken;
  const canBeginOrdering = isHost && state.status === "lobby";
  const canStartGame = isHost && state.status === "ordering" && state.orderReady;
  $("start-button").classList.toggle("hidden", !canBeginOrdering && !canStartGame);
  $("start-button").disabled = canBeginOrdering && state.players.length < 3;
  $("start-button").textContent = canStartGame ? "이 순서로 게임 시작" : "순서 정하기 시작";
  const me = state.players.find((player) => player.token === myToken);
  const canDrawOrder = state.status === "ordering" && me?.orderNumber == null;
  $("order-button").classList.toggle("hidden", !canDrawOrder);
  $("lobby-help").classList.toggle("hidden", !["lobby", "ordering"].includes(state.status));
  $("lobby-help").textContent = state.status === "ordering"
    ? state.orderReady ? "숫자가 큰 순서대로 정렬됐어요. 방장이 게임을 시작할 수 있습니다." : "각자 순서 숫자를 뽑아 주세요. 큰 숫자부터 먼저 플레이합니다."
    : "3명이 모이면 방장이 순서 정하기를 시작할 수 있어요.";

  const current = state.players.find((player) => player.token === state.turnToken);
  const isMyTurn = state.status === "playing" && state.turnToken === myToken;
  $("phase-label").textContent = state.status === "lobby" ? "대기실" : state.status === "ordering" ? "순서 정하기" : state.status === "dealing" ? "카드 준비" : state.status === "finished" ? "게임 종료" : `ROUND ${state.round}`;
  $("turn-label").textContent = state.status === "lobby" ? "플레이어를 기다리는 중" : state.status === "ordering" ? state.orderReady ? "플레이 순서 확정" : "순서 숫자를 뽑는 중" : state.status === "dealing" ? "카드를 종류별로 5장씩 뽑으세요" : state.status === "finished" ? "최종 점수 집계 완료" : `${current?.name || ""}의 차례`;
  $("action-hint").textContent = isMyTurn ? "함수·x축·y축 카드에서 각각 한 장을 고르세요." : state.status === "playing" ? `${current?.name || "다른 플레이어"}님이 카드를 고르는 중이에요.` : state.status === "dealing" ? "모든 플레이어가 15장을 뽑으면 자동으로 게임이 시작됩니다." : state.status === "ordering" ? "모든 플레이어가 숫자를 뽑으면 순서가 확정됩니다." : "게임 시작 전 직접 카드를 뽑습니다.";
  $("board-overlay").classList.toggle("hidden", !["lobby", "ordering", "dealing"].includes(state.status));
  if (state.status === "ordering") {
    $("board-overlay").querySelector("strong").textContent = state.orderReady ? "플레이 순서가 정해졌어요" : "순서 숫자를 뽑는 중";
    $("board-overlay").querySelector("span").textContent = state.orderReady ? "숫자가 큰 플레이어부터 시작합니다." : "왼쪽의 버튼을 눌러 내 숫자를 확인하세요.";
  } else if (state.status === "dealing") {
    const readyPlayers = state.players.filter((player) => player.cardsDrawn === 15).length;
    $("board-overlay").querySelector("strong").textContent = state.testMode ? "1인 테스트 카드 준비" : "카드를 직접 뽑아 주세요";
    $("board-overlay").querySelector("span").textContent = `${readyPlayers} / ${state.players.length}명 준비 완료`;
  } else if (state.status === "lobby") {
    $("board-overlay").querySelector("strong").textContent = "파티원을 기다리고 있어요";
    $("board-overlay").querySelector("span").textContent = "초대 코드를 친구에게 공유하세요.";
  }

  if (state.lastPlay) {
    $("equation").textContent = state.lastPlay.equation;
    const bombText = state.lastPlay.bombs.length ? ` · 폭탄 ${state.lastPlay.bombs.length}개 폭발, ${state.lastPlay.deleted}칸 소멸` : "";
    $("capture-result").textContent = `${state.lastPlay.cells.length}칸 통과 · 상대 영역 ${state.lastPlay.captured}칸 탈취${bombText}`;
  }
  renderHand();
  if (shouldAnimate) {
    lastAnimatedPlay = newPlay;
    animateBoard(state);
  } else {
    drawBoard(state, 1);
  }
  if (state.status === "finished") showResult(state);
}

function renderBoardBase(ctx, canvas, state, pulse = 1) {
  const min = state.settings.boardMin;
  const max = state.settings.boardMax;
  const count = max - min;
  const cell = canvas.width / count;
  const players = Object.fromEntries(state.players.map((player) => [player.token, player]));
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#0b0f17";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  for (const [key, token] of Object.entries(state.board)) {
    const [x, y] = key.split(",").map(Number);
    ctx.globalAlpha = .48 + .12 * pulse;
    ctx.fillStyle = players[token]?.color || "#555";
    ctx.fillRect((x - min) * cell + 1, (max - (y + 1)) * cell + 1, cell - 2, cell - 2);
  }
  ctx.globalAlpha = 1;
  for (let i = 0; i <= count; i++) {
    const pos = Math.round(i * cell) + .5;
    const coordinate = min + i;
    ctx.beginPath();
    ctx.strokeStyle = coordinate === 0 ? "#778096" : "#242b3a";
    ctx.lineWidth = coordinate === 0 ? 1.8 : 1;
    ctx.moveTo(pos, 0); ctx.lineTo(pos, canvas.height); ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(0, pos); ctx.lineTo(canvas.width, pos); ctx.stroke();
  }
  ctx.fillStyle = "#858da1";
  ctx.font = "18px ui-monospace, monospace";
  ctx.fillText("x", canvas.width - 20, canvas.height / 2 - 9);
  ctx.fillText("y", canvas.width / 2 + 9, 20);
  return {min, max, cell};
}

function drawBoard(state, progress = 1) {
  const canvas = $("board");
  const ctx = canvas.getContext("2d");
  const {min, max, cell} = renderBoardBase(ctx, canvas, state, Math.sin(progress * Math.PI));
  if (!state.lastPlay) return;
  const {a, h, k, color, bombs} = state.lastPlay;
  ctx.beginPath();
  ctx.strokeStyle = color;
  ctx.lineWidth = 4;
  ctx.shadowColor = color;
  ctx.shadowBlur = 10;
  let started = false;
  const endX = canvas.width * Math.min(1, progress / .7);
  for (let px = 0; px <= endX; px += 1) {
    const x = min + px / cell;
    const y = a * (x - h) ** 2 + k;
    const py = (max - y) * cell;
    if (py >= -10 && py <= canvas.height + 10) {
      if (!started) { ctx.moveTo(px, py); started = true; } else ctx.lineTo(px, py);
    } else if (started) {
      ctx.stroke(); ctx.beginPath(); started = false;
    }
  }
  ctx.stroke();
  ctx.shadowBlur = 0;

  if (bombs.length && progress > .58) {
    const blastProgress = Math.min(1, (progress - .58) / .42);
    for (const bomb of bombs) {
      const cx = (bomb.x - min + .5) * cell;
      const cy = (max - bomb.y - .5) * cell;
      const radius = cell * (state.settings.bombRadius + .5) * blastProgress;
      const gradient = ctx.createRadialGradient(cx, cy, 0, cx, cy, Math.max(1, radius));
      gradient.addColorStop(0, `rgba(255,255,220,${1 - blastProgress * .4})`);
      gradient.addColorStop(.25, `rgba(255,174,45,${.9 - blastProgress * .4})`);
      gradient.addColorStop(1, "rgba(255,60,50,0)");
      ctx.fillStyle = gradient;
      ctx.beginPath(); ctx.arc(cx, cy, radius, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = "#fff";
      ctx.font = `${Math.round(22 + 18 * blastProgress)}px sans-serif`;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText("✹", cx, cy);
    }
    ctx.textAlign = "start";
    ctx.textBaseline = "alphabetic";
  }
}

function animateBoard(state) {
  if (animationFrame) cancelAnimationFrame(animationFrame);
  const wrap = document.querySelector(".canvas-wrap");
  const start = performance.now();
  let shook = false;
  function frame(now) {
    const progress = Math.min(1, (now - start) / 1250);
    if (!shook && progress > .6 && state.lastPlay.bombs.length) {
      shook = true;
      wrap.classList.add("exploding");
      setTimeout(() => wrap.classList.remove("exploding"), 520);
    }
    drawBoard(state, progress);
    if (progress < 1) animationFrame = requestAnimationFrame(frame);
  }
  animationFrame = requestAnimationFrame(frame);
}

function showResult(state) {
  const winners = state.players.filter((player) => state.winnerTokens.includes(player.token));
  $("result-title").textContent = winners.length > 1 ? "공동 우승!" : `${winners[0]?.name || ""} 승리!`;
  $("result-copy").textContent = winners.length > 1 ? `${winners.map((player) => player.name).join(", ")} 플레이어가 같은 면적을 차지했습니다.` : "가장 많은 격자 칸을 차지했습니다.";
  $("final-scores").innerHTML = [...state.players].sort((a, b) => b.score - a.score).map((player, i) => `<div class="final-row"><span>${i + 1}위 · ${escapeHtml(player.name)}</span><span style="color:${player.color}">${player.score}칸</span></div>`).join("");
  $("result-modal").classList.remove("hidden");
}

$("create-button").addEventListener("click", () => socket.emit("create_room", identityPayload()));
$("join-button").addEventListener("click", () => socket.emit("join_room", identityPayload()));
$("start-button").addEventListener("click", () => {
  const event = gameState.status === "lobby" ? "begin_ordering" : "start_game";
  socket.emit(event, {code: gameState.code, token: myToken});
});
$("order-button").addEventListener("click", () => socket.emit("draw_order", {code: gameState.code, token: myToken}));
$("deck-area").addEventListener("click", (event) => {
  const deck = event.target.closest(".deck-button");
  if (!deck || deck.disabled) return;
  deck.classList.remove("drawing");
  void deck.offsetWidth;
  deck.classList.add("drawing");
  setTimeout(() => deck.classList.remove("drawing"), 560);
  socket.emit("draw_from_deck", {code: gameState.code, token: myToken, category: deck.dataset.category});
});
$("reveal-close").addEventListener("click", () => {
  $("card-reveal").classList.add("closing");
  setTimeout(() => {
    $("card-reveal").classList.add("hidden");
    $("card-reveal").classList.remove("closing");
  }, 260);
});
$("hand").addEventListener("click", (event) => {
  const card = event.target.closest(".hand-card");
  if (!card || card.disabled) return;
  selected[card.dataset.category] = card.dataset.cardId;
  renderHand();
});
$("play-button").addEventListener("click", () => {
  if (!selected.function || !selected.x || !selected.y) return;
  socket.emit("play_cards", {
    code: gameState.code,
    token: myToken,
    functionId: selected.function,
    xId: selected.x,
    yId: selected.y,
  });
  $("play-button").disabled = true;
});
$("copy-code").addEventListener("click", async () => {
  await navigator.clipboard.writeText(gameState.code);
  toast("초대 코드를 복사했습니다.");
});
$("back-home").addEventListener("click", () => {
  localStorage.removeItem("parabola_token");
  localStorage.removeItem("parabola_room");
  location.reload();
});
$("invite-code").addEventListener("input", (event) => event.target.value = event.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ""));
document.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !$("entry-view").classList.contains("hidden")) {
    $("invite-code").value ? $("join-button").click() : $("create-button").click();
  }
});

socket.on("joined", ({token, state}) => {
  myToken = token;
  savedCode = state.code;
  localStorage.setItem("parabola_token", token);
  localStorage.setItem("parabola_room", state.code);
  render(state);
});
socket.on("hand", ({cards}) => {
  const oldLengths = Object.fromEntries(Object.entries(myHand).map(([category, items]) => [category, items.length]));
  const newSize = Object.values(cards).reduce((total, categoryCards) => total + categoryCards.length, 0);
  const drewCard = newSize > previousHandSize;
  const openedCategory = newSize - previousHandSize === 5
    ? ["function", "x", "y"].find((category) => oldLengths[category] === 0 && cards[category].length === 5)
    : null;
  myHand = cards;
  previousHandSize = newSize;
  selected = {function: null, x: null, y: null};
  renderHand();
  if (drewCard) {
    document.querySelector(".action-panel")?.classList.add("card-arrived");
    setTimeout(() => document.querySelector(".action-panel")?.classList.remove("card-arrived"), 520);
  }
  if (openedCategory) showCardReveal(openedCategory, cards[openedCategory]);
});
socket.on("state", render);
socket.on("game_error", ({message}) => { toast(message); renderHand(); });
socket.on("connect", () => {
  if (savedCode && myToken) socket.emit("join_room", {code: savedCode, token: myToken, name: ""});
});
window.addEventListener("resize", () => gameState && drawBoard(gameState, 1));
