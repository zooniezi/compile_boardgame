// ============================================================================
// 가이드 튜토리얼 -- 챕터별 스크립트(텍스트/앵커/정답판정)를 담당한다.
// 실제 판 세팅(고정 덱/스크립트 AI/미리 배치된 보드)은 서버
// (src/game/tutorial_script.py)가 만들고, 여기는 그 위에서 "지금 어떤
// 스텝인지", "이 스텝이 원하는 조건이 지금 참인지"만 판단해서 모달/
// 하이라이트를 띄우고, submitAnswer로 나가는 값을 걸러준다.
//
// app.js가 먼저 로드되므로 gameId/lastState/requestSeq/handleState/
// findCardByUid/$ 등은 전역(같은 문서의 다른 <script>도 공유하는 스크립트
// 스코프)으로 그대로 재사용한다. app.js 쪽엔 훅 3줄만 추가했다:
//   - submitAnswer() 맨 앞: window.tutorialGate(value)
//   - render() 끝: window.tutorialOnRender(state)
//   - handleState()의 renderPrompt() 직후: window.tutorialOnRender(state) 재호출
//     (프롬프트바 버튼처럼 renderPrompt가 새로 만드는 DOM을 앵커로 삼는
//     스텝은 render() 시점엔 아직 옛 버튼이라 한 번 더 다시 적용해야 함)
// ============================================================================

const TUTORIAL_TEXT_KO = {
  welcome: "컴파일에 오신 것을 환영합니다. 짧은 실전 튜토리얼로 기본 규칙을 익혀볼게요.",
  welcome2: "당신의 목표는 상대보다 먼저 자신의 3개의 프로토콜을 컴파일하는 것입니다. 어떤 라인의 값이 10 이상이며 해당 라인에서 값이 상대보다 높다면 그 라인의 프로토콜을 컴파일할 수 있습니다.",
  lanes: "보드에는 라인이 3개 있습니다. 당신의 프로토콜은 아래쪽, 상대의 프로토콜은 위쪽에 있으며, 각 라인마다 나와 상대가 카드를 쌓아 값을 겨루는 독립된 대결입니다.",
  hand: "이건 당신의 손패입니다. 각 카드는 당신의 세 프로토콜 중 하나에 속하며 고유한 값과 명령을(상단: 지속 효과, 중단: 즉시 발동, 하단: 지속 효과) 갖습니다. 카드 위에 마우스를 올려 자세히 확인할 수 있습니다.",
  play1: "하이라이트된 '생명 4' 카드를 라인 1에 앞면으로 플레이하세요: 카드를 앞면으로 내는 행동은 카드와 일치하는 프로토콜의 라인에만 가능합니다.",
  oppFd: "상대가 라인 2에 뒷면 카드를 냈어요. 뒷면 카드는 카드의 효과가 발동되지는 않지만, 어느 라인에나 낼 수 있으며, 값은 2이고 카드의 정체는 숨겨집니다.",
  play2: "이번엔 '금속 6' 카드를 라인 1에 뒷면으로 내보세요. 뒷면으로 내면 카드 효과는 발동하지 않음에 유의하세요!",
  play3: "'생명 2' 카드를 라인 1에 앞면으로 내보세요. 이 카드는 낼 때 효과가 있어요.",
  passOpt: "'생명 2'의 효과 중 \"뒷면 카드를 뒤집을 수 있다\"는 선택 사항이에요. 선택이 필요한 효과들은 오른쪽 화면에서 결정을 내리게 될 거에요. 지금은 \"선택 안 함\"을 눌러 넘어가 볼게요.",
  control: "상대가 2개 이상의 라인들에서 나보다 값이 높아져서 제어권을 가져갔어요. 제어권을 가진 쪽은 컴파일이나 리프레시할 때 프로토콜을 재배치할 수 있습니다 -- 잠시 후 직접 겪어볼 거예요.",
  play4: "'생명 3' 카드를 라인 1에 앞면으로 내보세요. 라인 1의 값 합계가 4+2+2+3 = 11이 되어 컴파일할 수 있게 됩니다.",
  compile: "라인이 완성됐습니다! 자신의 차례가 시작했을 때, 어떤 라인의 값이 10 이상이고 해당 라인에서 상대보다 값이 높다면 컴파일이 반드시 수행됩니다. 컴파일 버튼을 눌러보세요. 해당 라인의 모든 카드가 제거되고 프로토콜이 컴파일 될 것입니다!",
  refresh: "손패가 얼마 안 남았네요. 리프레시를 하면 손패를 5장이 될 때까지 뽑습니다. 리프레시를 눌러보세요.",
  c1outro: "여기까지가 기본 흐름이에요: 카드 내기 → 값 겨루기 → 컴파일 → 리프레시. 이어서 조금 더 전략적인 상황을 하나 보여드릴게요.",
  c2intro: "이번엔 미리 짜인 상황이에요. 상대는 이미 프로토콜 2개를 컴파일했고, 남은 라인 1도 값이 10이라 다음 턴에 컴파일하면 상대가 승리합니다. 하지만 나는 라인 2·3에서 이기고 있어서 이미 제어권을 쥐고 있어요.",
  c2refresh: "제어권이 있으니 리프레시로 상대 프로토콜을 재배치해서 막을 수 있어요. 리프레시를 눌러보세요.",
  c2pick: "누구의 프로토콜을 재배치할지 물어봐요. \"상대 프로토콜\"을 선택하세요.",
  c2rearrange: "이미 컴파일된 프로토콜(라인 2 또는 3)을 상대의 라인 1로 옮기세요. 그러면 상대가 다음에 라인 1을 완성해도 이미 컴파일된 프로토콜을 다시 컴파일하는 것뿐이라 승리로 이어지지 않아요.",
  c2recompile: "보셨죠? 상대가 라인 1을 다시 컴파일했지만, 이미 컴파일했던 프로토콜이라 재컴파일로 끝났어요. 물론 재컴파일도 나쁜 것은 아닙니다. 재컴파일 시 해당 라인의 카드들은 제거되고, 재컴파일의 보상으로 상대방의 덱 맨 위 카드를 가져가게 됩니다. 하지만 당신은 승리를 막아냈습니다.",
  done: "튜토리얼을 마쳤습니다. 먼저 3개의 프로토콜을 컴파일하면 승리합니다. 이제 실전으로 가볼까요?",
};

