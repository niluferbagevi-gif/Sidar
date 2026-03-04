# Module Notes Yol Haritası

Bu belge, module-notes dokümantasyonunun **klasör bazlı + parti parti commit** yaklaşımıyla nasıl genişletileceğini tanımlar.

## Parti Planı

1. **Parti-1 (Runtime çekirdeği)**
   - `config.py`
   - `main.py`
   - `web_server.py`

2. **Parti-2 (Agent katmanı)**
   - `agent/__init__.py`
   - `agent/sidar_agent.py`
   - `agent/definitions.py`
   - `agent/auto_handle.py`

3. **Parti-3 (Core katmanı)**
   - `core/__init__.py`
   - `core/llm_client.py`
   - `core/memory.py`
   - `core/rag.py`

4. **Parti-4 (Manager katmanı)**
   - `managers/*`

5. **Parti-5 (Ops/dağıtım/dokümantasyon)**
   - `Dockerfile`, `docker-compose.yml`, `environment.yml`, `install_sidar.sh`
   - `README.md`, `SIDAR.md`, `CLAUDE.md`, `.env.example`

6. **Parti-6 (Test + UI)**
   - `tests/*`
   - `web_ui/index.html`

## Kalite Kriterleri

Her modül notu için:
- Sorumluluk ve kapsam
- Girdi/çıktı ve dış bağımlılıklar
- Diğer modüllerle ilişki
- Riskler ve teknik borçlar
- Operasyon notları (varsa)

Not: Teknik notlar kodu referans alan **yaşayan doküman** olarak tutulur; her büyük refaktörde ilgili not güncellenmelidir.
