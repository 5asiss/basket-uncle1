# 배포 환경 자동 백업 설정 가이드

매일 **한국시간 새벽 4시**에 백업이 실행되도록 하는 방법입니다.  
아래 **0단계**를 먼저 한 뒤, **A / B / C** 중 하나만 설정하면 됩니다.

---

## 0단계: 앱(Render) 쪽 필수 설정

배포된 앱이 백업 요청을 받아들이고, 결과를 GitHub에 올리려면 다음 환경 변수를 **Render Dashboard → 해당 Web Service → Environment**에 설정합니다.

| 변수명 | 값 예시 | 설명 |
|--------|---------|------|
| `BACKUP_CRON_SECRET` | `my-super-secret-key-123` | **직접 정한 비밀 문자열.** 나중에 cron이 이 값을 `key` 파라미터로 보내야 401이 안 난다. 길고 랜덤하게 정할 것. |
| `GITHUB_BACKUP_TOKEN` | `ghp_xxxx...` | GitHub **Personal Access Token.** 권한: `repo` (또는 최소 `public_repo`). 백업 zip을 Release에 올릴 때 사용. |
| `GITHUB_BACKUP_REPO` | `your-id/basket-uncle` | 백업을 올릴 저장소. 형식: `owner/repo`. |

**앱 URL**  
- 예: `https://basket-uncle.onrender.com` (끝에 `/` 없이)
- 이 주소를 **1~3번**에서 “백업 호출 URL”로 사용합니다.

---

## A. cron-job.org로 설정 (무료, 추천)

외부에서 매일 새벽 4시(KST)에 백업 URL을 호출하는 방식입니다.

### 1. 가입 및 Cron Job 생성