function actionPending(state) {
  const req = state.pending && state.pending.kind === "input" ? state.pending.req : null;
  return req !== null && req.type === "action";
}

function reqIsTutorial(type) {
  return (state) => {
    const req = state.pending && state.pending.kind === "input" ? state.pending.req : null;
    return req !== null && req.type === type;
  };
}

function opponentHasFaceDown(state) {
  const p2 = state.players["2"];
  if (!p2) return false;
  return [1, 2, 3].some((line) => (p2.stacks[String(line)] || []).some((c) => !c.faceUp));
}

const TUTORIAL_STEPS = {
  1: [
    { kind: "modal", text: TUTORIAL_TEXT_KO.welcome },
    { kind: "modal", text: TUTORIAL_TEXT_KO.welcome2 },
    { kind: "modal", text: TUTORIAL_TEXT_KO.lanes, anchor: "lanes" },
    { kind: "modal", text: TUTORIAL_TEXT_KO.hand, anchor: "hand" },
    { kind: "action", text: TUTORIAL_TEXT_KO.play1, anchor: "card:Life_4", when: actionPending,
      play: { proto: "Life", value: 4, line: 1, faceUp: true } },
    { kind: "modal", text: TUTORIAL_TEXT_KO.oppFd, when: opponentHasFaceDown },
    { kind: "action", text: TUTORIAL_TEXT_KO.play2, anchor: "card:Metal_6", when: actionPending,
      play: { proto: "Metal", value: 6, line: 1, faceUp: false } },
    { kind: "action", text: TUTORIAL_TEXT_KO.play3, anchor: "card:Life_2", when: actionPending,
      play: { proto: "Life", value: 2, line: 1, faceUp: true } },
    { kind: "action", text: TUTORIAL_TEXT_KO.passOpt, anchor: "button:pass", allow: "pass",
      when: (state) => {
        const req = state.pending && state.pending.kind === "input" ? state.pending.req : null;
        return req !== null && req.type === "chooseCard" && req.optional === true;
      } },
    { kind: "modal", text: TUTORIAL_TEXT_KO.control, when: (state) => state.control === 2 },
    { kind: "action", text: TUTORIAL_TEXT_KO.play4, anchor: "card:Life_3", when: actionPending,
      play: { proto: "Life", value: 3, line: 1, faceUp: true } },
    { kind: "action", text: TUTORIAL_TEXT_KO.compile, anchor: "button:compile", allow: "any",
      when: reqIsTutorial("confirmCompile") },
    { kind: "action", text: TUTORIAL_TEXT_KO.refresh, anchor: "button:refresh", allow: "refresh",
      when: actionPending },
    { kind: "modal", text: TUTORIAL_TEXT_KO.c1outro },
  ],
  2: [
    { kind: "modal", text: TUTORIAL_TEXT_KO.c2intro },
    { kind: "action", text: TUTORIAL_TEXT_KO.c2refresh, anchor: "button:refresh", allow: "refresh",
      when: actionPending },
    { kind: "action", text: TUTORIAL_TEXT_KO.c2pick, anchor: "board", allow: "player", pick: 2,
      when: reqIsTutorial("choosePlayer") },
    { kind: "action", text: TUTORIAL_TEXT_KO.c2rearrange, anchor: "board", allow: "rearrange",
      when: reqIsTutorial("rearrange") },
    { kind: "modal", text: TUTORIAL_TEXT_KO.c2recompile,
      when: (state) => state.pending !== null && state.pending.kind === "input" },
    { kind: "modal", text: TUTORIAL_TEXT_KO.done },
  ],
};

