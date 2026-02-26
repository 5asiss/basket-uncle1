"""
SQLite -> PostgreSQL 마이그레이션 스크립트 (단일 DB용).

사용 시나리오 (로컬에서 실행 권장):

1) 현재 SQLite 파일 위치 확인
   - 기본값: sqlite:///direct_trade_mall.db (프로젝트 루트 또는 instance/ 아래)

2) Render PostgreSQL DATABASE_URL 준비
   - Render 대시보드에서 Postgres 인스턴스 생성 후
   - INTERNAL DATABASE URL 을 복사 (postgres://... 형식)

3) .env (또는 실행 환경 변수)에 아래 두 값을 설정

   SQLITE_URL=sqlite:///direct_trade_mall.db
   TARGET_DATABASE_URL=postgres://USER:PASSWORD@HOST:PORT/DBNAME

4) 먼저 Postgres 쪽에 테이블 구조를 생성
   - 가장 간단한 방법: 일시적으로 DATABASE_URL=TARGET_DATABASE_URL 로 바꾸고
     `python app.py` 를 한 번 실행해서 앱이 기동되게 하면,
     SQLAlchemy가 create_all() 을 통해 테이블을 생성한 상태여야 합니다.

5) 다시 로컬에서 이 스크립트 실행

   cd 프로젝트루트
   python scripts/migrate_sqlite_to_postgres.py

테이블 생성 순서/제약조건에 따라 실패할 수 있으므로,
작은 데이터부터 테스트 후 사용하는 것을 권장합니다.
"""

import os
from sqlalchemy import create_engine, MetaData, Table
from sqlalchemy.engine.reflection import Inspector


SQLITE_URL = os.getenv("SQLITE_URL", "sqlite:///direct_trade_mall.db")
TARGET_DATABASE_URL = os.getenv("TARGET_DATABASE_URL") or os.getenv("DATABASE_URL")


def main() -> None:
    if not TARGET_DATABASE_URL:
        print("[ERROR] TARGET_DATABASE_URL 또는 DATABASE_URL 이 설정되어 있지 않습니다.")
        return

    print(f"[INFO] SQLite 원본: {SQLITE_URL}")
    print(f"[INFO] 대상 Postgres: {TARGET_DATABASE_URL}")

    src_engine = create_engine(SQLITE_URL)
    dst_engine = create_engine(TARGET_DATABASE_URL)

    src_meta = MetaData()
    dst_meta = MetaData()

    inspector = Inspector.from_engine(src_engine)
    table_names = inspector.get_table_names()
    if not table_names:
        print("[WARN] SQLite 원본에 테이블이 없습니다.")
        return

    print(f"[INFO] 발견된 테이블: {', '.join(table_names)}")

    src_meta.reflect(bind=src_engine)
    dst_meta.reflect(bind=dst_engine)

    for name in table_names:
        print(f"[INFO] 테이블 복사 중: {name}")
        src_table = Table(name, src_meta, autoload_with=src_engine)
        # 대상 메타데이터에 동일 이름 테이블이 있다고 가정 (create_all 로 생성되어 있어야 함)
        if name not in dst_meta.tables:
            print(f"  [SKIP] 대상 DB에 테이블이 없습니다: {name}")
            continue
        dst_table = dst_meta.tables[name]

        rows = list(src_engine.execute(src_table.select()))
        if not rows:
            print(f"  [INFO] 데이터 없음")
            continue

        # 이미 데이터가 있다면 중복 삽입 방지용으로 일단 건너뜀
        dst_count = dst_engine.execute(dst_table.count()).scalar()
        if dst_count:
            print(f"  [SKIP] 대상 테이블에 이미 {dst_count}건 존재 (중복 방지를 위해 건너뜀)")
            continue

        batch = [dict(r) for r in rows]
        with dst_engine.begin() as conn:
            conn.execute(dst_table.insert(), batch)
        print(f"  [OK] {len(batch)}건 복사 완료")

    print("[DONE] 마이그레이션 스크립트 종료.")


if __name__ == "__main__":
    main()

