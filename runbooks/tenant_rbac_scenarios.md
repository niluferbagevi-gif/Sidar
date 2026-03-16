# Tenant & RBAC Senaryo Rehberi (tenant_A vs tenant_B)

Bu rehber, `access_policy_middleware` için iki tenant senaryosunu uçtan uca doğrular.

## Senaryo
- `tenant_A`: sadece RAG erişimi (`rag:read`) var, swarm tetikleme (`swarm:execute`) **yok**.
- `tenant_B`: RAG + swarm dahil geniş yetki.

## 1) Kullanıcıları oluştur

```bash
curl -s -X POST http://localhost:7860/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"username":"tenant_a_user","password":"123456","tenant_id":"tenant_A"}'

curl -s -X POST http://localhost:7860/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"username":"tenant_b_user","password":"123456","tenant_id":"tenant_B"}'
```

## 2) Admin token ile policy yaz

```bash
# Admin login
ADMIN_TOKEN=$(curl -s -X POST http://localhost:7860/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"default_admin","password":"admin123"}' | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
```

Kullanıcı ID'lerini admin panelinden veya DB'den alın, ardından örnek policy çağrıları:

```bash
# tenant_A -> rag read allow
curl -s -X POST http://localhost:7860/admin/policies \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"<TENANT_A_USER_ID>","tenant_id":"tenant_A","resource_type":"rag","resource_id":"*","action":"read","effect":"allow"}'

# tenant_B -> rag read allow
curl -s -X POST http://localhost:7860/admin/policies \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"<TENANT_B_USER_ID>","tenant_id":"tenant_B","resource_type":"rag","resource_id":"*","action":"read","effect":"allow"}'

# tenant_B -> swarm execute allow
curl -s -X POST http://localhost:7860/admin/policies \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"user_id":"<TENANT_B_USER_ID>","tenant_id":"tenant_B","resource_type":"swarm","resource_id":"*","action":"execute","effect":"allow"}'
```

## 3) Beklenen davranış

- `tenant_A` ile `/rag/docs` gibi RAG endpointleri başarılı olmalı.
- `tenant_A` ile `/ws/chat` (swarm execute) denemesinde middleware **HTTP 403** dönmeli.
- `tenant_B` ile hem RAG hem `/ws/chat` erişimi başarılı olmalı.

## 4) Otomatik doğrulama (repo testi)

```bash
pytest -q tests/test_tenant_rbac_scenarios.py
```

Bu test dosyası şu iki şeyi kanıtlar:
1. DB policy matrisi tenant bazında doğru uygulanır.
2. Middleware, `tenant_A` swarm isteğini 403 ile keser; `tenant_B` isteğini geçirir.