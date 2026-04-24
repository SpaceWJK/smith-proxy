"""
cql_parallel.py - CQL 병렬 실행 유틸리티

ThreadPoolExecutor를 사용하여 N개 callable을 병렬 실행하고
첫 번째 non-None 결과를 반환한다.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeoutError
import logging

_log = logging.getLogger(__name__)


def run_parallel_cql(callables, timeout_total=5.0):
    """N개 callable 병렬 실행, 첫 non-None 결과 반환.

    Parameters
    ----------
    callables    : list of zero-argument callables (각 callable은 CQL 실행 후 dict 또는 None 반환)
    timeout_total: 전체 대기 최대 시간(초). 기본 5.0초.

    Returns
    -------
    첫 번째 non-None 결과, 또는 모두 None/타임아웃이면 None.
    """
    if not callables:
        return None
    # len==1 fast path 없음 — timeout_total 일관 적용

    executor = ThreadPoolExecutor(max_workers=len(callables))
    futures = [executor.submit(fn) for fn in callables]
    result = None
    try:
        for future in as_completed(futures, timeout=timeout_total):
            try:
                r = future.result()
                if r is not None:
                    result = r
                    break
            except Exception as e:
                _log.debug("[cql_parallel] future error: %s", e)
    except FuturesTimeoutError:
        _log.debug("[cql_parallel] timeout %.1fs — None 반환", timeout_total)

    for f in futures:
        f.cancel()
    executor.shutdown(wait=False)  # RUNNING thread는 HTTP timeout=5s 내 종료
    return result
