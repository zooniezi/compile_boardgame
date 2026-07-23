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

const $ = (sel) => document.querySelector(sel);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ----------------------------------------------------------------------------
// 셋업 화면
// ----------------------------------------------------------------------------
let chosenMode = null;

document.querySelectorAll(".mode-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".mode-btn").forEach((b) => b.classList.remove("selected"));
    btn.classList.add("selected");
    chosenMode = btn.dataset.mode;
    $("#start-btn").disabled = false;
  });
});

$("#start-btn").addEventListener("click", () => startGame(chosenMode));
$("#win-newgame").addEventListener("click", () => location.reload());
$("#new-game-btn").addEventListener("click", () => location.reload());

async function startGame(mode) {
  const res = await fetch("/api/new_game", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode: mode || "hotseat", aiSide: 2 }),
  });
  const data = await res.json();
  gameId = data.gameId;
  $("#setup-screen").classList.add("hidden");
  $("#game-screen").classList.remove("hidden");
  handleState(data.state, requestSeq);
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
    const dur = Math.max(120, (state.pending.dur || 0.3) * 1000 * 0.6);
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
  renderTurnBox(state);
  renderControlMarker(state);
  renderDeckCols(state);
  renderLinesRow(state);
  renderHand(state);
  renderLog(state);
  renderStatusBar(state);
  reattachPinnedZoom();
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
    <span class="turn-who">플레이어${state.turn}</span>의 턴 · ${phaseLabel(state.phase)}
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
    + (isUncovered ? " uncovered" : " covered");

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
  const chooser = req ? req.chooser : state.turn;
  const hand = syncHandOrder(chooser, state.players[String(chooser)].hand);

  const box = $("#hand-cards");
  box.innerHTML = "";
  hand.forEach((c) => {
    const el = document.createElement("div");
    el.className = "card hand-card";
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

function makeDropHalf(kind, label, action) {
  const half = document.createElement("div");
  half.className = `drop-half ${kind}`;
  half.textContent = label;
  half.addEventListener("click", (ev) => { ev.stopPropagation(); submitAnswer(action); });
  half.addEventListener("dragover", (ev) => { ev.preventDefault(); half.classList.add("drag-over"); });
  half.addEventListener("dragleave", () => half.classList.remove("drag-over"));
  half.addEventListener("drop", (ev) => { ev.preventDefault(); ev.stopPropagation(); submitAnswer(action); });
  return half;
}

function setDropZones(uid) {
  document.querySelectorAll(".stack-zone").forEach((zoneEl) => {
    zoneEl.classList.remove("drop-ok", "drag-over");
    zoneEl.querySelectorAll(".drop-half").forEach((h) => h.remove());
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
      zoneEl.classList.add("drop-ok");
    }
  });
}

function attemptPlayOnZone(uid, pi, line) {
  if (!uid) return;
  const matches = computeZoneMatches(uid, pi, line);
  if (matches.length === 1) {
    submitAnswer(matches[0]);
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
  return `${protoKo(card.proto)}${card.value}`;
}

const LOG_KO = {
  "ev.gameStart": () => "게임 시작",
  "ev.turnStart": (p) => `— 턴 ${p.n} · 플레이어${p.p} —`,
  "ev.draw": (p) => `플레이어${p.p}가 카드 ${p.n}장을 뽑음`,
  "ev.drawFromDeck": (p) => `플레이어${p.p}가 플레이어${p.opp}의 덱에서 카드를 가져옴`,
  "ev.refresh": (p) => `플레이어${p.p}가 리프레시합니다`,
  "ev.discardCard": (p) => `플레이어${p.p}가 ${cardLabel(p.card)} 버림`,
  "ev.discardDeck": (p) => `플레이어${p.p}가 덱 전체(${p.n}장)를 버림`,
  "ev.discardToOpp": (p) => `플레이어${p.p}가 카드를 플레이어${p.opp}의 버림더미로 보냄`,
  "ev.give": (p) => `플레이어${p.from}가 플레이어${p.to}에게 카드를 줌`,
  "ev.take": (p) => `플레이어${p.to}가 플레이어${p.from}의 카드를 가져옴`,
  "ev.takeBoard": (p) => `플레이어${p.p}가 필드의 카드를 손으로 가져옴`,
  "ev.takeBoardCard": (p) => `플레이어${p.p}가 ${cardLabel(p.card)}를 손으로 가져옴`,
  "ev.playFaceDown": (p) => `플레이어${p.p}가 라인${p.line}에 카드를 뒷면으로 냄`,
  "ev.playFaceUp": (p) => `플레이어${p.p}가 라인${p.line}에 ${cardLabel(p.card)} 앞면으로 냄`,
  "ev.flipUp": (p) => `${cardLabel(p.card)} 앞면으로 뒤집힘`,
  "ev.flipDownCard": (p) => `${cardLabel(p.card)} 뒷면으로 뒤집힘`,
  "ev.delete": (p) => `플레이어${p.p}가 라인${p.line}의 ${cardLabel(p.card)} 삭제`,
  "ev.return": (p) => `플레이어${p.p}가 카드를 손으로 되돌림`,
  "ev.returnCard": (p) => `플레이어${p.p}가 ${cardLabel(p.card)}를 손으로 되돌림`,
  "ev.returnToDeck": (p) => `플레이어${p.p}의 카드가 덱 위로 되돌아감`,
  "ev.returnToDeckCard": (p) => `플레이어${p.p}의 ${cardLabel(p.card)}가 덱 위로 되돌아감`,
  "ev.move": (p) => `플레이어${p.p}가 카드를 라인${p.fromLine}→라인${p.line}로 이동`,
  "ev.moveCard": (p) => `플레이어${p.p}가 ${cardLabel(p.card)}를 라인${p.fromLine}→라인${p.line}로 이동`,
  "ev.reveal": (p) => `${cardLabel(p.card)} 공개`,
  "ev.revealFacedown": (p) => `뒷면 카드 공개: ${cardLabel(p.card)}`,
  "ev.revealDeck": (p) => `플레이어${p.p}가 덱을 공개`,
  "ev.revealHand": (p) => `플레이어${p.p}가 손패를 공개 (${(p.cards || []).length}장)`,
  "ev.revealTopStay": (p) => `플레이어${p.p}의 덱 맨 위 카드가 공개된 채로 유지: ${cardLabel(p.card)}`,
  "ev.reshuffle": (p) => `플레이어${p.p}가 버림더미(${p.n}장)를 덱에 셔플`,
  "ev.shuffleDeck": (p) => `플레이어${p.p}가 덱을 셔플`,
  "ev.millTop": (p) => `플레이어${p.p}의 덱 맨 위 카드가 버려짐: ${cardLabel(p.card)}`,
  "ev.controlTake": (p) => `플레이어${p.p}가 Control 획득`,
  "ev.controlSpend": (p) => `플레이어${p.p}가 Control 소비`,
  "ev.rearrange": (p) => `플레이어${p.p}가 프로토콜 라인${p.a}·${p.b} 교환`,
  "ev.rearrangeFull": (p) => `플레이어${p.p}가 프로토콜을 재배치`,
  "ev.swapStacks": (p) => `플레이어${p.p}가 라인${p.a}·${p.b} 스택을 통째로 교환`,
  "ev.compile": (p) => `플레이어${p.p}가 ${p.proto}(라인${p.line}) 컴파일!`,
  "ev.recompile": (p) => `플레이어${p.p}가 ${p.proto}(라인${p.line}) 재컴파일`,
  "ev.compileFlip": (p) => `플레이어${p.p}의 ${p.proto}(라인${p.line}) 컴파일 완료로 표시`,
  "ev.noCompile": (p) => `플레이어${p.opp}는 이번엔 컴파일 불가`,
  "ev.middleIgnored": (p) => `라인${p.line}에서 Middle 명령 무시됨`,
  "ev.middleFear": (p) => `플레이어${p.p}의 Middle 명령이 상대 효과로 무시됨`,
  "ev.stateNumber": (p) => `플레이어${p.p}가 숫자 "${p.n}"을 말함`,
  "ev.stateProtocol": (p) => `플레이어${p.p}가 프로토콜 "${p.proto}"를 말함`,
  "ev.deckShortPlay": (p) => `플레이어${p.p}의 덱이 ${p.n}장뿐이라 ${p.lines}개 라인에 다 못 냄`,
  "ev.stalemate": (p) => `턴 상한 도달 -- 무승부 판정: 플레이어${p.p} 승리`,
  "ev.win": (p) => `★ 플레이어${p.p} 승리! ★`,
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
  (state.log || []).forEach((entry) => {
    const text = formatLogEntry(entry);
    if (!text) return;
    const div = document.createElement("div");
    div.className = "log-entry";
    div.innerHTML = text
      .replace(/플레이어1/g, '<span class="p1">플레이어1</span>')
      .replace(/플레이어2/g, '<span class="p2">플레이어2</span>');
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

function renderPrompt(state) {
  const req = state.pending.req;
  const chooser = req.chooser;
  const who = `<span class="prompt-who">플레이어${chooser}</span>`;

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
      showPromptBar(true, `${who}: Control -- 누구의 프로토콜을 재배치할까요?`, [
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
  $("#win-title").textContent = `PLAYER ${winner} COMPILED.`;
  $("#win-overlay").classList.remove("hidden");
}
