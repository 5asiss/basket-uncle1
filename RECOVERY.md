# 사이트 이상 시 GitHub 백업으로 복구하는 방법

사이트(Render·DB)가 날아갔거나 잘못됐을 때, GitHub Releases에 올라간 백업 zip으로 복구하는 절차입니다.

---

## 1. 백업 zip 받기

1. **GitHub**에서 **basket-uncle** 저장소 접속.
2. 오른쪽 **Releases** 클릭.
3. 복구할 시점의 백업 선택 (가장 최근이면 맨 위 **Backup YYYY-MM-DD HH:MM**).
4. **Assets**에서 **`backup_YYYYMMDD_HHMM.zip`** 다운로드.
5. PC에 zip 압축 해제.

압축 해제 후 나오는 파일:
- **PostgreSQL 사용했던 경우**: `main_dump.sql` (+ `reports/revenue_report_30d.csv`)
- **SQLite 사용했던 경우**: `main.db` (그리고 예전에 배송 DB 따로 썼으면 `delivery.db` 등) + `reports/` 폴더

---

## 2-A. 예전에 PostgreSQL(Render Postgres)을 쓰고 있었을 때

백업 zip 안에 **`main_dump.sql`** 이 있는 경우입니다.

### ① 새 PostgreSQL 만들기 (Render DB가 통째로 날아간 경우)

1. **Render Dashboard** → **New +** → **PostgreSQL**.
2. 이름·리전 설정 후 **Create Database**.
3. 생성된 DB의 **Connection** 정보에서 **Internal Database URL** 복사.  
   (형식: `postgres://...@.../...`)

### ② 덤프 복원

**중요**: Render PostgreSQL의 **Internal Database URL**은 Render 서비스 안에서만 접속 가능해서, 로컬 PC에서는 접속할 수 없습니다. 아래 중 하나로 진행하세요.

**방법 1: 외부 접속 가능한 PostgreSQL에 복원 (가장 간단)**

- **Neon**(neon.tech), **Supabase**, **Railway** 등 **외부에서 접속 가능한** PostgreSQL을 하나 만듭니다.
- 로컬 PC에서 압축 푼 **main_dump.sql**이 있는 폴더로 이동한 뒤, 해당 서비스에서 제공하는 **연결 문자열**로 복원합니다.
  ```bash
  psql "postgresql://사용자:비밀번호@호스트:포트/DB이름?sslmode=require" -f main_dump.sql
  ```
- 복원이 끝나면 그 **연결 문자열**을 Render Web Service의 **DATABASE_URL**에 넣고 재배포하면, 사이트가 복구된 DB를 사용합니다.

**방법 2: Render PostgreSQL을 그대로 쓰고 싶을 때**

- Render PostgreSQL에 **External Database URL**(외부 접속용)이 있으면, 로컬에서:
  ```bash
  psql "여기에_External_URL_붙여넣기" -f main_dump.sql
  ```
  로 복원한 뒤, Web Service의 **DATABASE_URL**은 **Internal** URL로 두면 됩니다.
- External URL이 없으면(무료 플랜 등) **방법 1**처럼 외부 접속 가능한 DB에 복원한 뒤, 그 연결 문자열을 **DATABASE_URL**에 넣어 사용하는 방식을 권장합니다.


### ③ 앱이 복구된 DB를 쓰도록 설정

1. **Render Dashboard** → **basket-uncle** Web Service → **Environment**.
2. **DATABASE_URL** 값을 **복원한 PostgreSQL의 연결 문자열**로 설정합니다.  
   (방법 1이면 외부 DB URL, 방법 2면 Render Internal URL.)
3. **Save Changes** 후 재배포(Deploy).

이제 사이트는 복구된 DB를 보고 있습니다.

---

## 2-B. 예전에 SQLite를 쓰고 있었을 때

백업 zip 안에 **`main.db`** 파일이 있는 경우입니다.

Render는 재시작 시 디스크가 비워지므로, **SQLite 파일을 서버에 올려서 계속 쓰는 방식**은 Render에서는 권장하지 않습니다. 그래서 복구 후에는 **로컬 실행** 또는 **다른 호스팅**으로 옮기는 경우가 많습니다.

### ① 로컬에서 복구해서 실행

1. 프로젝트 폴더의 **instance** 폴더를 만들고, 압축 푼 **main.db**를 그 안에 넣습니다.  
   (예: `instance/direct_trade_mall.db` 또는 기존에 쓰던 SQLite 파일 경로에 맞춤.)
2. `.env`에서:
   ```env
   DATABASE_URL=sqlite:///direct_trade_mall.db
   ```
   처럼 같은 경로를 가리키게 합니다.
3. 로컬에서 실행:
   ```bash
   python app.py
   ```
4. 브라우저에서 `http://127.0.0.1:5000` 등으로 접속해 동작 확인.

### ② 다시 Render에 배포하려면 (권장: PostgreSQL로 전환)

- SQLite는 Render 디스크에 두면 또 날아갈 수 있으므로, 복구 후 **PostgreSQL로 옮기는 것**을 권장합니다.
1. Render에서 **PostgreSQL** 하나 생성.
2. 로컬에서 **main.db**를 PostgreSQL로 이전 (예: `scripts/migrate_sqlite_to_postgres.py` 또는 수동으로 스키마·데이터 이전).
3. Render Web Service의 **DATABASE_URL**을 새 PostgreSQL URL로 바꾸고 재배포.
4. 이후 백업은 다시 **main_dump.sql** 형태로 쌓이므로, 다음 복구 시에는 **2-A** 절차를 따르면 됩니다.

---

## 3. 복구 후 확인

- [ ] 관리자 로그인 (`/admin`).
- [ ] 주문/상품/회원 등 핵심 데이터가 복구 시점과 맞는지 확인.
- [ ] 백업·환경 변수(`GITHUB_BACKUP_TOKEN`, `GITHUB_BACKUP_REPO`, `BACKUP_CRON_SECRET` 등) 다시 설정했는지 확인해, 다음부터도 자동 백업이 Releases에 올라가게 해 두기.

---

## 요약

| 예전 DB 종류 | zip 안 파일 | 복구 방법 |
|-------------|-------------|-----------|
| **PostgreSQL** | `main_dump.sql` | 새 Postgres 만들고 덤프 복원 → DATABASE_URL을 그 DB로 변경 후 재배포 |
| **SQLite** | `main.db` | 로컬에서 instance에 넣고 실행하거나, PostgreSQL로 이전 후 Render에 재배포 |

가장 최근 백업은 **Releases**에서 **가장 위에 있는 backup zip**을 받아서 위 순서대로 진행하면 됩니다.
