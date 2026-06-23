"""
Bel Acres Golf and Country Club — CPS Golf 직접 API 사용.

기존엔 Cloudflare Bot Fight Mode 때문에 FlareSolverr+Playwright 가 필요했으나,
cps_golf.py 의 직접 API 가 curl_cffi 브라우저 임퍼소네이트로 Cloudflare 를 우회하므로
별도 처리 없이 동일 스크래퍼를 그대로 사용한다.

(만약 Cloudflare 정책 강화로 curl_cffi 우회가 실패하면, 이 파일을 git 히스토리의
 이전 FlareSolverr 버전으로 되돌리면 됨.)
"""
from scrapers.cps_golf import scrape  # noqa: F401

__all__ = ["scrape"]
