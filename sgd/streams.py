import os
import urllib
import re
from sgd.ptn import parse_title
from sgd.utils import sanitize, hr_size


class Streams:
    def __init__(self, gdrive, stream_meta):
        self.results = []
        self.gdrive = gdrive
        self.strm_meta = stream_meta
        self.get_url = self.get_proxy_url
        self.proxy_url = os.environ.get("CF_PROXY_URL")

        if not self.proxy_url:
            self.get_url = self.get_gapi_url
            self.acc_token = gdrive.get_acc_token()

        for item in gdrive.results:
            try:
                self.item = item
                # Tenta processar o título
                self.parsed = parse_title(item.get("name"))
                
                # Verificação de segurança se o parser falhou totalmente
                if not hasattr(self.parsed, 'sortkeys'):
                    continue

                self.construct_stream()

                if self.is_semi_valid_title(self.constructed):
                    if self.strm_meta.type == "movie":
                        if self.is_valid_year(self.constructed):
                            self.results.append(self.constructed)
                    else:
                        self.results.append(self.constructed)
            except Exception as e:
                # Log de erro silencioso para não parar o addon
                print(f"Erro ao processar: {e}")
                continue

        self.results.sort(key=self.best_res, reverse=True)

    def is_valid_year(self, movie):
        sortkeys = movie.get("sortkeys", {})
        movie_year = str(sortkeys.get("year", "0"))
        return movie_year == self.strm_meta.year

    def is_semi_valid_title(self, item):
        sortkeys = item.get("sortkeys", {})
        item_title = sanitize(str(sortkeys.get("title")), "")
        if item_title:
            return any(
                sanitize(title, "") in item_title for title in self.strm_meta.titles
            )
        return False

    def get_title(self):
        # --- 1. Dados Brutos ---
        file_name = self.item.get("name", "Unknown")
        name_upper = file_name.upper()
        
        try:
            file_size = hr_size(int(self.item.get("size", 0)))
        except:
            file_size = "0B"

        # --- 2. Detecção Manual de Vídeo (Codec) ---
        # A biblioteca falhou em HEVC/x265, então forçamos a busca
        if any(x in name_upper for x in ["HEVC", "X265", "H265", "H.265"]):
            codec = "H.265"
        elif any(x in name_upper for x in ["AVC", "X264", "H264", "H.264"]):
            codec = "H.264"
        else:
            # Fallback para o parser ou genérico
            codec = self.parsed.sortkeys.get("codec", "CODEC?")

        # --- 3. Detecção Manual de HDR ---
        hdr_list = []
        
        # Ordem importa: HDR10+ é mais específico que HDR
        if "HDR10+" in name_upper or "HDR+" in name_upper:
            hdr_list.append("HDR+")
        elif "HDR" in name_upper:
            hdr_list.append("HDR")
            
        if "DV" in name_upper or "DOLBY VISION" in name_upper:
            hdr_list.append("Dolby Vision")
            
        hdr_display = " ".join(hdr_list) if hdr_list else "SDR"

        # --- 4. Detecção Manual de Áudio e Canais ---
        # Detectar Codec de Áudio
        audio_codec = "Audio" # Padrão
        if "ATMOS" in name_upper:
            audio_codec = "Dolby Atmos"
        elif any(x in name_upper for x in ["DDP", "DD+", "EAC3", "DIGITAL PLUS"]):
            audio_codec = "Dolby Digital Plus"
        elif any(x in name_upper for x in ["DD", "AC3", "DOLBY DIGITAL"]):
            audio_codec = "Dolby Digital"
        elif "AAC" in name_upper:
            audio_codec = "AAC"
        elif "DTS" in name_upper:
            audio_codec = "DTS"

        # Detectar Canais (Procura por 5.1, 7.1, 2.0 mesmo colado ex: DDP5.1)
        channels = ""
        channel_match = re.search(r'\b(7\.1|5\.1|2\.0)\b', file_name) # Busca isolada
        if not channel_match:
             channel_match = re.search(r'(7\.1|5\.1|2\.0)', file_name) # Busca geral (pega DDP5.1)
        
        if channel_match:
            channels = f" - {channel_match.group(1)}"
        
        # Monta string de áudio (ex: Dolby Digital Plus - 5.1)
        audio_final = f"{audio_codec}{channels}"

        # --- 5. Qualidade (WEB-DL, BluRay) ---
        quality = "WEB-DL" # Padrão seguro
        if "BLURAY" in name_upper: quality = "BluRay"
        elif "REMUX" in name_upper: quality = "Remux"
        elif "HDTV" in name_upper: quality = "HDTV"
        elif "WEBRIP" in name_upper: quality = "WebRip"

        # --- 6. Limpeza do Nome (Linha 3) ---
        # Em vez de limpar o nome do arquivo, montamos um novo limpo
        keys = self.parsed.sortkeys
        title_clean = keys.get("title", "Filme")
        
        if self.strm_meta.type == "series":
            # Formato: Nome da Série - S01E01
            try:
                s = int(keys.get("season", keys.get("se", 0)))
                e = int(keys.get("episode", keys.get("ep", 0)))
                line3_text = f"{title_clean} - S{s:02}E{e:02}"
            except:
                line3_text = title_clean
        else:
            # Formato: Nome do Filme (2025)
            year = keys.get("year", "")
            line3_text = f"{title_clean} {year}".strip()

        # --- MONTAGEM FINAL ---
        # Linha 1: 📺 HDR+ | 🔊 Dolby Digital Plus - 5.1
        line1 = f"📺 {hdr_display} | 🔊 {audio_final}"
        
        # Linha 2: 🎥 WEB-DL | 🎞️ H.265 | 💾 15.01GiB
        line2 = f"🎥 {quality} | 🎞️ {codec} | 💾 {file_size}"
        
        # Linha 3: 📄 Afterburn 2025
        line3 = f"📄 {line3_text}"

        return f"{line1}\n{line2}\n{line3}"

    def get_proxy_url(self):
        file_id = self.item.get("id")
        file_name = urllib.parse.quote(self.item.get("name")) or "file_name.vid"
        if "behaviorHints" not in self.constructed:
             self.constructed["behaviorHints"] = {}
        self.constructed["behaviorHints"]["proxyHeaders"] = {
            "request": {"Server": "Stremio"}
        }
        return f"{self.proxy_url}/load/{file_id}/{file_name}"

    def get_gapi_url(self):
        file_id = self.item.get("id")
        file_name = urllib.parse.quote(self.item.get("name")) or "file_name.vid"
        if "behaviorHints" not in self.constructed:
             self.constructed["behaviorHints"] = {}
        self.constructed["behaviorHints"]["proxyHeaders"] = {
            "request": {"Authorization": f"Bearer {self.acc_token}"}
        }
        return f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media&file_name={file_name}"

    def construct_stream(self):
        self.constructed = {}
        self.constructed["behaviorHints"] = {}
        self.constructed["behaviorHints"]["notWebReady"] = True
        
        keys = getattr(self.parsed, 'sortkeys', {})
        res_raw = str(keys.get("res", ""))
        
        self.constructed["behaviorHints"]["bingeGroup"] = f"gdrive-{res_raw}"

        # Mapeamento de Resolução para a Barra Verde
        res_lower = res_raw.lower()
        if "2160" in res_lower:
            res_display = "2160p (4k)"
        elif "1080" in res_lower:
            res_display = "1080p (Full HD)"
        elif "720" in res_lower:
            res_display = "720p (HD)"
        else:
            res_display = res_raw or "SD"

        self.constructed["url"] = self.get_url()
        self.constructed["name"] = f"[L1 GDrive] {res_display} | 🇧🇷"
        self.constructed["title"] = self.get_title()
        self.constructed["sortkeys"] = keys

        return self.constructed

    def best_res(self, item):
        MAX_RES = 2160
        sortkeys = item.pop("sortkeys", {})
        resolution = sortkeys.get("res")

        try:
            res_map = {
                "hd": 720,
                "1280x720": 720,
                "1280x720p": 720,
                "1920x1080": 1080,
                "fhd": 1080,
                "uhd": 2160,
                "4k": 2160,
            }
            if resolution and isinstance(resolution, str):
                sort_int = res_map.get(resolution.lower()) 
                if not sort_int:
                     nums = re.findall(r'\d+', resolution)
                     sort_int = int(nums[0]) if nums else 1
            else:
                sort_int = 1
                
        except (TypeError, AttributeError, ValueError, ImportError):
            sort_int = 1

        ptn_name = sanitize(sortkeys.get("title", ""), "")
        
        name_match = False
        if self.strm_meta.titles:
            name_match = any(
                ptn_name.endswith(sanitize(title, "")) for title in self.strm_meta.titles
            )
        
        if not name_match:
            sort_int -= MAX_RES

        if self.strm_meta.type == "series":
            listify = lambda x: [x] if isinstance(x, int) or not x else x

            se_list = listify(sortkeys.get("se"))
            ep_list = listify(sortkeys.get("ep"))
            
            try:
                meta_se = int(self.strm_meta.se)
                meta_ep = int(self.strm_meta.ep)
                
                invalid_se = True
                if se_list:
                     invalid_se = meta_se not in [int(x) for x in se_list if str(x).isdigit()]
                
                invalid_ep = True
                if ep_list:
                     invalid_ep = meta_ep not in [int(x) for x in ep_list if str(x).isdigit()]

                if invalid_se or invalid_ep:
                    sort_int -= MAX_RES * 2
            except:
                sort_int -= MAX_RES * 2

        return sort_int
