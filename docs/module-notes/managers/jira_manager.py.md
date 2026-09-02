# `managers/jira_manager.py` — Jira integration

Jira Cloud REST API v3 istemcisidir. E-posta + API token ile Basic Auth veya token ile
Bearer Auth kullanır; URL/token eksikse entegrasyon güvenli biçimde devre dışı kalır.

Kimlik bilgisi parametreleri `None` varsayılanına sahiptir ve yalnız istemci içinde boş
metne normalize edilir. Böylece API token için kaynak kodda parola benzeri sabit varsayılan
bulunmaz ve mevcut boş-string çağrıları geriye uyumlu kalır.

