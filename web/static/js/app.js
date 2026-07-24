// ============================================================================
// COMPILE 프론트엔드
// 서버(Flask)와 요청/응답으로 대화한다: 상태를 받아 그리고, 사람이 뭔가
// 결정해야 하면(pending.kind === "input") 화면에 선택지를 띄우고 답을
// 제출한다. 애니메이션 이벤트(pending.kind === "anim")는 잠깐 쉬었다가
// 자동으로 다음 지점까지 진행시킨다.
// ============================================================================

const PROTO = JSON.parse(document.getElementById("proto-data").textContent);

let gameId = null;
let lastState = null;
let armedUid = null;         // "action" 진행 중 클릭으로 고른 손 카드
let dragCtx = null;          // 드래그 중인 손 카드: {uid}
let rearrangeOrder = null;
let rearrangeFirstPick = null;
const handOrders = {};       // pi -> [uid, ...] 사용자가 정한 손패 표시 순서

const PLAYER_NAMES = { 1: "플레이어1", 2: "플레이어2" };
function pName(pi) {
  return PLAYER_NAMES[pi] || `플레이어${pi}`;
}

// 닉네임이 자유 텍스트라, 받침 유무에 따라 "이"/"가"를 골라 붙인다.
function hasBatchim(str) {
  if (!str) return false;
  const code = str.charCodeAt(str.length - 1);
  if (code < 0xAC00 || code > 0xD7A3) return false; // 완성형 한글 범위 밖(영문/숫자 등)이면 받침 없다고 취급
  return (code - 0xAC00) % 28 !== 0;
}
function josa(pi) {
  return hasBatchim(pName(pi)) ? "이" : "가";
}

let knownCardUids = new Set(); // 이전 렌더에서 이미 봤던 카드 uid들
let newCardUids = new Set();   // 이번 렌더에서 "새로 등장" 판정된 카드 uid들 (드로우/플레이 애니메이션용)

function computeAllCardUids(state) {
  const s = new Set();
  for (const pi of [1, 2]) {
    const p = state.players[String(pi)];
    p.hand.forEach((c) => s.add(c.uid));
    [1, 2, 3].forEach((line) => p.stacks[String(line)].forEach((c) => s.add(c.uid)));
  }
  return s;
}

const $ = (sel) => document.querySelector(sel);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ----------------------------------------------------------------------------
// 셋업 화면
// ----------------------------------------------------------------------------
let chosenMode = null;
let chosenDraft = "random";
let chosenSet = "all";

document.querySelectorAll(".mode-btn[data-mode]").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".mode-btn[data-mode]").forEach((b) => b.classList.remove("selected"));
    btn.classList.add("selected");
    chosenMode = btn.dataset.mode;
    $("#start-btn").disabled = false;
    $("#nick-p2-field").classList.toggle("hidden", chosenMode === "vs_ai");
  });
});

document.querySelectorAll(".mode-btn[data-draft]").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".mode-btn[data-draft]").forEach((b) => b.classList.remove("selected"));
    btn.classList.add("selected");
    chosenDraft = btn.dataset.draft;
    $("#set-select").classList.toggle("hidden", chosenDraft !== "draft");
  });
});
document.querySelectorAll(".mode-btn[data-set]").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".mode-btn[data-set]").forEach((b) => b.classList.remove("selected"));
    btn.classList.add("selected");
    chosenSet = btn.dataset.set;
  });
});
// 기본값을 시각적으로도 선택 표시
document.querySelector('.mode-btn[data-draft="random"]').classList.add("selected");
document.querySelector('.mode-btn[data-set="all"]').classList.add("selected");

$("#goto-play-setup-btn").addEventListener("click", () => {
  $("#setup-screen").classList.add("hidden");
  $("#play-setup-screen").classList.remove("hidden");
});
$("#back-to-landing-btn").addEventListener("click", () => {
  $("#play-setup-screen").classList.add("hidden");
  $("#setup-screen").classList.remove("hidden");
});

let confirmPlayEnabled = true;

function applyNicknames() {
  const n1 = $("#nick-p1").value.trim();
  const n2 = $("#nick-p2").value.trim();
  PLAYER_NAMES[1] = n1 || "플레이어1";
  PLAYER_NAMES[2] = (chosenMode === "vs_ai") ? "AI" : (n2 || "플레이어2");
}

$("#start-btn").addEventListener("click", () => {
  applyNicknames();
  confirmPlayEnabled = $("#confirm-play-toggle").checked;
  if (chosenDraft === "draft") {
    startDraft(chosenMode, chosenSet);
  } else {
    startGame(chosenMode, null);
  }
});
$("#win-newgame").addEventListener("click", () => location.reload());
$("#new-game-btn").addEventListener("click", () => location.reload());

// ----------------------------------------------------------------------------
// 버림더미 / 전체 덱 구성 열람 모달
// ----------------------------------------------------------------------------
function currentSelfPi(state) {
  const req = state.pending && state.pending.kind === "input" ? state.pending.req : null;
  return req ? req.chooser : state.turn;
}

function openDiscardModal(pi) {
  if (!lastState) return;
  const self = currentSelfPi(lastState);
  if (pi !== self) return; // 실물 규칙과 무관하게, 요청대로 "지금 차례인 사람" 것만 확인 가능
  const cards = lastState.players[String(pi)].discard.map((c) => ({ proto: c.proto, value: c.value }));
  showPileModal(`버림더미 — ${pName(pi)}`, cards);
}

function openDeckModal(pi) {
  if (!lastState) return;
  const protos = lastState.players[String(pi)].protocols;
  const cards = [];
  [1, 2, 3].forEach((line) => {
    const proto = protos[String(line)];
    (PROTO.values[proto] || []).forEach((v) => cards.push({ proto, value: v }));
  });
  showPileModal(`전체 덱 구성 — ${pName(pi)} (18장)`, cards);
}

function showPileModal(title, cards) {
  $("#pile-modal-title").textContent = title;
  const grid = $("#pile-modal-grid");
  grid.innerHTML = "";
  if (cards.length === 0) {
    grid.innerHTML = `<div class="card-info-empty">비어있어요</div>`;
  }
  cards.forEach((c) => {
    const accent = PROTO.colors[c.proto] || "#888";
    grid.appendChild(renderCodexCard(c.proto, c.value, accent));
  });
  $("#pile-modal").classList.remove("hidden");
}

function closePileModal() {
  $("#pile-modal").classList.add("hidden");
}

$("#deck-p1").addEventListener("click", () => openDeckModal(1));
$("#deck-p2").addEventListener("click", () => openDeckModal(2));
$("#discard-p1").addEventListener("click", () => openDiscardModal(1));
$("#discard-p2").addEventListener("click", () => openDiscardModal(2));
$("#pile-modal-close").addEventListener("click", closePileModal);
$("#pile-modal").addEventListener("click", (ev) => {
  if (ev.target.id === "pile-modal") closePileModal();
});

async function startGame(mode, draftedProtocols) {
  const body = { mode: mode || "hotseat", aiSide: 2 };
  if (draftedProtocols) body.draftedProtocols = draftedProtocols;
  const res = await fetch("/api/new_game", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  gameId = data.gameId;
  $("#setup-screen").classList.add("hidden");
  $("#play-setup-screen").classList.add("hidden");
  $("#draft-screen").classList.add("hidden");
  $("#game-screen").classList.remove("hidden");
  handleState(data.state, requestSeq);
}

// ----------------------------------------------------------------------------
// 밴픽 화면 -- 실물 프로토콜 카드(로딩 카드) 스타일
// ----------------------------------------------------------------------------
let draftId = null;
let draftGameMode = "hotseat";

// draft.py의 STEPS/MANUAL_STEPS를 그대로 반영 (단계 표시줄 렌더링용).
const DRAFT_STEPS_META = {
  hotseat: [
    { who: 1, action: "pick", count: 1 }, { who: 2, action: "pick", count: 2 },
    { who: 1, action: "ban", count: 1 }, { who: 2, action: "ban", count: 1 },
    { who: 1, action: "pick", count: 2 }, { who: 2, action: "pick", count: 1 },
  ],
  vs_ai: [
    { who: 1, action: "pick", count: 3 }, { who: 2, action: "pick", count: 3 },
  ],
};

function setToSetsParam(set) {
  if (set === "main1") return ["main1", "aux1"];
  if (set === "main2") return ["main2", "aux2"];
  return null; // 전체
}

async function startDraft(mode, set) {
  draftGameMode = mode || "hotseat";
  const res = await fetch("/api/draft/new", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode: draftGameMode, sets: setToSetsParam(set) }),
  });
  const data = await res.json();
  draftId = data.draftId;
  $("#setup-screen").classList.add("hidden");
  $("#play-setup-screen").classList.add("hidden");
  $("#draft-screen").classList.remove("hidden");
  renderDraft(data.state);
}

