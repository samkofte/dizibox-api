# Dizibox API Client & Cinema Dashboard

`https://www.dizibox.live/` için geliştirilmiş, Cloudflare TLS Bypass, otomatik MolySTREAM video şifre çözücü, TTL önbellek ve responsive web arayüzüne sahip kapsamlı Python kütüphanesi ve REST API.

---

## Özellikler

- **Cloudflare Bypass (`chrome120` impersonation)**: Sıfır CAPTCHA/challenge engeliyle doğrudan oturum yönetimi.
- **MolySTREAM / King Player Deşifre Motoru**: AES-CBC + OpenSSL EVP_BytesToKey (`CryptoJS.AES.decrypt`) katmanını otomatik çözen deşifre motoru. Doğrudan `.m3u8` HLS akışlarına erişim.
- **Kapsamlı Dizi Kataloğu (4800+ Yapım)**: Tüm site arşivi, arama, sezon ve bölüm hiyerarşisi.
- **Thread-Safe In-Memory TTL Cache**: Milisaniyelik yanıt süreleri.
- **İnteraktif CLI Kontrol Menüsü (`menu.py`)**: Terminalden arama, bölüm seçimi ve tek tıkla oynatma.
- **Cinema Web Dashboard & REST API (`app.py`)**: Video.js destekli, modern koyu temalı görsel kontrol paneli ve JSON API servisleri.

---

## Kurulum

```bash
pip install -r requirements.txt
```

---

## Kullanım

### 1. İnteraktif Terminal Menüsü (CLI Controller)

```bash
python menu.py
```

### 2. REST API ve Görsel Web Paneli

```bash
python app.py
```
Sunucu varsayılan olarak `http://localhost:5000` adresinde 8 eşzamanlı iş parçacıklı Waitress WSGI sunucusu ile başlar.

#### REST API Uç Noktaları

| Metot | Uç Nokta | Açıklama |
|---|---|---|
| `GET` | `/` | Responsive Sinema Kontrol Paneli |
| `GET` | `/api/recent?page=1` | Son eklenen güncel bölümler feed'i |
| `GET` | `/api/search?q={dizi}` | Dizi arama (4800+ yapım arasında) |
| `GET` | `/api/series/{slug}` | Dizi künyesi, posteri ve tüm bölümleri |
| `GET` | `/api/stream/{episode_slug}` | Deşifre edilmiş doğrudan HLS `.m3u8` video bağlantısı |
| `GET` | `/api/archive?page=1` | Tüm dizilerin arşivi |
| `GET` | `/api/cache/stats` | Önbellek hit/miss performansı |

### 3. Python Kütüphanesi Olarak Kullanım

```python
from dizibox_api import DiziboxClient

client = DiziboxClient()

# 1. Dizi Ara
series = client.search("Breaking Bad")
print(series[0].title, series[0].slug)

# 2. Dizi ve Sezon Detayları
detail = client.get_series("breaking-bad-izle-1")
print(f"Toplam Bölüm: {detail.total_episodes}")

# 3. Video Akışını Deşifre Et (HLS .m3u8)
stream = client.get_episode_stream("breaking-bad-1-sezon-1-bolum-hd-1-izle")
print("Doğrudan M3U8 Akış Linki:", stream.stream_url)
```

---

## Testleri Çalıştırma

```bash
python test_dizibox.py
```