1. [https://cron-job.org](https://cron-job.org) 접속 후 **무료 가입**.
2. 로그인 후 **Cron Jobs** → **Create cron job**.

### 2. 항목 입력

| 항목 | 입력 값 |
|------|----------|
| **Title** | `basket-uncle daily backup` (원하는 이름) |
| **URL** | `https://(앱URL)/admin/backup/cron?key=(BACKUP_CRON_SECRET 값)` |
| | 예: `https://basket-uncle.onrender.com/admin/backup/cron?key=my-super-secret-key-123` |
| **Schedule** | **Daily** → 시간 **04:00** (또는 **04:00** 선택 가능한 경우 KST 기준으로 4시) |
| | cron 표현식 사용 가능하면: `0 4 * * *` (매일 04:00). **타임존을 Korea (KST)** 로 설정. |
| **Request method** | GET |
| **Request timeout** | 300 초 권장 (백업이 오래 걸릴 수 있음) |

### 3. 저장 후 확인

- **Save** 후 다음날 새벽 4시에 한 번 실행되는지 확인.
- **History**에서 성공(200) 여부 확인. 401이면 `key` 값이 Render의 `BACKUP_CRON_SECRET`와 일치하는지 확인.

### 4. 타임존이 UTC만 있는 경우

- 서버가 UTC 기준이면 **04:00 KST = 19:00 UTC (전날)**.
- cron-job.org에서 **19:00 UTC**로 설정하면 한국시간 새벽 4시에 실행됩니다.

---

## B. GitHub Actions로 설정 (무료)

저장소에 워크플로를 추가하고, 시크릿만 넣으면 매일 04:00 KST에 백업 URL을 호출합니다.

### 1. 저장소 시크릿 추가

1. GitHub 저장소 **Settings** → **Secrets and variables** → **Actions**.
2. **New repository secret** 두 개 추가:

| Name | Value | 비고 |
|------|--------|------|
| `BACKUP_CRON_SECRET` | 0단계에서 정한 값 (예: `my-super-secret-key-123`) | Render의 `BACKUP_CRON_SECRET`와 **동일**하게. |
| `BACKUP_APP_URL` | 배포된 앱 URL (예: `https://basket-uncle.onrender.com`) | 끝에 `/` 없이. |

### 2. 워크플로 파일 확인

프로젝트에 이미 다음 파일이 있습니다:

- **`.github/workflows/backup-cron.yml`**

내용 요약:

- **스케줄**: 매일 **19:00 UTC** (= 한국시간 04:00)
- **동작**: `BACKUP_APP_URL` + `/admin/backup/cron?key=` + `BACKUP_CRON_SECRET` 로 GET 요청

위 시크릿만 맞게 넣으면 푸시 후 자동으로 스케줄 실행됩니다.

### 3. 수동 실행으로 테스트

워크플로가 **Actions**에 보이려면 `.github/workflows/backup-cron.yml` 파일이 **기본 브랜치(보통 `main`)에 푸시**되어 있어야 합니다. 아직 푸시 안 했다면:

```bash
git add .github/workflows/backup-cron.yml
git commit -m "Add backup cron workflow"
git push origin main
```

아래는 **GitHub 웹**에서 수동 실행하는 단계입니다.

#### ① Actions 탭 들어가기

1. **GitHub**에서 **basket-uncle** 저장소 페이지로 이동합니다.  
   (예: `https://github.com/본인아이디/basket-uncle`)
2. 저장소 **상단 메뉴**에서 **`Code`** 옆의 **`Actions`** 를 클릭합니다.  
   - 상단 탭 순서: `Code` | `Issues` | `Pull requests` | **`Actions`** | …
3. **Actions** 페이지가 열리면, **왼쪽 사이드바**에 워크플로 목록이 보입니다.

#### ② 워크플로 찾기

4. 왼쪽에서 **`Backup cron (daily 4am KST)`** 를 클릭합니다.  
   - 안 보이면 **`All workflows`** 를 클릭한 뒤 목록에서 같은 이름을 찾습니다.  
   - 파일 이름으로 보이면 **`backup-cron`** 항목을 클릭해도 됩니다.
5. 오른쪽에 해당 워크플로의 **Run 목록**(실행 이력)이 나옵니다.  
   - 아직 한 번도 실행 안 했으면 목록이 비어 있을 수 있습니다.

#### ③ Run workflow로 수동 실행

6. 오른쪽 영역 **위쪽**에 **`Run workflow`** 드롭다운 버튼이 있습니다.  
   - **"Run workflow"** 라고 써 있는 **회색 버튼**을 클릭합니다.
7. 브랜치를 선택합니다.  
   - **Branch**에서 `main`(또는 사용 중인 기본 브랜치)을 선택합니다.
8. **초록색 `Run workflow`** 버튼을 한 번 더 클릭합니다.
9. 잠시 후 페이지가 갱신되면, 방금 실행한 **Run**이 목록 맨 위에 나타납니다.  
   - **노란 동그라미** → 실행 중  
   - **초록 체크** → 성공  
   - **빨간 X** → 실패

#### ④ 결과 확인

10. 맨 위의 Run **제목**(예: "Run workflow" 또는 커밋 메시지)을 **클릭**합니다.
11. **Call backup endpoint** 단계를 클릭해 로그를 엽니다.
12. 로그에서 다음을 확인합니다.  
    - `HTTP 200` 이 보이면 성공입니다.  
    - `{"success":true,"message":"GitHub 백업 완료: ..."}` 같은 JSON이 보이면 백업이 정상 동작한 것입니다.  
    - `HTTP 401` 이면 시크릿 `BACKUP_CRON_SECRET` 값이 Render의 값과 다른 것입니다.  
    - `Missing BACKUP_APP_URL or BACKUP_CRON_SECRET` 이면 해당 시크릿을 저장소에 아직 안 넣은 것입니다.

**요약**:  
**저장소 → 상단 `Actions` 탭 → 왼쪽 `Backup cron (daily 4am KST)` (또는 `backup-cron`) → 오른쪽 위 `Run workflow` → Branch `main` 선택 → 초록색 `Run workflow` 클릭 → 맨 위 Run 클릭 → "Call backup endpoint" 로그에서 `HTTP 200` 확인.**

---

## C. Render Cron 서비스로 설정 (유료)

Render의 Cron Job 서비스를 쓰는 방법입니다. **Cron 1개당 월 최소 약 $1** 등 유료입니다.

### 1. render.yaml 사용 시

`render.yaml`에 이미 Cron 서비스가 정의되어 있으면:

1. Render Dashboard에서 **Blueprint** 또는 **New → Cron Job**으로 해당 Cron 서비스를 생성.
2. 해당 Cron 서비스 **Environment**에 다음 두 개 설정:

| 변수명 | 값 |
|--------|-----|
| `BACKUP_APP_URL` | `https://(앱주소).onrender.com` (끝에 `/` 없이) |
| `BACKUP_CRON_SECRET` | 0단계에서 Web Service에 넣은 것과 **동일한** 값 |

3. 스케줄은 이미 `0 19 * * *` (매일 19:00 UTC = 04:00 KST)로 되어 있으면 변경 불필요.

### 2. 수동으로 Cron Job만 만들 때

1. **Dashboard** → **New +** → **Cron Job**.
2. 같은 리포지토리 연결.
3. **Build Command**: `pip install -r requirements.txt`
4. **Command**:
   ```bash
   python -c "import os, requests; url=os.environ.get('BACKUP_APP_URL','').rstrip('/'); key=os.environ.get('BACKUP_CRON_SECRET',''); r=requests.get(url+'/admin/backup/cron', params={'key': key}, timeout=300); print('Backup cron:', r.status_code)"
   ```
5. **Schedule**: `0 19 * * *`
6. **Environment**: `BACKUP_APP_URL`, `BACKUP_CRON_SECRET` 위와 같이 설정.

---

## 동작 확인

- **성공 시**:  
  - 응답 **200** + JSON `{"success": true, "message": "GitHub 백업 완료: ..."}`  
  - GitHub 저장소 **Releases**에 `backup-YYYYMMDD_HHMM` 태그로 zip 업로드됨.
- **실패 시**:
  - **401**: `key`와 `BACKUP_CRON_SECRET` 불일치 → 값 다시 확인.
  - **500 / 타임아웃**: 앱 로그 확인 (pg_dump 없음, DB 연결 오류 등).

**사이트 이상 시 GitHub 백업으로 복구**하는 방법은 → **[RECOVERY.md](RECOVERY.md)** 참고.

---

## 요약 체크리스트

- [ ] Render Web Service에 `BACKUP_CRON_SECRET`, `GITHUB_BACKUP_TOKEN`, `GITHUB_BACKUP_REPO` 설정
- [ ] A / B / C 중 하나만 설정:
  - [ ] **A** cron-job.org: URL에 `key=(BACKUP_CRON_SECRET)` 포함, 매일 04:00 KST(또는 19:00 UTC)
  - [ ] **B** GitHub Actions: 시크릿 `BACKUP_CRON_SECRET`, `BACKUP_APP_URL` 추가 후 푸시
  - [ ] **C** Render Cron: 같은 리포에 Cron 서비스 추가, `BACKUP_APP_URL`, `BACKUP_CRON_SECRET` 설정
- [ ] 한 번 수동 실행으로 200 + Release 업로드 확인

이렇게 하면 배포 환경에서 **BACKUP_CRON_SECRET 설정 + (cron-job.org / GitHub Actions / Render Cron 중 하나)** 로 매일 새벽 4시에 `/admin/backup/cron?key=...` 가 호출되게 할 수 있습니다.
