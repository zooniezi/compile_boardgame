# Compy

### The compy(COMpile board game implemented in PYthon) game 

**Compy**는 실물 보드게임 **Compile**을 Python으로 구현한 프로젝트입니다.
본 프로젝트는 Michael Yang이 디자인한 실물 보드게임 **[Compile](https://boardgamegeek.com/boardgame/406652/compile-main-1)**을 기반으로 제작한 프로젝트며, 원작의 공식 출시 및 제작사와 어떠한 제휴, 승인 또는 공식적인 연관 관계도 없습니다.
본 프로젝트는 개인적인 흥미와 학습을 위해 비상업적인 목적으로 진행하였으며, 어떠한 수익도 창출되지 않습니다.
원작의 게임 디자인, 아트워크, 카드 디자인 및 기타 관련 지적재산권은 각각의 원작자 및 권리 보유자에게 있습니다.

---

Compile은 2명의 플레이어가 각자의 카드를 사용해 3개의 라인에서 경쟁하는 **Lane Battler** 장르의 보드게임입니다. 각 라인에서 자신의 카드를 활용해 상대보다 우위를 점하고, 총 3개의 라인을 먼저 컴파일하는 플레이어가 승리합니다.

이 프로젝트의 목표는 실물 보드게임의 복잡한 카드 효과와 게임 규칙을 Python으로 구현하고, 실제 플레이어와 AI가 게임을 진행할 수 있는 게임 엔진을 구축하는 것입니다.

현재 Flask를 기반으로 웹 버전을 구현하여 **PythonAnywhere에 배포**했으며, 브라우저에서 직접 게임을 플레이할 수 있습니다.

---

## 🎮 Play Online

👉 **[Compile Board Game 플레이하기](https://compileboardgame.pythonanywhere.com/)**

별도의 설치 없이 웹 브라우저에서 게임을 플레이할 수 있습니다.

---

## 🎲 About Compile

Compile은 2명의 플레이어가 서로의 덱을 구축하고, 3개의 라인에서 카드를 플레이하며 주도권을 겨루는 보드게임입니다.

각 카드에는 고유한 점수와 다양한 효과가 존재하며, 카드의 효과는 다음과 같은 방식으로 다양한 효과들의 집합으로 구성됩니다.

* **Passive**: 카드가 특정 상태로 존재하는 동안 지속적으로 적용되는 효과
* **Play**: 카드를 플레이하거나 특정 상황에서 즉시 발동하는 효과
* **Start / Finish**: 턴의 시작 또는 종료 시점에 발동하는 효과
* **On Covered**: 다른 카드에 의해 자신의 카드가 가려질 때 발동하는 효과
* **Reactive**: 특정 게임 이벤트가 발생한 이후 반응하여 발동하는 효과

이러한 카드 효과들이 서로 연쇄적으로 작용하기 때문에, 단순히 카드를 내고 효과를 실행하는 것만으로는 게임 구현에 제약이 발생.

예를 들어 하나의 카드 효과가 다른 카드 효과를 연쇄적으로 발생시키고, 그 과정에서 플레이어의 추가적인 선택이 필요한 상황이 발생할 수 있습니다.

이 프로젝트는 이러한 복잡한 게임 흐름을 안정적으로 처리하고, 실제 플레이어와 AI가 동일한 게임 환경에서 게임을 진행할 수 있도록 게임 엔진을 설계하는 데 중점을 두었습니다.

---

## 🧩 Core Architecture

### Thread + Queue 기반 게임 진행 구조

카드 효과를 실행하는 도중 플레이어의 입력을 기다려야 하는 상황을 처리하기 위해 **Thread + Queue 기반의 게임 진행 구조**를 사용합니다.

게임 엔진은 별도의 실행 흐름에서 게임을 진행하다가 플레이어의 선택이 필요한 시점에 실행을 일시적으로 중단합니다.

이후 웹 애플리케이션을 통해 플레이어의 입력을 전달받으면 게임 엔진이 다시 실행을 이어갑니다.

```text
Game Thread                         Web / Main Thread

게임 진행
    │
    ├── 플레이어 입력 요청 ──────────→ _out_queue
    │                                      │
    │                                      ↓
    │                                플레이어가 선택
    │                                      │
    │                                      ↓
    │←──────── 선택 결과 전달 ───────── _in_queue
    │
    └── 게임 진행 재개
```

이를 통해 카드 효과가 실행되는 도중 플레이어의 입력이 필요한 복잡한 상황에서도 게임의 흐름을 자연스럽게 중단하고 다시 재개할 수 있도록 구성했습니다.

### Player와 AI의 동일한 인터페이스

게임 엔진에서는 `prompt()`를 통해 플레이어의 선택을 요청합니다.

실제 플레이어와 AI는 서로 다른 방식으로 선택을 처리하지만, 게임 엔진과 카드 효과에서는 동일한 인터페이스를 사용합니다.

* **실제 플레이어**: Queue를 통해 웹 브라우저의 입력을 기다림
* **AI 플레이어**: AI 의사결정 로직을 통해 선택을 반환
* **테스트용 AI**: 미리 정의된 선택을 반환

이를 통해 카드 효과와 게임 로직은 입력을 처리하는 주체가 실제 플레이어인지 AI인지 직접 알 필요가 없도록 구성했습니다.

---

## 🏗️ Game Engine Structure

게임 엔진은 크게 **게임 실행 구조**, **기본 게임 동작**, **게임 진행 로직**으로 구성됩니다.

### 1. Game Execution

게임의 실행과 중단, 재개를 담당합니다.

* `start()`
* `step()`
* `answer()`
* `advance_anim()`
* `_run_loop()`

플레이어의 입력을 기다리는 동안 게임을 일시적으로 중단하고, 입력이 전달되면 다시 게임을 진행할 수 있도록 합니다.

### 2. Primitives

게임에서 사용되는 기본적인 동작을 제공합니다.

예:

* 카드 드로우 및 버리기
* 카드 제거 및 반환
* 카드 뒤집기
* 카드 이동
* 라인 점수 계산
* 현재 승리 중인 라인 판정

이러한 기본 동작들은 여러 카드 효과에서 공통적으로 사용됩니다.

### 3. Game Flow

기본 동작들을 조합하여 실제 게임을 진행합니다.

```text
게임 시작
    ↓
Control
    ↓
Compile 판정
    ↓
플레이어 행동
    ↓
캐시 정리
    ↓
턴 종료
    ↓
다음 턴
```

주요 게임 진행 메서드는 다음과 같습니다.

* `play_card()`
* `perform_action()`
* `do_compile()`
* `spend_control()`
* `run_turn()`
* `_game_loop()`

이를 통해 게임의 기본 동작과 카드 효과, 전체 게임 흐름을 분리하여 관리할 수 있도록 구성했습니다.

---

## 🃏 Card Definition System

카드 효과는 `carddefs.py`의 `DEFS` 딕셔너리를 중심으로 관리합니다.

각 카드는 고유한 카드 정의를 가지며, 다양한 상황에서 발동하는 효과를 콜백 함수로 정의합니다.

카드 효과는 다음과 같은 유형으로 구성됩니다.

```text
DEFS
 └── Card
      ├── passive
      ├── play
      ├── start
      ├── finish
      ├── can
      ├── onCovered
      └── reactive
```

이를 통해 카드마다 게임 엔진의 코드를 직접 수정하지 않고도 새로운 카드 효과를 추가할 수 있도록 설계했습니다.

또한 여러 카드에서 반복적으로 사용되는 효과 조합은 별도의 헬퍼 함수로 추상화하여 카드 정의 코드의 중복을 줄였습니다.

전체적인 구조는 다음과 같습니다.

```text
Engine Primitives
       ↓
Card Helpers
       ↓
Individual Card Effects
       ↓
DEFS
```

이러한 구조를 통해 카드 효과가 많아지더라도 게임 엔진과 카드 정의를 독립적으로 관리할 수 있도록 구성했습니다.

---

## 🧪 Testing

게임 엔진과 카드 효과의 안정성을 검증하기 위해 `pytest`를 사용하여 테스트 코드를 작성했습니다.

테스트는 크게 다음과 같은 영역으로 구성됩니다.

### Card / Engine Logic

개별 카드와 게임 규칙이 의도한 대로 동작하는지 검증합니다.

예:

* 카드가 올바르게 뒤집히는지
* 카드가 제거되는지
* 점수 계산이 정확한지
* 특정 카드 효과가 올바른 대상을 선택하는지
* 카드 효과가 예상한 상태 변화를 발생시키는지

### Coroutine / Queue

게임 실행이 올바르게 중단되고 재개되는지 검증합니다.

예:

* 애니메이션 대기 상태에서 올바르게 멈추는지
* 플레이어의 입력을 기다릴 때 게임이 멈추는지
* 플레이어의 응답 이후 게임이 정상적으로 재개되는지
* AI 플레이어는 불필요하게 대기하지 않는지

### Full Game

실제 게임 루프 전체를 실행하여 게임이 정상적으로 종료될 수 있는지 검증합니다.

테스트에서는 `assert`를 사용하여 예상한 상태와 실제 결과가 일치하는지 확인합니다.

```python
assert expected == actual
```

단순히 코드가 에러 없이 실행되는지만 확인하는 것이 아니라, 게임 상태의 변화와 계산 결과가 정확한지 검증하는 것을 목표로 합니다.

---

## 🌐 Web Version

게임 엔진을 실제로 플레이할 수 있도록 **Flask 기반 웹 애플리케이션**을 구현했습니다.

웹 애플리케이션은 게임 엔진과 브라우저 사이에서 플레이어의 입력과 게임 상태를 전달하는 역할을 합니다.

```text
Browser
   │
   │ Player Input
   ↓
Flask Web Application
   │
   ↓
Game Engine
   │
   │ Game State / Prompt
   ↓
Flask Web Application
   │
   ↓
Browser
```

웹 버전에서는 다음과 같은 기능을 제공합니다.

* 게임 설정
* 2인 Hotseat 플레이
* AI와의 대전
* 카드 선택 및 플레이
* 카드 효과에 따른 사용자 입력
* 게임 진행 상황 및 로그 확인
* 카드 정보 확인
* 드래그 앤 드롭 기반 카드 조작
* 카드 Hover 및 정보 확인
* 필드에서의 카드 재배치

현재 웹 버전은 **PythonAnywhere를 통해 실제 서비스로 배포**되어 있습니다.

### Play Online

👉 **https://compileboardgame.pythonanywhere.com/**

---

## 🛠️ Tech Stack

* **Language**: Python
* **Web Framework**: Flask
* **Testing**: pytest
* **Frontend**: HTML / CSS / JavaScript
* **Deployment**: PythonAnywhere

---

## 📁 Project Structure

```text
compile_boardgame/
├── src/
│   ├── engine.py
│   ├── carddefs.py
│   └── ...
│
├── web/
│   └── app.py
│
├── tests/
│   ├── test_carddefs_*.py
│   ├── test_coroutine.py
│   ├── test_full_game.py
│   └── ...
│
└── README.md
```

* `src/` : 게임 엔진 및 카드 효과 등 핵심 게임 로직
* `web/` : Flask 기반 웹 애플리케이션
* `tests/` : 게임 엔진 및 카드 효과 테스트

---

## 🚀 Run Locally

### 1. Clone the repository

```bash
git clone https://github.com/zooniezi/compile_boardgame.git
cd compile_boardgame
```

### 2. Create a virtual environment

```bash
python -m venv venv
```

Windows:

```bash
venv\Scripts\activate
```

macOS / Linux:

```bash
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Run the Flask application

```bash
python web/app.py
```

실행 후 터미널에 표시된 로컬 서버 주소로 접속하면 웹 브라우저에서 게임을 플레이할 수 있습니다.

---

## 🔮 Future Plans

향후에는 보다 향상된 플레이 경험을 제공하기 위해 AI 플레이어의 의사결정 로직을 확장할 계획입니다.

게임 규칙을 기반으로 한 **휴리스틱 모델**을 비롯하여 **ISMCTS (Information Set Monte Carlo Tree Search)** 및 **강화학습 (Reinforcement Learning)** 기반의 AI 플레이어를 추가하여, 다양한 AI 모델이 동일한 게임 환경에서 플레이할 수 있도록 발전시키는 것을 목표로 하고 있습니다.
