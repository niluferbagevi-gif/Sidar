# core/rag.py Teknik Notu

`DocumentStore`, Sidar’ın hibrit RAG katmanıdır. ChromaDB vektör arama + BM25 + anahtar-kelime fallback yaklaşımını aynı depoda birleştirir.

## 1) Sorumluluklar

- Belge ekleme/silme/listeleme işlemlerini yürütmek.
- Metni recursive chunking ile parçalamak.
- İndeks meta verisini JSON dosyasında saklamak.
- Arama sırasında vektör/BM25/keyword stratejileri arasında seçim yapmak.

## 2) Mimari Özellikler

- **Hybrid retrieval:** tek bir yönteme bağımlı kalmadan birden çok arama stratejisi.
- **GPU destekli embedding (opsiyonel):** ortam uygunsa embedding tarafında hızlandırma.
- **Dosya ve URL ingestion:** hem yerel dosya hem URL kaynaklarından belge ekleyebilme.
- **Index persistence:** `_index` meta verisi kalıcı dosyada tutulur.

## 3) Bilinen Risk/İyileştirme Alanları

- Bazı çağrı yollarında arama işlemi senkron çalışabildiği için yüksek eşzamanlılıkta event-loop gecikmesi üretebilir.
- BM25/indeks güncelleme maliyeti büyüyen veri setlerinde optimize edilmeye açıktır.

## 4) Bağlantılı Dosyalar

- Tüketen: `agent/sidar_agent.py`, `web_server.py`
- Ayar kaynağı: `config.py` (`RAG_DIR`, `RAG_TOP_K`, `RAG_CHUNK_SIZE`, `RAG_CHUNK_OVERLAP`, `RAG_FILE_THRESHOLD`)
- UI tüketicisi: `web_ui/index.html` (`/rag/*` endpoint’leri üzerinden)