async function draftPick(player, protoId) {
  const res = await fetch(`/api/draft/pick/${draftId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ player, protoId }),
  });
  const data = await res.json();
  renderDraft(data);
}

function renderDraft(state) {
  const cur = state.current;
  const stepsMeta = DRAFT_STEPS_META[state.mode] || DRAFT_STEPS_META.hotseat;
  const doneCount = Object.keys(state.owner).length;
  renderDraftSteps(stepsMeta, doneCount);

  const subtitle = $("#draft-subtitle");
  if (cur) {
    const actLabel = cur.action === "ban"
      ? `<span class="act-ban">${cur.remaining}개 밴</span>` : `<span class="act-pick">${cur.remaining}개 선택</span>`;
    subtitle.innerHTML = `<span class="who">${pName(cur.player)}</span> 차례 · ${actLabel}`;
  } else {
    subtitle.textContent = "";
  }

  $("#draft-picks-1").classList.toggle("is-turn", !!cur && cur.player === 1);
  $("#draft-picks-2").classList.toggle("is-turn", !!cur && cur.player === 2);
  $("#draft-picks-1 .draft-side-title").textContent = pName(1);
  $("#draft-picks-2 .draft-side-title").textContent = pName(2);
  renderDraftPicks(1, state.picks["1"]);
  renderDraftPicks(2, state.picks["2"]);

  const poolEl = $("#draft-pool");
  poolEl.innerHTML = "";
  state.pool.forEach((protoId) => {
    const status = state.owner[protoId]; // undefined | 1 | 2 | "ban"
    poolEl.appendChild(renderDraftCard(protoId, cur, status));
  });

  if (state.done) {
    sleep(500).then(() => startGame(draftGameMode, state.result));
  }
}

function renderDraftSteps(stepsMeta, doneCount) {
  const el = $("#draft-steps");
  el.innerHTML = "";
  let cum = 0;
  let curIdx = stepsMeta.length;
  for (let i = 0; i < stepsMeta.length; i++) {
    cum += stepsMeta[i].count;
    if (doneCount < cum) { curIdx = i; break; }
  }
  stepsMeta.forEach((s, i) => {
    const pip = document.createElement("div");
    pip.className = `draft-step ${s.action}` + (i === curIdx ? " current" : (i < curIdx ? " filled" : ""));
    pip.textContent = s.action === "ban" ? "✕" : "▾";
    pip.title = `${pName(s.who)} ${s.action === "ban" ? "밴" : "픽"} ${s.count}개`;
    el.appendChild(pip);
  });
}

// "로딩 카드": 태그라인 / 프로토콜 이름 / 키워드(verbs) -- 실물 카드 뒷면과 동일한 정보.
function renderDraftCard(protoId, cur, status) {
  const card = document.createElement("div");
  const taken = status !== undefined; // 1 | 2 | "ban"
  card.className = "draft-card" + (taken ? " taken" : "") + (status === "ban" ? " banned" : "");
  const accent = PROTO.colors[protoId] || "#888";
  card.style.setProperty("--card-accent", accent);
  const tagline = (PROTO.tagline && PROTO.tagline[protoId]) || "";
  const verbs = (PROTO.verbs && PROTO.verbs[protoId]) || "";

  let badge = "";
  if (status === "ban") badge = `<div class="dc-badge dc-badge-ban">밴됨</div>`;
  else if (status === 1 || status === 2) badge = `<div class="dc-badge dc-badge-taken">${pName(status)} 픽</div>`;

  card.innerHTML = `
    <div class="dc-tagline">${tagline}</div>
    <div class="dc-name">${protoKo(protoId)}</div>
    <div class="dc-verbs">${verbs}</div>
    ${badge}
  `;
  if (cur && !taken) {
    card.addEventListener("click", () => draftPick(cur.player, protoId));
  }
  return card;
}

function renderDraftPicks(pi, picks) {
  const el = $(`#draft-picks-${pi}-list`);
  el.innerHTML = "";
  for (let i = 0; i < 3; i++) {
    const protoId = picks[i];
    const chip = document.createElement("div");
    if (protoId) {
      chip.className = "draft-pick-chip";
      chip.style.setProperty("--pick-accent", PROTO.colors[protoId] || "");
      chip.textContent = protoKo(protoId);
    } else {
      chip.className = "draft-pick-chip empty";
      chip.textContent = "-";
    }
    el.appendChild(chip);
  }
}

// ----------------------------------------------------------------------------
// 상태 진행 루프
// ----------------------------------------------------------------------------
let requestSeq = 0; // 오래된 응답이 최신 화면을 덮어쓰는 경쟁 조건 방지용

async function handleState(state, mySeq) {
  if (mySeq !== undefined && mySeq !== requestSeq) return; // 그새 더 최신 요청이 나감 -- 이 응답은 버림
  lastState = state;
  render(state);

  if (state.error) {
    showPromptBar(true, `<span style="color:var(--danger)">엔진 오류: ${state.error}</span>`, []);
    return;
  }
  if (state.winner) {
    showWin(state.winner);
    return;
  }
  if (!state.pending) {
    showPromptBar(false);
    return;
  }
  if (state.pending.kind === "anim") {
    showPromptBar(false);
    const dur = Math.max(300, (state.pending.dur || 0.3) * 1000 * 0.6);
    await sleep(dur);
    const seq = ++requestSeq;
    const res = await fetch(`/api/advance_anim/${gameId}`, { method: "POST" });
    handleState(await res.json(), seq);
  } else {
    armedUid = null;
    rearrangeOrder = null;
    renderPrompt(state);
  }
}

async function submitAnswer(value) {
  showPromptBar(false);
  armedUid = null;
  const seq = ++requestSeq;
  const res = await fetch(`/api/answer/${gameId}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ value }),
  });
  handleState(await res.json(), seq);
}

function tr(text, params) {
  if (!text || !params) return text;
  return text.replace(/%\{(\w+)\}/g, (m, k) => (params[k] !== undefined ? params[k] : m));
}

function protoKo(proto) {
  return (PROTO.namesKo && PROTO.namesKo[proto]) || proto;
}

// ----------------------------------------------------------------------------
// 전체 렌더링
// ----------------------------------------------------------------------------
function render(state) {
  const allUids = computeAllCardUids(state);
  newCardUids = new Set([...allUids].filter((u) => !knownCardUids.has(u)));

  maybeShowTurnBanner(state);
  renderOppHandPreview(state);
  renderTurnBox(state);
  renderControlMarker(state);
  renderDeckCols(state);
  renderLinesRow(state);
  renderHand(state);
  renderLog(state);
  renderStatusBar(state);
  reattachPinnedZoom();

  knownCardUids = allUids;
}

// 하스스톤 식 턴 시작 배너: "OOO의 턴"
let announcedTurnCount = -1;
function maybeShowTurnBanner(state) {
  if (state.winner || state.turnCount == null) return;
  if (state.turnCount === announcedTurnCount) return;
  announcedTurnCount = state.turnCount;
  const el = $("#turn-banner");
  const textEl = $("#turn-banner-text");
  textEl.textContent = `${pName(state.turn)}의 턴`;
  el.classList.remove("hidden");
  textEl.style.animation = "none";
  void textEl.offsetWidth; // 강제 리플로우로 애니메이션 재시작
  textEl.style.animation = "";
  clearTimeout(window.__turnBannerTimer);
  window.__turnBannerTimer = setTimeout(() => el.classList.add("hidden"), 1700);
}

// 상단: "상대"(=지금 결정하는 사람이 아닌 쪽) 손패를, 내 손패와 동일한
// 크기의 뒷면 카드로 표시 (5번 요청: 크기 통일).
function renderOppHandPreview(state) {
  const self = currentSelfPi(state);
  const opp = self === 1 ? 2 : 1;
  const hand = state.players[String(opp)].hand;
  const box = $("#opp-hand-cards");
  box.innerHTML = "";
  hand.forEach(() => {
    const el = document.createElement("div");
    el.className = "card hand-card";
    el.innerHTML = `<span class="ohc-back">${pName(opp)}<br>손패</span>`;
    box.appendChild(el);
  });
}

// 고정(pin)된 카드가 있으면, 매 렌더마다 새로 생성되는 카드 엘리먼트에
// 확대 미리보기를 다시 붙인다 (손패든 보드든 상관없이 uid로 찾는다).
function reattachPinnedZoom() {
  if (!pinnedCard) return;
  const el = document.querySelector(`.card[data-uid="${pinnedCard.uid}"]`);
  if (!el) {
    // 고정했던 카드가 더 이상 화면에 없음(냈거나 이동 등) -> 고정 해제
    pinnedCard = null;
    pinnedZoom = false;
    clearCardInfo();
    hideCardZoom();
    return;
  }
  if (pinnedZoom) showCardZoomAbove(el, pinnedCard);
}

// Control 컴포넌트: 중립이면 필드 정가운데, 어느 쪽이 쥐고 있으면 그쪽
// 절반으로 이동한다 (위=플레이어2, 아래=플레이어1).
function renderControlMarker(state) {
  const el = $("#control-marker");
  el.classList.remove("p1", "p2");
  let topPct = 50;
  if (state.control === 2) {
    topPct = 14;
    el.classList.add("p2");
  } else if (state.control === 1) {
    topPct = 86;
    el.classList.add("p1");
  }
  el.style.top = `${topPct}%`;
}

function phaseLabel(phase) {
  const labels = { setup: "준비", start: "시작", control: "제어", compile: "컴파일",
                   action: "행동", cache: "캐시 정리", end: "종료", over: "게임 종료" };
  return labels[phase] || phase;
}

function renderTurnBox(state) {
  const box = $("#turn-box");
  if (state.winner) { box.innerHTML = ""; return; }
  box.innerHTML = `
    <span class="turn-n">T${state.turnCount}</span> ·
    <span class="turn-who">${pName(state.turn)}</span>의 턴 · ${phaseLabel(state.phase)}
    ${state.control ? `<span class="turn-control">CONTROL: P${state.control}</span>` : ""}
  `;
}

function renderDeckCols(state) {
  for (const pi of [1, 2]) {
    const p = state.players[String(pi)];
    $(`#deck-p${pi}`).innerHTML = `덱<div class="count-badge">${p.deckCount}</div>`;
    $(`#discard-p${pi}`).innerHTML = `버림<div class="count-badge">${p.discard.length}</div>`;
  }
}

function lineValue(state, pi, line) {
  // 서버(engine.line_value)가 거울0/금속0 같은 패시브 보정까지 반영해서
  // 계산한 진짜 값을 그대로 쓴다. 화면에서 카드 값을 단순 합산하면 이런
  // 패시브가 누락된다.
  return state.players[String(pi)].lineValues[String(line)];
}

// ----------------------------------------------------------------------------
// 라인 3칸: 각 칸 = [상대 스택(위)] [프로토콜 띠] [내 스택(아래)]
// ----------------------------------------------------------------------------
function renderLinesRow(state) {
  const row = $("#lines-row");
  row.innerHTML = "";
  const pending = state.pending;
  const req = pending && pending.kind === "input" ? pending.req : null;
  const rearrangeReq = req && req.type === "rearrange" ? req : null;

  for (let line = 1; line <= 3; line++) {
    const col = document.createElement("div");
    col.className = "line-col";
    col.dataset.line = line;

    const oppZone = document.createElement("div");
    oppZone.className = "stack-zone opp-zone";
    oppZone.dataset.pi = "2";
    oppZone.dataset.line = String(line);
    renderStack(oppZone, state.players["2"].stacks[String(line)], state);

    const belt = document.createElement("div");
    belt.className = "proto-belt";
    belt.appendChild(protoPill(state, 2, line, rearrangeReq));
    belt.appendChild(protoPill(state, 1, line, rearrangeReq));

    const selfZone = document.createElement("div");
    selfZone.className = "stack-zone self-zone";
    selfZone.dataset.pi = "1";
    selfZone.dataset.line = String(line);
    renderStack(selfZone, state.players["1"].stacks[String(line)], state);

    attachZoneInteractions(oppZone, req);
    attachZoneInteractions(selfZone, req);
    attachLineClickForChooseLine(col, line, req);

    col.appendChild(oppZone);
    col.appendChild(belt);
    col.appendChild(selfZone);
    row.appendChild(col);
  }
  setDropZones(armedUid);
}

// 스택은 항상 프로토콜 띠에 붙어서 시작한다: uncovered(스택 맨 위) 카드가
// 항상 띠와 맞닿고, covered 카드들은 그 바깥쪽으로 헤더만 보이며 이어진다.
// nearBeltFirst가 true(자신 쪽, 띠가 위에 있음)면 배열을 뒤집어서 uncovered가
// 첫 DOM 자식이 되게 한다 (justify-content:flex-start가 띠 쪽으로 붙임).
function renderStack(zoneEl, cards, state) {
  cards.forEach((c, idx) => {
    const isUncovered = idx === cards.length - 1;
    zoneEl.appendChild(renderBoardCard(c, state, isUncovered));
  });
}

function protoPill(state, pi, line, rearrangeReq) {
  const p = state.players[String(pi)];
  const compiled = p.compiled[String(line)];
  const isRearrangeTarget = rearrangeReq && rearrangeReq.target === pi;
  let proto;
  if (isRearrangeTarget) {
    if (!rearrangeOrder) rearrangeOrder = [1, 2, 3];
    proto = (rearrangeReq.protocols || {})[rearrangeOrder[line - 1]];
  } else {
    proto = p.protocols[String(line)];
  }
  const el = document.createElement("div");
  el.className = "proto-pill" + (compiled ? " compiled" : "");
  const accent = PROTO.colors[proto] || "";
  el.style.setProperty("--proto-accent", accent);

  const value = lineValue(state, pi, line);
  const oppValue = lineValue(state, pi === 1 ? 2 : 1, line);
  const hot = value >= 10 ? " hot" : ""; // 컴파일 임계값(10) 이상이면 강조
  const winning = value > oppValue ? " winning" : ""; // 이 라인에서 우위인 쪽 강조

  el.innerHTML = `
    <span class="pp-name">${protoKo(proto)}</span>
    <span class="pp-value${hot}${winning}">${value}</span>
  `;

  if (isRearrangeTarget) {
    el.classList.add("rearrange-slot");
    if (rearrangeFirstPick === line) el.classList.add("rearrange-picked");
    el.addEventListener("click", (ev) => {
      ev.stopPropagation();
      handleRearrangeSlotClick(line);
    });
  }
  return el;
}

// 필드에서 라인(슬롯) 두 개를 순서대로 클릭해서 프로토콜을 교환한다.
// 원하는 만큼 반복해서 여러 번 교환할 수 있다.
function handleRearrangeSlotClick(slot) {
  if (!rearrangeOrder) rearrangeOrder = [1, 2, 3];
  if (rearrangeFirstPick === null) {
    rearrangeFirstPick = slot;
  } else if (rearrangeFirstPick === slot) {
    rearrangeFirstPick = null; // 같은 곳을 다시 클릭하면 선택 취소
  } else {
    const a = rearrangeFirstPick - 1, b = slot - 1;
    [rearrangeOrder[a], rearrangeOrder[b]] = [rearrangeOrder[b], rearrangeOrder[a]];
    rearrangeFirstPick = null;
  }
  render(lastState);
  renderPrompt(lastState);
}

// ----------------------------------------------------------------------------
// 보드 카드 렌더링: 헤더(이름+값)는 covered여도 항상 보이고, uncovered일 때만
// 본문(중단 명령 미리보기)까지 펼쳐진다 -- 실물 카드가 덮여도 이름/값이
// 항상 보이는 것과 같다.
// ----------------------------------------------------------------------------
function isChooseCardCandidate(state, card) {
  const pending = state.pending;
  if (!pending || pending.kind !== "input") return false;
  const req = pending.req;
  if (req.type !== "chooseCard") return false;
  return (req.candidates || []).includes(card.uid);
}

function bandHtml(kind, lines) {
  if (lines && lines.length) {
    return `<div class="card-body card-band-${kind}">${lines.join(" ")}</div>`;
  }
  return `<div class="card-body card-band-${kind} card-band-empty"></div>`;
}

function renderBoardCard(c, state, isUncovered) {
  const div = document.createElement("div");
  div.dataset.uid = c.uid;
  div.className = "card board-card" + (c.faceUp ? " face-up" : " face-down")
    + (isUncovered ? " uncovered" : " covered")
    + (newCardUids.has(c.uid) ? " card-enter" : "");

  if (c.faceUp) {
    const color = PROTO.colors[c.proto] || "#888";
    div.style.setProperty("--card-accent", color);
    const text = (PROTO.cardText && PROTO.cardText[`${c.proto}_${c.value}`]) || {};
    let bandsHtml = "";
    // 상단(top) 텍스트는 덮여도 항상 활성/표시 (실물 카드 규칙: "Top Command - Persistent").
    bandsHtml += bandHtml("top", text.top);
    // 중단/하단은 uncovered일 때만 보임.
    if (isUncovered) {
      bandsHtml += bandHtml("mid", text.mid);
      bandsHtml += bandHtml("bot", text.bot);
    }
    div.innerHTML = `<div class="card-header">
        <span class="card-name">${protoKo(c.proto)}</span><span class="card-num">${c.value}</span>
      </div>${bandsHtml}`;
    attachCardInfoHover(div, c, true);
  } else {
    // 뒷면 카드도 앞면처럼 헤더를 보여준다: 프로토콜/이름은 숨겨져 있지만
    // 값은 항상 2로 고정(룰북)이라 그대로 표시. 본문(COMPILE 워터마크)은
    // uncovered일 때만.
    const bodyHtml = isUncovered
      ? `<div class="card-body card-back-mini">COMPILE<br>&lt;|&gt;</div>`
      : "";
    div.innerHTML = `<div class="card-header face-down-header">
        <span class="card-name">뒷면</span><span class="card-num">2</span>
      </div>${bodyHtml}`;
    // 실물 규칙: 뒷면 카드는 "자신의" 것만 언제든 확인할 수 있다 -- 상대
    // 영역의 뒷면 카드는 볼 수 없어야 한다. hotseat이라 "자신"은 지금
    // 결정 중인 플레이어(chooser, 없으면 현재 턴 플레이어) 기준.
    const pending = state.pending;
    const req = pending && pending.kind === "input" ? pending.req : null;
    const viewerPi = req ? req.chooser : state.turn;
    if (c.owner === viewerPi) {
      attachCardInfoHover(div, c, true);
    }
  }
  if (isChooseCardCandidate(state, c)) {
    div.classList.add("selectable");
    div.addEventListener("click", (ev) => { ev.stopPropagation(); submitAnswer(c.uid); });
  }
  return div;
}

// ----------------------------------------------------------------------------
// 카드 정보 패널 (사이드바에 도킹, 실물 카드의 밴드 레이아웃을 흉내낸다)
// ----------------------------------------------------------------------------
let pinnedCard = null; // 클릭으로 고정된 카드 (null이면 고정 없음)
let pinnedZoom = false; // 고정된 카드가 확대 미리보기도 함께 고정하는지

// 카드가 아닌 곳(빈 필드, 배경 등)을 클릭하면 고정 해제 -> 기본 화면으로.
document.addEventListener("click", (ev) => {
  if (pinnedCard && !ev.target.closest(".card")) {
    pinnedCard = null;
    pinnedZoom = false;
    clearCardInfo();
    hideCardZoom();
  }
});

function attachCardInfoHover(el, card, alsoZoomAbove) {
  el.addEventListener("mouseenter", () => {
    showCardInfo(card);
    if (alsoZoomAbove) showCardZoomAbove(el, card);
  });
  el.addEventListener("mouseleave", () => {
    if (pinnedCard) {
      showCardInfo(pinnedCard); // 고정된 카드가 있으면 그걸로 복귀
      if (pinnedZoom) {
        const pinnedEl = document.querySelector(`.card[data-uid="${pinnedCard.uid}"]`);
        if (pinnedEl) { showCardZoomAbove(pinnedEl, pinnedCard); return; }
      }
      hideCardZoom();
    } else {
      clearCardInfo();
      if (alsoZoomAbove) hideCardZoom();
    }
  });
  el.addEventListener("click", () => togglePinCard(el, card, alsoZoomAbove));
}

// 카드를 클릭하면 정보를 고정해서 마우스를 치워도 계속 보이게 한다.
// 같은 카드를 다시 클릭하면 고정 해제. (게임 진행용 클릭 핸들러와는 별개로 동작)
function togglePinCard(el, card, alsoZoomAbove) {
  if (pinnedCard && pinnedCard.uid === card.uid) {
    pinnedCard = null;
    pinnedZoom = false;
    clearCardInfo();
    hideCardZoom();
  } else {
    pinnedCard = card;
    pinnedZoom = !!alsoZoomAbove;
    showCardInfo(card);
    if (pinnedZoom) showCardZoomAbove(el, card);
    else hideCardZoom();
  }
}

// 하스스톤 식: 손패 카드에 마우스를 올리면 그 카드 바로 위에 전체 내용을
// 확대해서 보여준다 (사이드바 갱신과 별개로 함께 뜬다).
function showCardZoomAbove(el, card) {
  const zoom = $("#card-zoom");
  zoom.innerHTML = cardInfoInnerHtml(card);
  zoom.style.setProperty("--cz-accent", PROTO.colors[card.proto] || "#3dffa0");
  zoom.style.width = "240px";
  zoom.classList.remove("hidden");

  const rect = el.getBoundingClientRect();
  let left = rect.left + rect.width / 2 - 120;
  left = Math.max(6, Math.min(left, window.innerWidth - 246));
  zoom.style.left = `${left}px`;
  zoom.style.top = "-9999px"; // 높이를 재기 전까지 화면 밖에 둠 (깜빡임 방지)

  requestAnimationFrame(() => {
    const zh = zoom.offsetHeight;
    let top = rect.top - zh - 14;
    if (top < 6) top = rect.bottom + 14; // 위쪽 공간이 부족하면 아래로
    zoom.style.top = `${top}px`;
  });
}

function hideCardZoom() {
  $("#card-zoom").classList.add("hidden");
}

function cardInfoInnerHtml(card) {
  const accent = PROTO.colors[card.proto] || "#3dffa0";
  const text = (PROTO.cardText && PROTO.cardText[`${card.proto}_${card.value}`]) || { top: [], mid: [], bot: [] };
  let html = `<div class="ci-header" style="--ci-accent:${accent}">
    <span class="ci-name">${protoKo(card.proto)}</span>
    <span class="ci-value" style="--ci-accent:${accent}">${card.value}</span>
  </div>`;
  ["top", "mid", "bot"].forEach((z) => {
    if (text[z] && text[z].length) {
      html += `<div class="ci-band" style="--ci-accent:${accent}">${text[z].join(" ")}</div>`;
    } else {
      html += `<div class="ci-band-empty"></div>`;
    }
  });
  return html;
}

function showCardInfo(card) {
  $("#card-info-box").innerHTML = cardInfoInnerHtml(card);
}

function clearCardInfo() {
  $("#card-info-box").innerHTML = `<div class="card-info-empty">카드에 마우스를 올리면<br>여기에 효과가 표시돼요</div>`;
}

// ----------------------------------------------------------------------------
// 손패 (클릭/드래그로 내기 + 드래그로 재정렬)
// ----------------------------------------------------------------------------
function syncHandOrder(pi, rawHand) {
  let order = handOrders[pi] || [];
  const present = new Set(rawHand.map((c) => c.uid));
  order = order.filter((u) => present.has(u));
  rawHand.forEach((c) => { if (!order.includes(c.uid)) order.push(c.uid); });
  handOrders[pi] = order;
  const byUid = {};
  rawHand.forEach((c) => { byUid[c.uid] = c; });
  return order.map((u) => byUid[u]);
}

function reorderHand(pi, draggedUid, targetUid) {
  const order = handOrders[pi];
  if (!order) return;
  const from = order.indexOf(draggedUid);
  if (from === -1) return;
  order.splice(from, 1);
  const to = order.indexOf(targetUid);
  order.splice(to === -1 ? order.length : to, 0, draggedUid);
  render(lastState);
}

function renderHand(state) {
  const pending = state.pending;
  const req = pending && pending.kind === "input" ? pending.req : null;
  let chooser = req ? req.chooser : state.turn;
  // AI 턴 중 활성 입력 요청이 없으면(애니메이션 진행 중 등) AI의 패가
  // 노출되지 않도록, 사람 쪽 패를 대신 보여준다.
  if (!req && state.players[String(chooser)].isAI) {
    const other = chooser === 1 ? 2 : 1;
    if (!state.players[String(other)].isAI) chooser = other;
  }
  const hand = syncHandOrder(chooser, state.players[String(chooser)].hand);

  const box = $("#hand-cards");
  box.innerHTML = "";
  hand.forEach((c) => {
    const el = document.createElement("div");
    el.className = "card hand-card" + (newCardUids.has(c.uid) ? " card-enter" : "");
    el.dataset.uid = c.uid;
    const color = PROTO.colors[c.proto] || "#888";
    el.style.setProperty("--card-accent", color);
    el.innerHTML = `
      <div class="hc-header">${protoKo(c.proto)}</div>
      <div class="hc-value">${c.value}</div>
    `;
    attachCardInfoHover(el, c, true);

    el.draggable = true;
    el.addEventListener("dragstart", (ev) => {
      dragCtx = { uid: c.uid };
      ev.dataTransfer.setData("text/plain", String(c.uid));
      ev.dataTransfer.effectAllowed = "move";
      setTimeout(() => el.classList.add("dragging"), 0);
      if (req && req.type === "action" && isHandCardSelectable(req, c)) setDropZones(c.uid);
    });
    el.addEventListener("dragend", () => {
      el.classList.remove("dragging");
      setDropZones(armedUid);
      dragCtx = null;
    });
    el.addEventListener("dragover", (ev) => {
      if (dragCtx && dragCtx.uid !== c.uid) {
        ev.preventDefault();
        el.classList.add("reorder-target");
      }
    });
    el.addEventListener("dragleave", () => el.classList.remove("reorder-target"));
    el.addEventListener("drop", (ev) => {
      ev.preventDefault();
      el.classList.remove("reorder-target");
      if (dragCtx && dragCtx.uid !== c.uid) reorderHand(chooser, dragCtx.uid, c.uid);
    });

    if (isHandCardSelectable(req, c)) {
      el.classList.add("selectable");
      if (c.uid === armedUid) el.classList.add("armed");
      if (req && req.type === "chooseHandCards" && (window.__handPick || []).includes(c.uid)) {
        el.classList.add("picked");
      }
      el.addEventListener("click", () => handleHandCardClick(c, req));
    }
    box.appendChild(el);
  });

}

// ----------------------------------------------------------------------------
// 드롭존 (낼 수 있는 라인 하이라이트) + 존 클릭/드롭으로 내기
// ----------------------------------------------------------------------------
function attachZoneInteractions(zoneEl, req) {
  zoneEl.addEventListener("click", () => {
    if (!zoneEl.classList.contains("drop-ok")) return;
    const pi = Number(zoneEl.dataset.pi);
    const line = Number(zoneEl.dataset.line);
    attemptPlayOnZone(armedUid, pi, line);
  });
  zoneEl.addEventListener("dragover", (ev) => {
    if (dragCtx && zoneEl.classList.contains("drop-ok")) {
      ev.preventDefault();
      zoneEl.classList.add("drag-over");
    }
  });
  zoneEl.addEventListener("dragleave", () => zoneEl.classList.remove("drag-over"));
  zoneEl.addEventListener("drop", (ev) => {
    ev.preventDefault();
    zoneEl.classList.remove("drag-over");
    if (!dragCtx) return;
    const pi = Number(zoneEl.dataset.pi);
    const line = Number(zoneEl.dataset.line);
    attemptPlayOnZone(dragCtx.uid, pi, line);
  });
}

function computeZoneMatches(uid, pi, line) {
  if (!uid || !lastState || !lastState.pending || lastState.pending.kind !== "input") return [];
  const chooser = lastState.pending.req.chooser;
  return (window.__legalActions || []).filter((a) =>
    a.kind === "play" && a.uid === uid && a.line === line &&
    (a.side ? a.side === pi : pi === chooser));
}

function confirmAndPlay(action) {
  if (!confirmPlayEnabled) { submitAnswer(action); return; }
  const card = findCardByUid(lastState, action.uid);
  const label = card ? `${protoKo(card.proto)}${card.value}` : "카드";
  const faceLabel = action.faceUp ? "앞면" : "뒷면";
  showPromptBar(true,
    `<span class="prompt-who">${label}</span> 카드를 라인 ${action.line}에 <b>${faceLabel}</b>으로 플레이할까요?`,
    [
      { label: "예", onClick: () => submitAnswer(action) },
      { label: "아니오", secondary: true, onClick: () => renderPrompt(lastState) },
    ]);
}

function makeDropHalf(kind, label, action) {
  const half = document.createElement("div");
  half.className = `drop-half ${kind}`;
  half.textContent = label;
  half.addEventListener("click", (ev) => { ev.stopPropagation(); confirmAndPlay(action); });
  half.addEventListener("dragover", (ev) => { ev.preventDefault(); half.classList.add("drag-over"); });
  half.addEventListener("dragleave", () => half.classList.remove("drag-over"));
  half.addEventListener("drop", (ev) => { ev.preventDefault(); ev.stopPropagation(); confirmAndPlay(action); });
  return half;
}

function setDropZones(uid) {
  document.querySelectorAll(".stack-zone").forEach((zoneEl) => {
    zoneEl.classList.remove("drop-ok", "drag-over");
    zoneEl.querySelectorAll(".drop-half, .drop-zone-label").forEach((h) => h.remove());
    if (!uid) return;
    const pi = Number(zoneEl.dataset.pi);
    const line = Number(zoneEl.dataset.line);
    const matches = computeZoneMatches(uid, pi, line);
    if (matches.length === 0) return;

    const faceUpAction = matches.find((a) => a.faceUp);
    const faceDownAction = matches.find((a) => !a.faceUp);
    if (faceUpAction && faceDownAction) {
      // 앞면/뒷면 둘 다 가능: 영역을 절반씩 나눠서 바로 결정 (중간 질문 없음)
      zoneEl.classList.add("drop-ok");
      zoneEl.appendChild(makeDropHalf("up", "앞면", faceUpAction));
      zoneEl.appendChild(makeDropHalf("down", "뒷면", faceDownAction));
    } else {
      // 한쪽 면만 가능해도 어느 면인지 텍스트로 표시 (3번 요청)
      zoneEl.classList.add("drop-ok");
      const label = document.createElement("div");
      const onlyUp = !!faceUpAction;
      label.className = `drop-zone-label ${onlyUp ? "face-up" : "face-down"}`;
      label.textContent = onlyUp ? "앞면" : "뒷면";
      zoneEl.appendChild(label);
    }
  });
}

function attemptPlayOnZone(uid, pi, line) {
  if (!uid) return;
  const matches = computeZoneMatches(uid, pi, line);
  if (matches.length === 1) {
    confirmAndPlay(matches[0]);
  } else if (matches.length > 1) {
    // 앞/뒤가 둘 다 있는 일반적인 경우는 drop-half가 이미 처리하므로 여기 안 옴;
    // side까지 겹치는 드문 경우에 대한 안전망으로만 남겨둔다.
    showPromptBar(true, "앞면으로 낼까요, 뒷면으로 낼까요?", matches.map((a) => ({
      label: a.faceUp ? "앞면" : "뒷면", onClick: () => submitAnswer(a),
    })));
  }
}

// chooseLine류 프롬프트는 라인 칸 전체(상대/내 스택+띠)를 클릭 대상으로 삼는다.
function attachLineClickForChooseLine(colEl, line, req) {
  if (!req || req.type !== "chooseLine") return;
  if (!(req.candidates || []).includes(line)) return;
  colEl.classList.add("winning-line");
  colEl.style.cursor = "pointer";
  colEl.addEventListener("click", () => submitAnswer(line));
}

// ----------------------------------------------------------------------------
// 로그
// ----------------------------------------------------------------------------
function cardLabel(card) {
  if (!card) return "카드";
  return `<span class="log-card" data-proto="${card.proto}" data-value="${card.value}">${protoKo(card.proto)}${card.value}</span>`;
}

const LOG_KO = {
  "ev.gameStart": () => "게임 시작",
  "ev.turnStart": (p) => `— 턴 ${p.n} · ${pName(p.p)} —`,
  "ev.draw": (p) => `${pName(p.p)}${josa(p.p)} 카드 ${p.n}장을 뽑음`,
  "ev.drawFromDeck": (p) => `${pName(p.p)}${josa(p.p)} ${pName(p.opp)}의 덱에서 카드를 가져옴`,
  "ev.refresh": (p) => `${pName(p.p)}${josa(p.p)} 리프레시합니다`,
  "ev.discardCard": (p) => `${pName(p.p)}${josa(p.p)} ${cardLabel(p.card)} 버림`,
  "ev.discardDeck": (p) => `${pName(p.p)}${josa(p.p)} 덱 전체(${p.n}장)를 버림`,
  "ev.discardToOpp": (p) => `${pName(p.p)}${josa(p.p)} 카드를 ${pName(p.opp)}의 버림더미로 보냄`,
  "ev.give": (p) => `${pName(p.from)}${josa(p.from)} ${pName(p.to)}에게 카드를 줌`,
  "ev.take": (p) => `${pName(p.to)}${josa(p.to)} ${pName(p.from)}의 카드를 가져옴`,
  "ev.takeBoard": (p) => `${pName(p.p)}${josa(p.p)} 필드의 카드를 손으로 가져옴`,
  "ev.takeBoardCard": (p) => `${pName(p.p)}${josa(p.p)} ${cardLabel(p.card)}를 손으로 가져옴`,
  "ev.playFaceDown": (p) => `${pName(p.p)}${josa(p.p)} 라인${p.line}에 카드를 뒷면으로 냄`,
  "ev.playFaceUp": (p) => `${pName(p.p)}${josa(p.p)} 라인${p.line}에 ${cardLabel(p.card)} 앞면으로 냄`,
  "ev.flipUp": (p) => `${cardLabel(p.card)} 앞면으로 뒤집힘`,
  "ev.flipDownCard": (p) => `${cardLabel(p.card)} 뒷면으로 뒤집힘`,
  "ev.delete": (p) => `${pName(p.p)}${josa(p.p)} 라인${p.line}의 ${cardLabel(p.card)} 삭제`,
  "ev.return": (p) => `${pName(p.p)}${josa(p.p)} 카드를 손으로 되돌림`,
  "ev.returnCard": (p) => `${pName(p.p)}${josa(p.p)} ${cardLabel(p.card)}를 손으로 되돌림`,
  "ev.returnToDeck": (p) => `${pName(p.p)}의 카드가 덱 위로 되돌아감`,
  "ev.returnToDeckCard": (p) => `${pName(p.p)}의 ${cardLabel(p.card)}가 덱 위로 되돌아감`,
  "ev.move": (p) => `${pName(p.p)}${josa(p.p)} 카드를 라인${p.fromLine}→라인${p.line}로 이동`,
  "ev.moveCard": (p) => `${pName(p.p)}${josa(p.p)} ${cardLabel(p.card)}를 라인${p.fromLine}→라인${p.line}로 이동`,
  "ev.reveal": (p) => `${cardLabel(p.card)} 공개`,
  "ev.revealFacedown": (p) => `뒷면 카드 공개: ${cardLabel(p.card)}`,
  "ev.revealDeck": (p) => `${pName(p.p)}${josa(p.p)} 덱을 공개`,
  "ev.revealHand": (p) => `${pName(p.p)}${josa(p.p)} 손패를 공개 (${(p.cards || []).length}장)`,
  "ev.revealTopStay": (p) => `${pName(p.p)}의 덱 맨 위 카드가 공개된 채로 유지: ${cardLabel(p.card)}`,
  "ev.reshuffle": (p) => `${pName(p.p)}${josa(p.p)} 버림더미(${p.n}장)를 덱에 셔플`,
  "ev.shuffleDeck": (p) => `${pName(p.p)}${josa(p.p)} 덱을 셔플`,
  "ev.millTop": (p) => `${pName(p.p)}의 덱 맨 위 카드가 버려짐: ${cardLabel(p.card)}`,
  "ev.controlTake": (p) => `${pName(p.p)}${josa(p.p)} 제어권 획득`,
  "ev.controlSpend": (p) => `${pName(p.p)}${josa(p.p)} 제어권 소비`,
  "ev.rearrange": (p) => `${pName(p.p)}${josa(p.p)} 프로토콜 라인${p.a}·${p.b} 교환`,
  "ev.rearrangeFull": (p) => `${pName(p.p)}${josa(p.p)} 프로토콜을 재배치`,
  "ev.swapStacks": (p) => `${pName(p.p)}${josa(p.p)} 라인${p.a}·${p.b} 스택을 통째로 교환`,
  "ev.compile": (p) => `${pName(p.p)}${josa(p.p)} ${p.proto}(라인${p.line}) 컴파일!`,
  "ev.recompile": (p) => `${pName(p.p)}${josa(p.p)} ${p.proto}(라인${p.line}) 재컴파일`,
  "ev.compileFlip": (p) => `${pName(p.p)}의 ${p.proto}(라인${p.line}) 컴파일 완료로 표시`,
  "ev.noCompile": (p) => `${pName(p.opp)}는 이번엔 컴파일 불가`,
  "ev.middleIgnored": (p) => `라인${p.line}에서 Middle 명령 무시됨`,
  "ev.middleFear": (p) => `${pName(p.p)}의 Middle 명령이 상대 효과로 무시됨`,
  "ev.stateNumber": (p) => `${pName(p.p)}${josa(p.p)} 숫자 "${p.n}"을 말함`,
  "ev.stateProtocol": (p) => `${pName(p.p)}${josa(p.p)} 프로토콜 "${p.proto}"를 말함`,
  "ev.deckShortPlay": (p) => `${pName(p.p)}의 덱이 ${p.n}장뿐이라 ${p.lines}개 라인에 다 못 냄`,
  "ev.stalemate": (p) => `턴 상한 도달 -- 무승부 판정: ${pName(p.p)} 승리`,
  "ev.win": (p) => `★ ${pName(p.p)} 승리! ★`,
};

function formatLogEntry(entry) {
  if (!entry || !entry.key) return null;
  const fn = LOG_KO[entry.key];
  if (fn) {
    try { return fn(entry.params || {}); } catch (e) { /* fallback 아래 */ }
  }
  return entry.key;
}

function renderLog(state) {
  const list = $("#log-list");
  const wasAtBottom = list.scrollTop + list.clientHeight >= list.scrollHeight - 4;
  list.innerHTML = "";
  const n1 = pName(1);
  const n2 = pName(2);
  (state.log || []).forEach((entry) => {
    const text = formatLogEntry(entry);
    if (!text) return;
    const div = document.createElement("div");
    div.className = "log-entry";
    let html = text.split(n1).join(`<span class="p1">${n1}</span>`);
    if (n2 !== n1) html = html.split(n2).join(`<span class="p2">${n2}</span>`);
    div.innerHTML = html;
    div.querySelectorAll(".log-card").forEach((el) => {
      const card = { proto: el.dataset.proto, value: Number(el.dataset.value) };
      attachCardInfoHover(el, card, true);
      el.addEventListener("click", (ev) => { ev.stopPropagation(); togglePinCard(el, card, true); });
    });
    list.appendChild(div);
  });
  if (wasAtBottom) list.scrollTop = list.scrollHeight;
}

// ----------------------------------------------------------------------------
// 상태 바 (짧은 안내)
// ----------------------------------------------------------------------------
function renderStatusBar(state) {
  const bar = $("#status-bar");
  const pending = state.pending;
  if (pending && pending.kind === "input" && pending.req.type === "action") {
    bar.innerHTML = armedUid
      ? '<span class="who">카드를 낼 곳</span>을 클릭하거나 그쪽으로 드래그하세요'
      : "카드를 클릭하거나 드래그해서 플레이하세요";
  } else {
    bar.innerHTML = "";
  }
}

// ----------------------------------------------------------------------------
// 프롬프트 바 (버튼이 필요한 결정들)
// ----------------------------------------------------------------------------
function showPromptBar(visible, html, buttons) {
  const bar = $("#prompt-bar");
  if (!visible) { bar.classList.add("hidden"); return; }
  bar.classList.remove("hidden");
  $("#prompt-text").innerHTML = html;
  const actions = $("#prompt-actions");
  actions.innerHTML = "";
  (buttons || []).forEach((b) => {
    const btn = document.createElement("button");
    btn.className = "prompt-btn" + (b.secondary ? " secondary" : "");
    btn.textContent = b.label;
    if (b.disabled) { btn.disabled = true; }
    btn.addEventListener("click", b.onClick);
    actions.appendChild(btn);
  });
}

function findCardByUid(state, uid) {
  if (uid == null) return null;
  for (const pi of [1, 2]) {
    const p = state.players[String(pi)];
    for (const c of p.hand) if (c.uid === uid) return c;
    for (const line of [1, 2, 3]) {
      for (const c of p.stacks[String(line)]) if (c.uid === uid) return c;
    }
    for (const c of p.discard) if (c.uid === uid) return c;
  }
  return null;
}

function sourceCardNote(state, req) {
  if (!req || req.sourceUid == null) return "";
  const card = findCardByUid(state, req.sourceUid);
  if (!card) return "";
  return ` <span style="color:var(--amber)">(${protoKo(card.proto)}${card.value} 카드로 인해 발동)</span>`;
}

function highlightTriggerCard(req) {
  document.querySelectorAll(".card.trigger-highlight").forEach((el) => el.classList.remove("trigger-highlight"));
  if (!req || req.sourceUid == null) return;
  const el = document.querySelector(`.card[data-uid="${req.sourceUid}"]`);
  if (el) el.classList.add("trigger-highlight");
}

function renderPrompt(state) {
  const req = state.pending.req;
  const chooser = req.chooser;
  const who = `<span class="prompt-who">${pName(chooser)}</span>${sourceCardNote(state, req)}`;
  highlightTriggerCard(req);

  // action(카드 내기) 프롬프트가 아니면, 이전 단계의 legalActions가 남아있다가
  // 드래그로 잘못 "카드 내기"가 되는 사고를 막기 위해 즉시 비운다.
  if (req.type !== "action") {
    window.__legalActions = [];
    setDropZones(null);
  }

  switch (req.type) {
    case "action":
      renderActionPrompt(state, req, who);
      break;
    case "chooseCard":
      showPromptBar(true, `${who}: ${tr(req.prompt, req.promptParams) || "카드를 선택하세요"}`,
        req.optional ? [{ label: "선택 안 함", secondary: true, onClick: () => submitAnswer(null) }] : []);
      break;
    case "chooseHandCards":
      renderChooseHandCards(state, req, who);
      break;
    case "chooseLine":
      renderChooseLinePrompt(state, req, who);
      break;
    case "chooseOption":
      renderChooseOption(req, who);
      break;
    case "yesno":
      showPromptBar(true, `${who}: ${tr(req.prompt, req.promptParams) || "예/아니오"}`, [
        { label: "예", onClick: () => submitAnswer(true) },
        { label: "아니오", secondary: true, onClick: () => submitAnswer(false) },
      ]);
      break;
    case "confirmCompile":
      showPromptBar(true, `${who}: 컴파일할 라인을 선택하세요`,
        (req.candidates || []).map((l) => ({ label: `라인 ${l} 컴파일`, onClick: () => submitAnswer(l) })));
      break;
    case "confirmRefresh":
      showPromptBar(true, `${who}: 낼 카드가 없습니다. 리프레시합니다.`, [
        { label: "확인", onClick: () => submitAnswer(true) },
      ]);
      break;
    case "choosePlayer":
      showPromptBar(true, `${who}: 제어권 -- 누구의 프로토콜을 재배치할까요?`, [
        { label: "내 프로토콜", onClick: () => submitAnswer(chooser) },
        { label: "상대 프로토콜", onClick: () => submitAnswer(chooser === 1 ? 2 : 1) },
        { label: "재배치 안 함", secondary: true, onClick: () => submitAnswer(null) },
      ]);
      break;
    case "rearrange":
      renderRearrange(state, req, who);
      break;
    default:
      showPromptBar(true, `${who}: ${tr(req.prompt, req.promptParams) || req.type}`, [
        { label: "확인", onClick: () => submitAnswer(true) },
        { label: "취소", secondary: true, onClick: () => submitAnswer(null) },
      ]);
  }
}

function renderActionPrompt(state, req, who) {
  fetch(`/api/legal_actions/${gameId}/${req.chooser}`).then((r) => r.json()).then((acts) => {
    window.__legalActions = acts;
    const canRefresh = acts.some((a) => a.kind === "refresh");
    if (canRefresh) {
      showPromptBar(true, `${who}: 낼 카드가 없으면 리프레시하세요`,
        [{ label: "리프레시", onClick: () => submitAnswer({ kind: "refresh" }) }]);
    } else {
      showPromptBar(false);
    }
    setDropZones(armedUid);
    renderHand(state);
  });
}

function renderChooseLinePrompt(state, req, who) {
  showPromptBar(true, `${who}: ${tr(req.prompt, req.promptParams) || "라인을 선택하세요"} (밝게 표시된 라인을 클릭하세요)`, []);
}

function renderChooseHandCards(state, req, who) {
  const min = req.min ?? req.count ?? 0;
  const count = req.count ?? 0;
  window.__handPick = window.__handPick || [];
  const picked = window.__handPick;
  const canConfirm = picked.length >= min;
  const hint = canConfirm ? "" : `<div class="prompt-hint">최소 ${min}장은 선택해야 확인할 수 있어요</div>`;
  showPromptBar(true,
    `${who}: ${tr(req.prompt, req.promptParams) || "카드를 선택하세요"} (${picked.length}/${count}, 최소 ${min})${hint}`,
    [{ label: "확인", disabled: !canConfirm, onClick: () => {
        if (!canConfirm) return;
        const v = picked.slice(); window.__handPick = []; submitAnswer(v);
      } }]);
  renderHand(state);
}

function renderChooseOption(req, who) {
  const cands = req.candidates || [];
  const labels = req.labels || {};
  const buttons = cands.map((v) => ({ label: labels[v] || protoKo(String(v)), onClick: () => submitAnswer(v) }));
  if (req.optional) buttons.push({ label: "선택 안 함", secondary: true, onClick: () => submitAnswer(null) });
  showPromptBar(true, `${who}: ${tr(req.prompt, req.promptParams) || "선택하세요"}`, buttons);
}

function renderRearrange(state, req, who) {
  if (!rearrangeOrder) rearrangeOrder = [1, 2, 3];
  const protos = req.protocols || {};
  const mustChange = req.mustChange !== false; // 기본값: 카드 효과는 변경 강제
  const changed = rearrangeOrder.some((v, i) => v !== i + 1);
  const blocked = mustChange && !changed;
  const currentText = [1, 2, 3].map((slot) => protoKo(protos[rearrangeOrder[slot - 1]])).join(" · ");
  const hint = blocked ? '<div class="prompt-hint">최소 한 곳은 위치를 바꿔야 확정할 수 있어요</div>' : "";
  const buttons = [{ label: "확정", disabled: blocked, onClick: () => {
      if (blocked) return;
      const o = { 1: rearrangeOrder[0], 2: rearrangeOrder[1], 3: rearrangeOrder[2] };
      rearrangeOrder = null; rearrangeFirstPick = null;
      submitAnswer(o);
    } }];
  if (!mustChange) {
    buttons.push({ label: "건너뛰기", secondary: true, onClick: () => {
        rearrangeOrder = null; rearrangeFirstPick = null;
        submitAnswer({ 1: 1, 2: 2, 3: 3 });
      } });
  }
  showPromptBar(true,
    `${who}: 필드에서 바꿀 두 라인의 프로토콜을 순서대로 클릭하세요` +
    `<div style="margin-top:6px;color:var(--text-mid);font-size:12px">현재 순서: ${currentText}</div>${hint}`,
    buttons);
}

// ----------------------------------------------------------------------------
// 손패 카드 선택 가능 여부 + 클릭 핸들러
// ----------------------------------------------------------------------------
function isHandCardSelectable(req, card) {
  if (!req) return false;
  if (req.type === "action") return (window.__legalActions || []).some((a) => a.kind === "play" && a.uid === card.uid);
  if (req.type === "chooseCard" && req.fromHand) return (req.candidates || []).includes(card.uid);
  if (req.type === "chooseHandCards") return true;
  return false;
}

function handleHandCardClick(card, req) {
  if (req.type === "chooseHandCards") {
    window.__handPick = window.__handPick || [];
    const i = window.__handPick.indexOf(card.uid);
    const max = req.count ?? Infinity;
    if (i >= 0) {
      window.__handPick.splice(i, 1);
    } else if (window.__handPick.length < max) {
      window.__handPick.push(card.uid);
    }
    // max에 이미 도달했는데 새 카드를 클릭한 경우는 조용히 무시 (교체하려면 먼저 해제).
    renderPrompt(lastState);
    return;
  }
  if (req.type === "chooseCard") { submitAnswer(card.uid); return; }
  if (req.type === "action") {
    armedUid = armedUid === card.uid ? null : card.uid;
    render(lastState);
  }
}

// ----------------------------------------------------------------------------
// 승리 오버레이
// ----------------------------------------------------------------------------
function showWin(winner) {
  $("#win-title").textContent = `${pName(winner).toUpperCase()} COMPILED.`;
  $("#win-overlay").classList.remove("hidden");
}

// ----------------------------------------------------------------------------
// 카드 도감
// ----------------------------------------------------------------------------
let codexSet = "main1"; // "main1"(=main1+aux1) | "main2"(=main2+aux2)
let codexSelectedProto = null;

$("#codex-btn").addEventListener("click", openCodex);
$("#codex-back-btn").addEventListener("click", () => {
  $("#codex-screen").classList.add("hidden");
  $("#setup-screen").classList.remove("hidden");
});

document.querySelectorAll("#codex-set-select [data-cset]").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("#codex-set-select [data-cset]").forEach((b) => b.classList.remove("selected"));
    btn.classList.add("selected");
    codexSet = btn.dataset.cset;
    codexSelectedProto = null;
    renderCodexList();
    selectFirstCodexProto();
  });
});

