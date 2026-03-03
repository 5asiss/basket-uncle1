import os
from typing import Optional

import cloudinary
import cloudinary.api


def _init_cloudinary_from_env() -> None:
    """
    CLOUDINARY_URL 환경변수를 기준으로 Cloudinary 설정을 초기화한다.

    - 앱(main)과 동일하게 CLOUDINARY_URL 하나만 쓰는 형태를 그대로 따른다.
    - 별도 값이 없으면 곧바로 예외를 던져 사용자가 설정을 확인하도록 유도한다.
    """
    cloudinary_url = os.getenv("CLOUDINARY_URL", "").strip()
    if not cloudinary_url:
        raise RuntimeError(
            "CLOUDINARY_URL 환경변수가 설정되어 있지 않습니다. "
            "Cloudinary 대시보드의 Environment variable 값을 확인해서 "
            "CLOUDINARY_URL 로 등록한 뒤 다시 실행하세요."
        )
    cloudinary.config(cloudinary_url=cloudinary_url, secure=True)


def delete_detail_images_by_prefix(prefix: str = "basket-uncle/detail/", max_results: int = 100) -> None:
    """
    Cloudinary에서 특정 prefix 를 가진 업로드 리소스를 모두 삭제한다.

    - prefix 예시:
      - 'basket-uncle/detail/'  -> 상세페이지용 원본/상세 이미지
      - 'basket-uncle/test/'    -> 테스트용 버킷
    - 내부적으로는
      1) resources API 로 prefix 에 해당하는 public_id 목록을 페이지 단위로 조회
      2) 조회된 public_id 들을 delete_resources 로 삭제
      3) next_cursor 가 없을 때까지 반복
    """
    _init_cloudinary_from_env()

    print(f"[cleanup] Cloudinary prefix 삭제 시작: prefix='{prefix}'")

    next_cursor: Optional[str] = None
    total_deleted = 0
    page = 0

    while True:
        page += 1
        print(f"[cleanup] 리소스 조회 중... page={page}, max_results={max_results}, next_cursor={next_cursor}")

        res_list = cloudinary.api.resources(
            type="upload",
            prefix=prefix,
            max_results=max_results,
            next_cursor=next_cursor,
        )

        resources = res_list.get("resources", []) or []
        public_ids = [r.get("public_id") for r in resources if r.get("public_id")]

        if not public_ids:
            print("[cleanup] 더 이상 삭제할 대상이 없습니다.")
            break

        print(f"[cleanup] 이번 페이지에서 삭제할 개수: {len(public_ids)}")

        delete_result = cloudinary.api.delete_resources(
            public_ids,
            invalidate=True,  # CDN 캐시 무효화
        )

        deleted_public_ids = list(delete_result.get("deleted", {}).keys())
        error_public_ids = list(delete_result.get("not_found", {}).keys())

        total_deleted += len(deleted_public_ids)
        print(f"[cleanup] 삭제 성공: {len(deleted_public_ids)}개, 누적 삭제: {total_deleted}개")

        if error_public_ids:
            print(f"[cleanup] not_found 또는 삭제 실패(public_id 기준): {error_public_ids}")

        next_cursor = res_list.get("next_cursor")
        if not next_cursor:
            print("[cleanup] next_cursor 없음. 전체 삭제 루프 종료.")
            break

    print(f"[cleanup] 완료: prefix='{prefix}', 총 삭제 개수={total_deleted}")


if __name__ == "__main__":
    """
    사용 예시 (PowerShell 기준):

      # 1) 가급적 테스트 prefix 로 먼저 실행
      $env:CLOUDINARY_URL = "cloudinary://<api_key>:<api_secret>@<cloud_name>"
      python scripts/cleanup_cloudinary_detail_images.py

    기본 prefix 는 'basket-uncle/detail/' 이며,
    다른 경로를 지우고 싶다면 환경변수 또는 인자를 이용해 제어하는 방식을
    추후 확장해서 사용할 수 있다.
    """
    # 기본 prefix 로 실행
    delete_detail_images_by_prefix("basket-uncle/detail/")

