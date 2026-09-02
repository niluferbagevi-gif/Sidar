# `managers/teams_manager.py` — Microsoft Teams integration

Teams Incoming Webhook üzerinden MessageCard ve Adaptive Card gönderimini yönetir. Webhook
tanımlı değilse dış ağ çağrısı yapmadan entegrasyonu devre dışı bırakır.

Webhook ve client secret parametreleri `None` varsayılanına sahiptir; değerler manager
sınırında normalize edilir. Bu sözleşme kaynak kodda secret-benzeri boş varsayılanları
kaldırırken mevcut çağıranlarla uyumluluğu korur.