function selectFirstCodexProto() {
  const first = (PROTO.list || []).find((p) => codexGroupOf(p) === codexSet);
  if (first) {
    selectCodexProto(first);
  } else {
    $("#codex-banner").innerHTML = "";
    $("#codex-cards").innerHTML = "";
  }
}

function openCodex() {
  $("#setup-screen").classList.add("hidden");
  $("#codex-screen").classList.remove("hidden");
  renderCodexList();
  selectFirstCodexProto();
}

function codexGroupOf(protoId) {
  const s = (PROTO.set && PROTO.set[protoId]) || "main1";
  return (s === "main1" || s === "aux1") ? "main1" : "main2";
}

function renderCodexList() {
  const listEl = $("#codex-proto-list");
  listEl.innerHTML = "";
  const subOrder = codexSet === "main1" ? ["main1", "aux1"] : ["main2", "aux2"];
  const subLabel = { main1: "MAIN 1", aux1: "AUX 1", main2: "MAIN 2", aux2: "AUX 2" };
  subOrder.forEach((sub) => {
    const protos = (PROTO.list || []).filter((p) => (PROTO.set && PROTO.set[p]) === sub
      || (sub === "main1" && !(PROTO.set && PROTO.set[p])));
    if (!protos.length) return;
    const header = document.createElement("div");
    header.className = "codex-group-title";
    header.textContent = subLabel[sub];
    listEl.appendChild(header);
    protos.forEach((protoId) => {
      const item = document.createElement("div");
      item.className = "codex-proto-item" + (protoId === codexSelectedProto ? " selected" : "");
      item.style.setProperty("--item-accent", PROTO.colors[protoId] || "");
      item.textContent = protoKo(protoId);
      item.addEventListener("click", () => selectCodexProto(protoId));
      listEl.appendChild(item);
    });
  });
}

