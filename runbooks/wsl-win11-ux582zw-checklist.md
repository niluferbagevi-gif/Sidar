# WSL2 + Windows 11 (ASUS Zenbook Pro Duo 15 OLED UX582ZW) Hızlı Kontrol Listesi

Bu kontrol listesi, Sidar'ı Windows 11 üzerinde WSL/Ubuntu + Conda ile çalıştıran kullanıcılar içindir.

## 1) WSL / GPU doğrulama

```bash
uname -a
nvidia-smi
```

- `nvidia-smi` başarısızsa Windows tarafı NVIDIA sürücüsü veya WSL GPU köprüsü kontrol edilmelidir.
- GPU görünmüyorsa proje CPU ile çalışır; bu bir bloklayıcı değildir fakat RAG embedding ve benzeri işlerde daha yavaş olur.

## 2) Conda ortamı

```bash
conda env create -f environment.yml
conda activate sidar-ai
python --version
```

Beklenen Python hattı: 3.11.x

## 3) Bağımlılık kurulumu (tek kaynak: pyproject.toml)

```bash
pip install -e .[all,dev]
```

## 4) CUDA wheel kanalı (GPU/RAG için önerilir)

```bash
export PIP_EXTRA_INDEX_URL=https://download.pytorch.org/whl/cu124
pip install -e .[rag]
```

## 5) Browser otomasyonu kullanacaksanız

```bash
python -m playwright install --with-deps chromium
```

## 6) Temel sağlık kontrolü

```bash
python -m pytest -q -c /dev/null tests/test_active_learning.py
```

