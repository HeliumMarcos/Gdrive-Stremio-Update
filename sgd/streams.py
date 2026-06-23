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

        for item in getattr(gdrive, 'results', []):
            try:
                self.item = item
                if not isinstance(self.item, dict):
                    continue
                    
                self.parsed = parse_title(str(self.item.get("name", "")))
                
                # Hardening: Caso o parse_title retorne None ou falhe
                if self.parsed is None:
                    class DummyParsed: pass
                    self.parsed = DummyParsed()
                
                if not hasattr(self.parsed, 'sortkeys') or not isinstance(getattr(self.parsed, 'sortkeys', None), dict):
                    self.parsed.sortkeys = {}

                self.construct_stream()
                
                # --- FILTRO INTELIGENTE ---
                if self.is_semi_valid_title(self.constructed):
                    strm_type = getattr(self.strm_meta, 'type', '')
                    if strm_type == "movie":
                        if self.is_valid_year(self.constructed):
                            self.results.append(self.constructed)
                    elif strm_type == "series":
                        # VERIFICAÇÃO CRUCIAL: Bloqueia vazamentos de outras temporadas/episódios
                        if self.is_valid_episode(self.constructed):
                            self.results.append(self.constructed)
                    else:
                        self.results.append(self.constructed)
                    
            except Exception:
                continue

        # Ordenação baseada apenas nos dados contruídos, independente do self.item
        self.results.sort(key=self.best_res, reverse=True)

    def is_valid_year(self, movie):
        sortkeys = movie.get("sortkeys", {})
        if not isinstance(sortkeys, dict): 
            sortkeys = {}
            
        file_year_str = str(sortkeys.get("year", "0"))
        meta_year_str = str(getattr(self.strm_meta, 'year', '0'))

        if file_year_str == "0" or not file_year_str.isdigit():
            return True

        try:
            file_year = int(file_year_str)
            meta_year = int(meta_year_str)
            return abs(file_year - meta_year) <= 1
        except Exception:
            return True

    def is_valid_episode(self, item):
        """
        Confere se a temporada e o episódio do arquivo batem exatamente com a requisição do Stremio.
        """
        sortkeys = item.get("sortkeys", {})
        if not isinstance(sortkeys, dict): 
            sortkeys = {}
            
        file_se = sortkeys.get("se")
        file_ep = sortkeys.get("ep")
        
        # Fallback caso o PTN não pegue no campo principal (tentativa via regex)
        if file_se is None or file_ep is None:
            file_name = str(self.item.get("name", "")).lower()
            match = re.search(r's(\d+)\s*e(\d+)', file_name)
            if match:
                file_se, file_ep = match.groups()
            else:
                return False
                
        try:
            return int(file_se) == int(getattr(self.strm_meta, 'se', -1)) and int(file_ep) == int(getattr(self.strm_meta, 'ep', -1))
        except (ValueError, TypeError, AttributeError):
            return False

    def is_semi_valid_title(self, item):
        """
        Lógica Blindada com Filtro Anti-Spinoff e Proteção de Grupos de Lançamento BR
        """
        file_name_raw = str(self.item.get("name", ""))
        
        # --- 0. BYPASS DA ID DO IMDB ---
        imdb_id = getattr(self.strm_meta, "id", None)
        if imdb_id and str(imdb_id).lower() in file_name_raw.lower():
            return True

        def clean_str(s):
            s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
            s = re.sub(r"[^a-zA-Z0-9]", " ", s).lower()
            return " ".join(s.split())
            
        def filter_1_letter(s):
            return " ".join([w for w in s.split() if len(w) > 1 or w.isdigit()])

        file_clean = clean_str(file_name_raw)
        file_clean_filtered = filter_1_letter(file_clean)
        
        sortkeys = item.get("sortkeys", {})
        if not isinstance(sortkeys, dict): 
            sortkeys = {}
        ptn_title = sortkeys.get("title", "")

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
        titles = getattr(self.strm_meta, 'titles', [])
        if not titles:
            return False

        for title in titles:
            title_clean = clean_str(str(title))
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
        file_name = str(self.item.get("name", "Unknown"))
        name_upper = file_name.upper()
        
        try:
            file_size_raw = self.item.get("size", 0)
            file_size = hr_size(int(file_size_raw)) if file_size_raw else "0B"
        except Exception:
            file_size = "0B"

        # Codec (Atualizado com detecção nativa de AV1)
        if any(x in name_upper for x in ["AV1", "AV01"]):
            codec = "AV1"
        elif any(x in name_upper for x in ["HEVC", "X265", "H265", "H.265"]):
            codec = "H.265"
        elif any(x in name_upper for x in ["AVC", "X264", "H264", "H.264"]):
            codec = "H.264"
        else:
            sortkeys = getattr(self.parsed, 'sortkeys', {})
            if isinstance(sortkeys, dict):
                codec = sortkeys.get("codec", "CODEC?")
            else:
                codec = "CODEC?"

        # Quality
        quality = "WEB-DL"
        if "BLURAY" in name_upper: quality = "BluRay"
        elif "REMUX" in name_upper: quality = "Remux"
        elif "HDTV" in name_upper: quality = "HDTV"
        elif "WEBRIP" in name_upper: quality = "WebRip"

        # LAYOUT REFORMULADO
        line1 = f"🎥 {quality} | 🎞️ {codec} | 💾 {file_size}"
        line2 = f"📄 {file_name}"

        return f"{line1}\n{line2}"

    def get_proxy_url(self):
        file_id = str(self.item.get("id", ""))
        file_name = urllib.parse.quote(str(self.item.get("name", ""))) or "file_name.vid"
        if "behaviorHints" not in self.constructed:
             self.constructed["behaviorHints"] = {}
        self.constructed["behaviorHints"]["proxyHeaders"] = {
            "request": {"Server": "Stremio"}
        }
        return f"{self.proxy_url}/load/{file_id}/{file_name}"

    def get_gapi_url(self):
        file_id = str(self.item.get("id", ""))
        file_name = urllib.parse.quote(str(self.item.get("name", ""))) or "file_name.vid"
        if "behaviorHints" not in self.constructed:
             self.constructed["behaviorHints"] = {}
        self.constructed["behaviorHints"]["proxyHeaders"] = {
            "request": {"Authorization": f"Bearer {getattr(self, 'acc_token', '')}"}
        }
        return f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media&file_name={file_name}"

    def construct_stream(self):
        self.constructed = {}
        self.constructed["behaviorHints"] = {}
        self.constructed["behaviorHints"]["notWebReady"] = True
        
        keys = getattr(self.parsed, 'sortkeys', {})
        if not isinstance(keys, dict): 
            keys = {}
            
        res_raw = str(keys.get("res", ""))
        self.constructed["behaviorHints"]["bingeGroup"] = f"gdrive-{res_raw}"

        # MELHORIA 3: SALVAR O NOME ORIGINAL DO ARQUIVO PARA ORDENAÇÃO
        file_name = str(self.item.get("name", ""))
        self.constructed["filename"] = file_name

        self.constructed["url"] = self.get_url()
        
        # MELHORIA 2: NOVO FORMATO DO STREAM NAME
        title_clean = str(keys.get("title", "Titulo")).strip()
        strm_type = getattr(self.strm_meta, 'type', '')
        
        if strm_type == "series":
            try:
                s = int(keys.get("season", keys.get("se", 0)))
                e = int(keys.get("episode", keys.get("ep", 0)))
                if s > 0 and e > 0:
                    stream_name = f"📺 {title_clean} - T{s:02} E{e:02}"
                else:
                    stream_name = f"📺 {title_clean}"
            except Exception:
                stream_name = f"📺 {title_clean}"
        else:
            year = str(keys.get("year", "")).strip()
            if year:
                stream_name = f"📺 {title_clean} ({year})"
            else:
                stream_name = f"📺 {title_clean}"

        self.constructed["name"] = stream_name
        self.constructed["title"] = self.get_title()
        self.constructed["sortkeys"] = keys

        return self.constructed

    def best_res(self, item):
        """
        Ranking inteligente baseado em score estrito.
        Não depende de self.item para evitar bugs de ordenação.
        """
        score = 0
        
        filename = item.get("filename", "")
        if not isinstance(filename, str): 
            filename = ""
        name_upper = filename.upper()
        
        sortkeys = item.get("sortkeys", {})
        if not isinstance(sortkeys, dict): 
            sortkeys = {}

        # 1. Resolução (Prioridade Máxima)
        res_raw = str(sortkeys.get("res", "")).upper()
        if "2160" in res_raw or "4K" in res_raw: 
            score += 1000000000
        elif "1080" in res_raw or "FHD" in res_raw: 
            score += 800000000
        elif "720" in res_raw or "HD" in res_raw: 
            score += 600000000
        else:
            # Fallback regex no filename
            if "2160P" in name_upper or "4K" in name_upper: 
                score += 1000000000
            elif "1080P" in name_upper: 
                score += 800000000
            elif "720P" in name_upper: 
                score += 600000000
            else: 
                score += 400000000

        # 2. Fonte
        if "REMUX" in name_upper: score += 100000000
        elif "BLURAY" in name_upper: score += 80000000
        elif "WEB-DL" in name_upper or "WEBDL" in name_upper: score += 60000000
        elif "WEBRIP" in name_upper: score += 40000000
        elif "HDTV" in name_upper: score += 20000000

        # 3. HDR
        if "DV" in name_upper or "DOLBY VISION" in name_upper: score += 10000000
        elif "HDR10+" in name_upper or "HDR+" in name_upper: score += 8000000
        elif "HDR" in name_upper: score += 6000000

        # 4. Áudio
        if "ATMOS" in name_upper: score += 1000000
        elif any(x in name_upper for x in ["DDP", "EAC3", "DD+"]): score += 800000
        elif any(x in name_upper for x in ["DD", "AC3"]): score += 600000
        elif "DTS-HD" in name_upper or "DTSHD" in name_upper: score += 400000
        elif "DTS" in name_upper: score += 200000
        elif "AAC" in name_upper: score += 100000

        # 5. Codec
        if any(x in name_upper for x in ["AV1", "AV01"]): score += 100000
        elif any(x in name_upper for x in ["HEVC", "X265", "H265", "H.265"]): score += 80000
        elif any(x in name_upper for x in ["AVC", "X264", "H264", "H.264"]): score += 60000

        # 6. Canais
        if "7.1" in name_upper: score += 10000
        elif "5.1" in name_upper: score += 8000
        elif "2.0" in name_upper: score += 6000

        # 7. Idioma
        if any(x in name_upper for x in ["DUBLADO", "PT-BR", "PTBR", "DUAL", "MULTI"]):
            score += 1000

        # 8. Origem do streaming
        if any(x in name_upper for x in ["HMAX", "DSNP", "AMZN", "NF", "ATVP", "MAX"]):
            score += 100

        return score