// ----------------------------------------------------------------------------
// 정답 판정 (Lua Script.stepAllows 이식)
// ----------------------------------------------------------------------------
function stepAllows(step, value, state) {
  if (step.play) {
    if (!value || typeof value !== "object" || value.kind !== "play") return false;
    const card = findCardByUid(state, value.uid);
    return !!card && card.proto === step.play.proto && Number(card.value) === Number(step.play.value)
      && value.line === step.play.line && (value.faceUp === true) === step.play.faceUp;
  }
  switch (step.allow) {
    case "pass":
      return value === null || value === undefined;
    case "refresh":
      return value !== null && typeof value === "object" && value.kind === "refresh";
    case "player":
      return typeof value === "number" && (step.pick === undefined || value === step.pick);
    case "rearrange": {
      if (!value || typeof value[1] !== "number") return false;
      const req = state.pending && state.pending.kind === "input" ? state.pending.req : null;
      const target = req && req.target;
      const p = target != null ? state.players[String(target)] : null;
      return !!p && p.compiled[String(value[1])] === true;
    }
    case "any":
      return true;
    default:
      return false;
  }
}

// ----------------------------------------------------------------------------
// 앵커 -> DOM 엘리먼트 목록 (여러 개를 동시에 하이라이트하는 앵커도 있음,
// 예: "lanes"는 라인 3개 전부).
// ----------------------------------------------------------------------------
function resolveTutorialAnchors(anchor, state) {
  if (!anchor) return [];
  if (anchor === "board") {
    const el = document.querySelector(".board");
    return el ? [el] : [];
  }
  if (anchor === "lanes") {
    return [1, 2, 3]
      .map((n) => document.querySelector(`.line-col[data-line="${n}"]`))
      .filter(Boolean);
  }
  if (anchor === "hand") {
    const el = $("#hand-cards");
    return el ? [el] : [];
  }
  if (anchor.startsWith("card:")) {
    const m = anchor.match(/^card:([A-Za-z]+)_(\d+)$/);
    if (!m) return [];
    const [, proto, value] = m;
    const req = state.pending && state.pending.kind === "input" ? state.pending.req : null;
    const chooser = (req && req.chooser) || 1;
    const hand = (state.players[String(chooser)] || {}).hand || [];
    const card = hand.find((c) => c.proto === proto && Number(c.value) === Number(value));
    if (!card) return [];
    const el = document.querySelector(`.card[data-uid="${card.uid}"]`);
    return el ? [el] : [];
  }
  if (anchor.startsWith("lane:")) {
    const n = anchor.split(":")[1];
    const el = document.querySelector(`.line-col[data-line="${n}"]`);
    return el ? [el] : [];
  }
  if (anchor.startsWith("button:")) {
    const key = anchor.split(":")[1];
    const includesText = { compile: "컴파일", refresh: "리프레시", pass: "선택 안 함" }[key];
    if (!includesText) return [];
    const btns = document.querySelectorAll("#prompt-actions .prompt-btn");
    for (const b of btns) if (b.textContent.includes(includesText)) return [b];
    return [];
  }
  return [];
}

