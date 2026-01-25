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
                self.parsed = parse_title(item.get("name"))
                
                # Se não tem sortkeys, cria um vazio para não quebrar
                if not hasattr(self.parsed, 'sortkeys'):
                    self.parsed.sortkeys = {}

                self.construct_stream()
                
                # --- LÓGICA DE FILTRO PERMISSIVA ---
                # Adicionamos o arquivo primeiro, depois filtramos se for muito absurdo
                if self.strm_meta.type == "movie":
                    if self.is_valid_year(self.constructed):
                        self.results.append(self.constructed)
                else:
                    # Para séries, o filtro principal é SxxExx que já foi feito na busca
                    self.results.append(self.constructed)
                    
            except Exception as e:
                print(f"Erro item: {e}")
                continue

        self.results.sort(key=self.best_res, reverse=True)

    def is_valid_year(self, movie):
        sortkeys = movie.get("sortkeys", {})
        file_year_str = str(sortkeys.get("year", "0"))
        meta_year_str = str(self.strm_meta.year)

        # Se o arquivo não tem ano identificado (comum em Web-DL), ACEITA.
        if file_year_str == "0" or not file_year_str.isdigit():
            return True

        try:
            file_year = int(file_year_str)
            meta_year = int(meta_year_str)
            # Aceita diferença de 1 ano (Ex: Meta 2024, Arq 2025)
            return abs(file_year - meta_year) <= 1
        except:
            return True

    def is_semi_valid_title(self, item):
        # Essa função estava restritiva demais. 
        # Como já filtramos na busca do GDrive, podemos ser mais lenientes aqui.
        return True

    def get_title(self):
        file_name = self.item.get("name", "Unknown")
        name_upper = file_name.upper()
        
        try:
            file_size = hr_size(int(self.item.get("size", 0)))
        except:
            file_size = "0B"

        # Codec
        if any(x in name_upper for x in ["HEVC", "X265", "H265", "H.265"]):
            codec = "H.265"
        elif any(x in name_upper for x in ["AVC", "X264", "H264", "H.264"]):
            codec = "H.264"
        else:
            codec = self.parsed.sortkeys.get("codec", "CODEC?")

        # HDR / DV
        hdr_list = []
        if "HDR10+" in name_upper or "HDR+" in name_upper:
            hdr_list.append("HDR+")
        elif "HDR" in name_upper:
            hdr_list.append("HDR")
        if "DV" in name_upper or "DOLBY VISION" in name_upper:
            hdr_list.append("Dolby Vision")   
        hdr_display = " ".join(hdr_list) if hdr_list else "SDR"

        # Audio
        audio_codec = "Audio"
        if "ATMOS" in name_upper: audio_codec = "Dolby Atmos"
        elif any(x in name_upper for x in ["DDP", "DD+", "EAC3"]): audio_codec = "Dolby Digital Plus"
        elif any(x in name_upper for x in ["DD", "AC3"]): audio_codec = "Dolby Digital"
        elif "AAC" in name_upper: audio_codec = "AAC"
        elif "DTS" in name_upper: audio_codec = "DTS"

        channels = ""
        channel_match = re.search(r'\b(7\.1|5\.1|2\.0)\b', file_name)
        if not channel_match: channel_match = re.search(r'(7\.1|5\.1|2\.0)', file_name)
        if channel_match: channels = f" - {channel_match.group(1)}"
        
        audio_final = f"{audio_codec}{channels}"

        # Quality
        quality = "WEB-DL"
        if "BLURAY" in name_upper: quality = "BluRay"
        elif "REMUX" in name_upper: quality = "Remux"
        elif "HDTV" in name_upper: quality = "HDTV"
        elif "WEBRIP" in name_upper: quality = "WebRip"

        # Nome Limpo
        keys = getattr(self.parsed, 'sortkeys', {})
        title_clean = keys.get("title", "Titulo")
        
        if self.strm_meta.type == "series":
            try:
                s = int(keys.get("season", keys.get("se", 0)))
                e = int(keys.get("episode", keys.get("ep", 0)))
                line3_text = f"{title_clean} - S{s:02}E{e:02}"
            except:
                line3_text = title_clean
        else:
            year = keys.get("year", "")
            line3_text = f"{title_clean} {year}".strip()

        # SEU LAYOUT
        line1 = f"📺 {hdr_display} | 🔊 {audio_final}"
        line2 = f"🎥 {quality} | 🎞️ {codec} | 💾 {file_size}"
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

        res_lower = res_raw.lower()
        if "2160" in res_lower: res_display = "2160p (4k)"
        elif "1080" in res_lower: res_display = "1080p (Full HD)"
        elif "720" in res_lower: res_display = "720p (HD)"
        else: res_display = res_raw or "SD"

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
            res_map = {"hd": 720, "fhd": 1080, "uhd": 2160, "4k": 2160}
            if resolution and isinstance(resolution, str):
                sort_int = res_map.get(resolution.lower()) 
                if not sort_int:
                     nums = re.findall(r'\d+', resolution)
                     sort_int = int(nums[0]) if nums else 1
            else: sort_int = 1     
        except: sort_int = 1

        # Lógica simplificada de ranking
        # Se for série e não tiver temp/ep, joga pro fim
        if self.strm_meta.type == "series":
             if not sortkeys.get("se") or not sortkeys.get("ep"):
                 sort_int -= MAX_RES * 2

        return sort_int