function selectCodexProto(protoId) {
  codexSelectedProto = protoId;
  renderCodexList();

  const accent = PROTO.colors[protoId] || "#888";
  const banner = $("#codex-banner");
  banner.style.setProperty("--banner-accent", accent);
  banner.innerHTML = `
    <div class="cb-name">${protoKo(protoId)}</div>
    <div class="cb-tagline">${(PROTO.tagline && PROTO.tagline[protoId]) || ""}</div>
    <div class="cb-verbs">${(PROTO.verbs && PROTO.verbs[protoId]) || ""}</div>
  `;

  const cardsEl = $("#codex-cards");
  cardsEl.innerHTML = "";
  const values = PROTO.values[protoId] || [];
  values.forEach((value) => {
    cardsEl.appendChild(renderCodexCard(protoId, value, accent));
  });
}

function renderCodexCard(protoId, value, accent) {
  const el = document.createElement("div");
  el.className = "codex-card";
  el.style.setProperty("--card-accent", accent);
  const text = (PROTO.cardText && PROTO.cardText[`${protoId}_${value}`]) || {};
  let bands = "";
  ["top", "mid", "bot"].forEach((z) => {
    if (text[z] && text[z].length) {
      bands += `<div class="cc-band">${text[z].join(" ")}</div>`;
    } else {
      bands += `<div class="cc-band cc-band-empty"></div>`;
    }
  });
  el.innerHTML = `
    <div class="cc-header"><span>${protoKo(protoId)}</span><span class="cc-value">${value}</span></div>
    ${bands}
  `;
  return el;
}