// ----------------------------------------------------------------------------
// 진행 상태 + 렌더 훅
// ----------------------------------------------------------------------------
let tutorialChapter = null;
let tutorialStepIdx = 0;
let tutorialArmed = false;

function currentTutorialStep() {
  if (!tutorialChapter) return null;
  return TUTORIAL_STEPS[tutorialChapter][tutorialStepIdx] || null;
}

window.tutorialActive = function tutorialActive() {
  return tutorialChapter !== null;
};

// 화면 중앙을 가리는 모달 대신, 하단 안내 박스 하나로 모달/액션 스텝을
// 전부 통일해서 보여준다. 모달성 스텝만 "다음" 버튼이 같이 뜬다(액션
// 스텝은 실제 게임 UI 조작으로 저절로 넘어가므로 버튼이 필요 없음).
function hideTutorialHint() {
  $("#tutorial-hint-box").classList.add("hidden");
  $("#tutorial-hint-next").classList.add("hidden");
  document.querySelectorAll(".tutorial-highlight").forEach((el) => el.classList.remove("tutorial-highlight"));
}

function showTutorialHintAndHighlight(step, state) {
  $("#tutorial-hint-text").textContent = step.text;
  $("#tutorial-hint-box").classList.remove("hidden");
  $("#tutorial-hint-next").classList.toggle("hidden", step.kind !== "modal");
  document.querySelectorAll(".tutorial-highlight").forEach((el) => el.classList.remove("tutorial-highlight"));
  resolveTutorialAnchors(step.anchor, state).forEach((el) => el.classList.add("tutorial-highlight"));
}

window.tutorialOnRender = function tutorialOnRender(state) {
  if (!tutorialChapter) return;
  const step = currentTutorialStep();
  if (!step) return;
  if (!tutorialArmed) {
    const when = step.when || (() => true);
    if (!when(state)) return;
    tutorialArmed = true;
  }
  showTutorialHintAndHighlight(step, state);
};

window.tutorialGate = function tutorialGate(value) {
  if (!tutorialChapter) return true;
  const step = currentTutorialStep();
  if (!step) return true;
  // 안내 문구(모달성 스텝)가 떠 있는 동안엔 실제 게임 입력을 전부 막는다
  // -- "다음" 버튼으로만 넘어간다. 화면을 가리는 오버레이가 없어졌으니
  // 이게 유일한 방어선.
  if (step.kind === "modal") return false;
  if (!tutorialArmed) return false;
  if (!stepAllows(step, value, lastState)) return false;
  advanceTutorialStep();
  return true;
};

function advanceTutorialStep() {
  tutorialStepIdx += 1;
  tutorialArmed = false;
  hideTutorialHint();
  const steps = TUTORIAL_STEPS[tutorialChapter];
  if (tutorialStepIdx >= steps.length) {
    const chapters = Object.keys(TUTORIAL_STEPS).map(Number).sort((a, b) => a - b);
    const nextIdx = chapters.indexOf(tutorialChapter) + 1;
    if (nextIdx < chapters.length) {
      startTutorialChapter(chapters[nextIdx]);
    } else {
      tutorialChapter = null;
      location.reload();
    }
  } else if (lastState) {
    window.tutorialOnRender(lastState);
  }
}

async function startTutorialChapter(n) {
  tutorialChapter = n;
  tutorialStepIdx = 0;
  tutorialArmed = false;
  // 튜토리얼은 설정 화면(체크박스)을 거치지 않고 바로 시작하므로
  // confirmPlayEnabled가 기본값(true)에 머물러 있다 -- 카드를 낼 때마다
  // "예/아니오" 재확인이 뜨면 안내 흐름이 끊기니 여기서 꺼둔다.
  confirmPlayEnabled = false;
  const res = await fetch("/api/tutorial/new", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ chapter: n }),
  });
  const data = await res.json();
  gameId = data.gameId;
  $("#setup-screen").classList.add("hidden");
  $("#play-setup-screen").classList.add("hidden");
  $("#draft-screen").classList.add("hidden");
  $("#game-screen").classList.remove("hidden");
  handleState(data.state, ++requestSeq);
}

document.addEventListener("DOMContentLoaded", () => {
  const startBtn = $("#goto-tutorial-btn");
  if (startBtn) startBtn.addEventListener("click", () => startTutorialChapter(1));

  $("#tutorial-hint-next").addEventListener("click", () => {
    if (currentTutorialStep() && currentTutorialStep().kind === "modal") advanceTutorialStep();
  });
});
