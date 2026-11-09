import os
import re
import time
import requests
import urllib3
from flask import Flask, Response, abort

# SSL sertifika doğrulama uyarılarını kapatır
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = Flask(__name__)

# Desteklenen kanal eşlemeleri (name -> embed/stream adı)
CHANNEL_MAP = {
    "aloula": "73_aloula_w1dqfwm",
    "arryadia": "73_arryadia_k2tgcj0",
    "arrabia": "73_arrabia_hthcj4p",
    "almaghribia": "73_almaghribia_83tz85q",
    "assadissa": "73_assadissa_7b7u5n1",
    "tamazight": "73_tamazight_tccybxt",
    "laayoune": "73_laayoune_pgagr52"
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
    "Referer": "https://snrt.player.easybroadcast.io/"
}

# Bellek içi cache yapısı: { name: {"playlist": data, "timestamp": expire_time} }
token_cache = {}
CACHE_TTL = 900  # 15 dakika (saniye cinsinden)

def get_refreshed_playlist(name):
    current_time = time.time()
    
    # Cache süresi dolmadıysa bellekteki veriyi döndür
    if name in token_cache and (current_time - token_cache[name]["timestamp"] < CACHE_TTL):
        return token_cache[name]["playlist"]

    try:
        url = f"https://token.easybroadcast.io/all?url=https://cdn.live.easybroadcast.io/abr_corp/{name}/playlist_dvr.m3u8"
        response = requests.get(url, headers=HEADERS, verify=False, timeout=10)

        if response.status_code != 200:
            return None

        api_text = response.text.strip()
        
        token_match = re.search(r'token=([\w\-]+)', api_text)
        expires_match = re.search(r'expires=(\d+)', api_text)
        path_match = re.search(r'token_path=([^&]+)', api_text)

        if token_match and expires_match and path_match:
            custom_token_query = f"token={token_match.group(1)}&expires={expires_match.group(1)}&token_path={path_match.group(1)}"
        else:
            custom_token_query = api_text

        hls_variant_link = f"https://cdn.live.easybroadcast.io/abr_corp/{name}/playlist_dvr.m3u8?{custom_token_query}"
        
        stream_response = requests.get(hls_variant_link, headers=HEADERS, verify=False, timeout=10)
        stream_response.raise_for_status()

        base_url = f"https://cdn.live.easybroadcast.io/abr_corp/{name}/"
        processed_lines = []

        for line in stream_response.text.splitlines():
            line = line.strip()
            if not line:
                continue

            if line.startswith("#"):
                if "URI=" in line or "URL=" in line:
                    def fix_url(match_obj):
                        prefix = match_obj.group(1)
                        val = match_obj.group(2)
                        quote = match_obj.group(3)
                        if not val.startswith(("http://", "https://")):
                            val = base_url + val
                        return f"{prefix}{val}{quote}"

                    line = re.sub(r'((?:URI|URL)=["\']?)([^"\']*)(["\']?)', fix_url, line)
                processed_lines.append(line)
            else:
                if not line.startswith(("http://", "https://")):
                    line = base_url + line
                
                if ".m3u8" in line and "?" not in line:
                    line = f"{line}?{custom_token_query}"

                processed_lines.append(line)

        playlist_content = "\n".join(processed_lines)

        # Cache'i güncelle
        token_cache[name] = {
            "playlist": playlist_content,
            "timestamp": current_time
        }

        return playlist_content

    except Exception as e:
        print(f"Token yenileme hatası ({name}): {e}")
        # Hata durumunda cache'de eski veri varsa patlamamak için onu döndürebiliriz
        if name in token_cache:
            return token_cache[name]["playlist"]
        return None

@app.route('/stream/<name>.m3u8')
def proxy_stream(name):
    if name not in CHANNEL_MAP:
        abort(404, description="Kanal bulunamadı.")
    
    stream_id = CHANNEL_MAP[name]
    playlist_data = get_refreshed_playlist(stream_id)
    
    if not playlist_data:
        abort(500, description="Yayın akışı alınamadı veya token süresi doldu.")
        
    return Response(playlist_data, mimetype="application/vnd.apple.mpegurl")

if __name__ == '__main__':
    # Render veya yerel test için port ayarı
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
