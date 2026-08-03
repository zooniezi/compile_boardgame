"""자기대국/아레나 병렬 실행 공용 헬퍼 (260803_병렬화_plan.md).

이 파일 자체는 게임 로직을 전혀 모른다 -- "작업 목록을 워커 여러 개에
나눠 돌리고 결과를 모은다"는 배관만 담당한다. `scripts/arena.py`가 이걸
불러 쓰고, 나중에 자기대국 데이터 생성 스크립트도 그대로 재사용할 수
있게 분리해뒀다.

Windows는 `multiprocessing`이 "spawn" 방식이라(리눅스의 "fork"와 다름)
워커로 넘기는 함수/인자가 전부 **피클 가능**해야 한다 -- 람다나 함수 안에
정의된 클로저는 안 되고, 최상위(모듈 레벨) 함수/클래스나
`functools.partial(클래스, **kwargs)`만 가능하다.
"""

import os
import pickle
from concurrent.futures import ProcessPoolExecutor, as_completed


def check_picklable(obj, name):
    """obj를 병렬 워커로 넘기기 전에 미리 피클 가능한지 확인한다 --
    실패하면 워커 스폰 후 알아보기 힘든 에러 대신 여기서 바로 명확하게
    알려준다."""
    try:
        pickle.dumps(obj)
    except (pickle.PicklingError, TypeError, AttributeError) as e:
        raise TypeError(
            f"{name}({obj!r})을 병렬 워커로 넘길 수 없어요(피클 불가) -- "
            f"람다나 함수 안 클로저 대신 functools.partial(클래스, **kwargs)나 "
            f"최상위(모듈 레벨) 클래스/함수를 쓰세요. (원인: {e})"
        ) from e


def limit_blas_threads():
    """numpy가 내부적으로 띄우는 BLAS(OpenBLAS/MKL) 스레드를 1개로 제한한다.

    프로세스 풀로 이미 병렬화하는데 프로세스 하나 안에서 numpy가 또 여러
    스레드를 쓰면, 워커 수 x BLAS 스레드 수가 코어 수를 훌쩍 넘겨 서로
    경쟁하느라(오버섭스크립션) 기대한 속도 향상이 안 나올 수 있다. numpy를
    import하기 전에 설정해야 효과가 있으므로 워커 initializer 맨 앞에서만
    쓴다."""
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS"):
        os.environ[var] = "1"


def resolve_n_workers(n_workers):
    """"auto"면 코어 수-1(최소 1, OS/다른 작업용으로 하나는 남겨둠),
    정수면 최소 1로 잘라서 그대로 쓴다."""
    if n_workers == "auto":
        return max(1, (os.cpu_count() or 2) - 1)
    return max(1, int(n_workers))


def run_parallel(work_items, worker_fn, init_fn=None, init_args=(), n_workers=1,
                  on_result=None):
    """work_items(리스트)를 worker_fn(item)에 나눠 돌리고, 결과 리스트를
    반환한다(제출 순서가 아니라 완료 순서로 모임 -- 최종 리스트 순서에
    의존하는 로직을 만들면 안 됨, on_result로 순서 무관하게 집계할 것).

    n_workers<=1이면 프로세스 풀을 아예 안 띄우고 그냥 순차 실행한다(소규모
    호출에서 프로세스 스폰 오버헤드조차 피하기 위함) -- 이 경우
    init_fn(*init_args)를 호출부와 같은(메인) 프로세스에서 한 번 불러
    병렬 경로와 동일한 준비를 해준다.

    n_workers>1이면 ProcessPoolExecutor(initializer=init_fn,
    initargs=init_args)로 **워커 프로세스마다 init_fn을 한 번씩만** 호출
    하고(무거운 값을 매 작업마다 다시 피클링/전송하지 않기 위함),
    work_items를 분산 처리한다. worker_fn은 init_fn이 그 워커 프로세스의
    모듈 전역에 남겨둔 값을 읽어서 쓰는 식으로 짜여 있어야 한다(둘 다
    같은 모듈의 최상위 함수여야 전역 공유가 됨). 완료되는 대로
    on_result(result)를 호출한다(진행 출력용)."""
    n_workers = resolve_n_workers(n_workers)

    if n_workers <= 1:
        if init_fn is not None:
            init_fn(*init_args)
        results = []
        for item in work_items:
            r = worker_fn(item)
            results.append(r)
            if on_result is not None:
                on_result(r)
        return results

    results = []
    with ProcessPoolExecutor(max_workers=n_workers, initializer=init_fn,
                              initargs=init_args) as ex:
        futures = [ex.submit(worker_fn, item) for item in work_items]
        for fut in as_completed(futures):
            r = fut.result()
            results.append(r)
            if on_result is not None:
                on_result(r)
    return results
