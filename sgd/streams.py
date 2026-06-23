import os
import urllib
import re
import unicodedata
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
                
                # Hardening: Previne quebra se o parse_title falhar ou retornar None
                self.parsed = parse_title(str(item.get("name", "")))
                if self.parsed is None:
                    class DummyParsed: pass
                    self.parsed = DummyParsed()
                
                if not hasattr(self.parsed, 'sortkeys') or not isinstance(getattr(self.parsed, 'sortkeys', None), dict):
                    self.parsed.sortkeys = {}

                self.construct_stream()
                
                # --- FILTRO INTELIGENTE ---
                if self.is_semi_valid_title(self.constructed):
                    if self.strm_meta.type == "movie":
                        if self.is_valid_year(self.constructed):
                            self.results.append(self.constructed)
                    elif self.strm_meta.type == "series":
                        # VERIFICAÇÃO CRUCIAL: Bloqueia vazamentos de outras temporadas/episódios
                        if self.is_valid_episode(self.constructed):
                            self.results.append(self.constructed)
                    
            except Exception as e:
                continue

        self.results.sort(key=self.best_res, reverse=True)

    def is_valid_year(self, movie):
        sortkeys = movie.get("sortkeys", {})
        file_year_str = str(sortkeys.get("year", "0"))
        meta_year_str = str(self.strm_meta.year)

        if file_year_str == "0" or not file_year_str.isdigit():
            return True

        try:
            file_year = int(file_year_str)
            meta_year = int(meta_year_str)
            return abs(file_year - meta_year) <= 1
        except:
            return True

    def is_valid_episode(self, item):
        """
        Confere se a temporada e o episódio do arquivo batem exatamente com a requisição do Stremio.
        """
        sortkeys = item.get("sortkeys", {})
        file_se = sortkeys.get("se")
        file_ep = sortkeys.get("ep")
        
        # Fallback caso o PTN não pegue no campo principal (tentativa via regex)
        if file_se is None or file_ep is None:
            file_name = self.item.get("name", "").lower()
            match = re.search(r's(\d+)\s*e(\d+)', file_name)
            if match:
                file_se, file_ep = match.groups()
            else:
                return False
                
        try:
            return int(file_se) == int(self.strm_meta.se) and int(file_ep) == int(self.strm_meta.ep)
        except (ValueError, TypeError):
            return False

    def is_semi_valid_title(self, item):
        """
        Lógica Blindada com Filtro Anti-Spinoff e Proteção de Grupos de Lançamento BR
        """
        file_name_raw = self.item.get("name", "")
        
        # --- 0. BYPASS DA ID DO IMDB ---
        imdb_id = getattr(self.strm_meta, "id", None)
        if imdb_id and imdb_id.lower() in file_name_raw.lower():
            return True

        def clean_str(s):
            s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
            s = re.sub(r"[^a-zA-Z0-9]", " ", s).lower()
            return " ".join(s.split())
            
        def filter_1_letter(s):
            return " ".join([w for w in s.split() if len(w) > 1 or w.isdigit()])

        file_clean = clean_str(file_name_raw)
        file_clean_filtered = filter_1_letter(file_clean)
        
        ptn_title = item.get("sortkeys", {}).get("title", "")

        STOP_WORDS = {
            "and", "of", "to", "in", "for", "on", "at", "by", "with", "the", "a", "an",
            "o", "os", "as", "um", "uma", "de", "do", "da", "dos", "das", 
            "em", "no", "na", "nos", "nas", "por", "para", "com", "se", "que", "ou"
        }
        
        ALLOWED_EXTRAS = {
            "filme", "movie", "series", "serie", "temporada", "season", 
            "pt", "br", "dublado", "legendado", "dual", "audio", "remastered", 
            "remaster", "director", "cut", "extended", "unrated", "edition", 
            "part", "parte", "vol", "volume", "ep", "episodio", "1080p", "4k", 
            "2160p", "720p", "hd", "web", "dl", "bluray", "remux", "tv",
            "h264", "h265", "hevc", "avc", "aac", "ddp", "atmos", "x264", "x265", 
            "amzn", "nf", "dsnp", "max", "hbo", "peacock", "hulu", "apple", "appletv",
            "bioma", "c76", "lapumia", "wolverdon", "bludv", "comandotorrents", "comando",
            "torrent", "torrents", "yts", "yify", "rarbg", "rmteam", "mkv", "mp4", "avi"
        }

        match_found = False

        for title in self.strm_meta.titles:
            title_clean = clean_str(title)
            title_clean_filtered = filter_1_letter(title_clean)
            
            if not title_clean_filtered:
                title_clean_filtered = title_clean
                file_clean_filtered = file_clean
            
            words = title_clean_filtered.split()
            strong_words = [w for w in words if w not in STOP_WORDS]
            if not strong_words: strong_words = words

            is_match_candidate = False
            
            # --- CENÁRIO 1: TÍTULO CURTO (Até 2 palavras fortes) ---
            if len(words) <= 2:
                if f" {title_clean_filtered} " in f" {file_clean_filtered} ":
                    is_match_candidate = True
                else:
                    pattern = r'\b' + re.escape(title_clean_filtered) + r'\b'
                    if re.search(pattern, file_clean_filtered):
                        is_match_candidate = True

            # --- CENÁRIO 2: TÍTULO MÉDIO/LONGO (3+ palavras) ---
            else:
                file_tokens = set(file_clean_filtered.split())
                missing = [w for w in strong_words if w not in file_tokens]
                
                if not missing or (len(strong_words) >= 4 and len(missing) <= 1):
                    is_match_candidate = True

            # --- FILTRO DE BLOQUEIO (Anti-Spinoff) ---
            if is_match_candidate:
                if ptn_title:
                    ptn_clean = clean_str(ptn_title)
                    ptn_strong = [w for w in ptn_clean.split() if w not in STOP_WORDS]
                    meaningful_extras = [w for w in ptn_strong if w not in strong_words and w not in ALLOWED_EXTRAS]
                    
                    if len(meaningful_extras) > 0:
                        continue 
                
                match_found = True
                break

        return match_found

    def get_title(self):
        file_name = self.item.get("name", "Unknown")
        name_upper = file_name.upper()
        
        try:
            file_size = hr_size(int(self.item.get("size", 0)))
        except:
            file_size = "0B"

        # Codec
        if any(x in name_upper for x in ["AV1", "AV01"]):
            codec = "AV1"
        elif any(x in name_upper for x in ["HEVC", "X265", "H265", "H.265"]):
            codec = "H.265"
        elif any(x in name_upper for x in ["AVC", "X264", "H264", "H.264"]):
            codec = "H.264"
        else:
            codec = self.parsed.sortkeys.get("codec", "CODEC?")

        # HDR / DV - Ajustado para ativar emblemas Nuvio
        hdr_list = []
        if "HDR10+" in name_upper or "HDR+" in name_upper:
            hdr_list.append("HDR10+")
        elif "HDR10" in name_upper:
            hdr_list.append("HDR10")
        elif "HDR" in name_upper:
            hdr_list.append("HDR")   
        if "DV" in name_upper or "DOLBY VISION" in name_upper:
            hdr_list.append("Dolby Vision")
        hdr_display = " ".join(hdr_list) if hdr_list else "SDR"

        # Audio - Ajustado para ativar emblemas Nuvio
        audio_codec = "Audio"
        if "ATMOS" in name_upper: 
            audio_codec = "Dolby Atmos"
        elif any(x in name_upper for x in ["DDP", "DD+", "EAC3", "DIGITAL PLUS"]): 
            audio_codec = "Dolby Digital+"
        elif any(x in name_upper for x in ["DD", "AC3", "DOLBY DIGITAL"]): 
            audio_codec = "Dolby Digital"
        elif "AAC" in name_upper: 
            audio_codec = "AAC"
        elif "DTS" in name_upper: 
            audio_codec = "DTS"

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

        # LAYOUT
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

        # Injetando o nome do arquivo para ser usado no best_res()
        self.constructed["filename"] = self.item.get("name", "")

        self.constructed["url"] = self.get_url()
        self.constructed["name"] = f"[L1 GDrive] {res_display} | 🇧🇷"
        self.constructed["title"] = self.get_title()
        self.constructed["sortkeys"] = keys

        return self.constructed

    def best_res(self, item):
        try:
            score = 0
            
            file_name = str(item.get("filename", "")).upper()
            sortkeys = item.get("sortkeys", {})
            if not isinstance(sortkeys, dict): 
                sortkeys = {}

            # 1. Resolução (Prioridade Máxima)
            res_raw = str(sortkeys.get("res", "")).upper()
            if "2160" in res_raw or "4K" in res_raw or "2160P" in file_name or "4K" in file_name: 
                score += 1000000000
            elif "1080" in res_raw or "FHD" in res_raw or "1080P" in file_name: 
                score += 800000000
            elif "720" in res_raw or "HD" in res_raw or "720P" in file_name: 
                score += 600000000
            else: 
                score += 400000000

            # 2. Fonte (Remux > BluRay > Web-DL)
            if "REMUX" in file_name: score += 100000000
            elif "BLURAY" in file_name: score += 80000000
            elif "WEB-DL" in file_name or "WEBDL" in file_name: score += 60000000

            # 3. HDR e Áudio (DV e Atmos no topo)
            if "DV" in file_name or "DOLBY VISION" in file_name: score += 10000000
            if "HDR10+" in file_name or "HDR+" in file_name: score += 8000000
            
            if "ATMOS" in file_name: score += 1000000
            elif "DDP" in file_name or "DD+" in file_name: score += 800000

            # 4. Idioma (Priorizar PT-BR / Dublado)
            if any(x in file_name for x in ["DUBLADO", "PT-BR", "PTBR", "DUAL", "MULTI"]):
                score += 1000

            return score
        except:
            return 1
