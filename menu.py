"""Interactive CLI Menu for Dizibox."""

import sys
import webbrowser
from dizibox_api.client import DiziboxClient


def clear():
    print("\n" + "=" * 60 + "\n")


def print_header():
    print(r"""
============================================================
  ____  _     _ _               _    ____ ___ 
 |  _ \(_)___(_) |__   _____  __/ |  / _ \_ _|
 | | | | |_  / | '_ \ / _ \ \/ /| | | | | | | 
 | |_| | |/ /| | |_) | (_) >  < | |_| |_| | | 
 |____/|_/___|_|_.__/ \___/_/\_\|_(_)\___/___|
============================================================
  Dizibox Terminal Kontrol & Oynatıcı Merkezi
""")


def main():
    client = DiziboxClient()

    while True:
        print_header()
        print("  [1] Dizi Ara (Breaking Bad, Dark, Sherlock vb.)")
        print("  [2] Son Eklenen Bölümler (Güncel Akış)")
        print("  [3] Dizi Arşivi / Kataloğu (4800+ Dizi)")
        print("  [4] Bölüm Video Akışını Çöz (HLS .m3u8 & MolySTREAM)")
        print("  [5] Web Dashboard & REST API Sunucusunu Başlat")
        print("  [0] Çıkış")
        print("=" * 60)

        choice = input("\nSeçiminiz [0-5]: ").strip()

        if choice == "0":
            print("\nGörüşmek üzere!")
            sys.exit(0)

        elif choice == "1":
            q = input("\nAramak istediğiniz dizi adı: ").strip()
            if not q:
                continue
            print(f"[*] '{q}' aranıyor...")
            results = client.search(q)
            if not results:
                print("[-] Hiçbir sonuç bulunamadı.")
                input("\nDevam etmek için Enter'a basın...")
                continue

            print(f"\n[+] {len(results)} dizi bulundu:")
            for i, s in enumerate(results[:15], start=1):
                print(f"  [{i}] {s.title} ({s.slug})")

            sel = input("\nDetayını görmek istediğiniz dizinin numarası (Enter = Geri): ").strip()
            if sel.isdigit() and 1 <= int(sel) <= len(results):
                chosen = results[int(sel) - 1]
                show_series_menu(client, chosen.slug)

        elif choice == "2":
            print("\n[*] Son eklenen bölümler alınıyor...")
            episodes = client.get_recent_episodes(page=1)
            print(f"\n[+] Son Eklenen {len(episodes)} Bölüm:")
            for i, ep in enumerate(episodes[:20], start=1):
                badge_str = f"[{ep.badge}]" if ep.badge else ""
                print(f"  [{i}] {ep.title} {badge_str} -> {ep.episode_slug}")

            sel = input("\nVideo akışını çözmek istediğiniz bölümün numarası (Enter = Geri): ").strip()
            if sel.isdigit() and 1 <= int(sel) <= len(episodes):
                chosen_ep = episodes[int(sel) - 1]
                play_episode(client, chosen_ep.episode_slug)

        elif choice == "3":
            print("\n[*] Arşivden diziler taranıyor...")
            archive = client.get_archive_series()
            print(f"[+] Toplam {len(archive)} dizi indekslendi.")
            for i, s in enumerate(archive[:20], start=1):
                print(f"  [{i}] {s.title}")
            print("  ... ve 4800+ dizi daha.")
            input("\nDevam etmek için Enter'a basın...")

        elif choice == "4":
            slug = input("\nBölüm Slug veya URL'si girin (örn: breaking-bad-1-sezon-1-bolum-hd-1-izle): ").strip()
            if slug:
                play_episode(client, slug)

        elif choice == "5":
            print("\n[*] Web sunucusu için 'python app.py' çalıştırabilirsiniz.")
            input("\nDevam etmek için Enter'a basın...")


def show_series_menu(client: DiziboxClient, slug: str):
    print(f"\n[*] '{slug}' bilgileri yükleniyor...")
    try:
        detail = client.get_series(slug)
    except Exception as e:
        print(f"[-] Hata oluştu: {e}")
        input("\nDevam etmek için Enter'a basın...")
        return

    print("\n" + "=" * 60)
    print(f"  BAŞLIK: {detail.title}")
    if detail.imdb_rating:
        print(f"  IMDb: {detail.imdb_rating} ⭐")
    if detail.genres:
        print(f"  TÜRLER: {', '.join(detail.genres)}")
    print(f"  TOPLAM BÖLÜM: {detail.total_episodes}")
    print("=" * 60)

    if not detail.episodes:
        print("[-] Bu dizi için henüz bölüm bulunamadı.")
        input("\nDevam etmek için Enter'a basın...")
        return

    print("\nBölümler:")
    for i, ep in enumerate(detail.episodes[:30], start=1):
        print(f"  [{i}] {ep.title} -> {ep.slug}")

    sel = input("\nOynatmak / video linkini almak istediğiniz bölüm numarası (Enter = Geri): ").strip()
    if sel.isdigit() and 1 <= int(sel) <= len(detail.episodes):
        ep_chosen = detail.episodes[int(sel) - 1]
        play_episode(client, ep_chosen.slug)


def play_episode(client: DiziboxClient, slug: str):
    print(f"\n[*] '{slug}' video oynatıcı ve MolySTREAM şifresi çözülüyor...")
    try:
        stream = client.get_episode_stream(slug)
        print("\n" + "=" * 60)
        print(f"[+] Bölüm: {stream.episode_title}")
        print(f"[+] HLS Master M3U8: {stream.stream_url}")
        print(f"[+] Embed Kaynağı: {stream.embed_url}")
        print("=" * 60)
        print("\nBu m3u8 akışını VLC, mpv veya tarayıcınızda oynatabilirsiniz.")
        copy = input("\nTarayıcıda açmak ister misiniz? (e/h): ").strip().lower()
        if copy == "e":
            webbrowser.open(stream.stream_url)
    except Exception as e:
        print(f"[-] Akış çözülürken hata: {e}")
    input("\nDevam etmek için Enter'a basın...")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nÇıkış yapıldı.")
