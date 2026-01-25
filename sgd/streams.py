import os
import urllib
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
            self.item = item
            self.parsed = parse_title(item.get("name"))
            self.construct_stream()

            if self.is_semi_valid_title(self.constructed):
                if self.strm_meta.type == "movie":
                    if self.is_valid_year(self.constructed):
                        self.results.append(self.constructed)
                else:
                    self.results.append(self.constructed)

        self.results.sort(key=self.best_res, reverse=True)

    def is_valid_year(self, movie):
        movie_year = str(movie["sortkeys"].get("year", "0"))
        return movie_year == self.strm_meta.year

    def is_semi_valid_title(self, item):
        item_title = sanitize(str(item["sortkeys"].get("title")), "")
        if item_title:
            return any(
                sanitize(title, "") in item_title for title in self.strm_meta.titles
            )
        return False

    def get_title(self):
        # 1. Coleta de dados
        file_name = self.item.get("name")
        file_size = hr_size(int(self.item.get("size")))
        
        # 2. Extração de metadados do parser
        hdr_info = self.parsed.get("hdr", [])
        if isinstance(hdr_info, str): hdr_info = [hdr_info]
        
        # Força detecção de DV (Dolby Vision) se presente no nome
        if "DV" in file_name.upper() and "DV" not in [x.upper() for x in hdr_info]:
            hdr_info.append("DV")
        
        hdr_dv = " ".join(hdr_info) if hdr_info else "SDR"
        audio = self.parsed.get("audio", "Atmos")
        channels = self.parsed.get("channels", "5.1")
        quality = self.parsed.get("quality", "WEB-DL")
        codec = self.parsed.get("codec", "H.265")

        # 3. Formatação das linhas conforme desejado
        # Linha 1: 📺 HDR DV | 🔊 Atmos - 5.1 | 💾 18.4 GB
        line1 = f"📺 {hdr_dv} | 🔊 {audio} - {channels} | 💾 {file_size}"
        
        # Linha 2: 🎥 WEB-DL | 🎞️ x265 | 🇧🇷
        line2 = f"🎥 {quality} | 🎞️ {codec} | 🇧🇷"
        
        # Linha 3: 📄 Nome do Arquivo (Limpo)
        clean_name = file_name.rsplit('.', 1)[0].replace('.', ' ')
        line3 = f"📄 {clean_name}"

        return f"{line1}\n{line2}\n{line3}"

    def get_proxy_url(self):
        file_id = self.item.get("id")
        file_name = urllib.parse.quote(self.item.get("name")) or "file_name.vid"
        self.constructed["behaviorHints"]["proxyHeaders"] = {
            "request": {"Server": "Stremio"}
        }
        return f"{self.proxy_url}/load/{file_id}/{file_name}"

    def get_gapi_url(self):
        file_id = self.item.get("id")
        file_name = urllib.parse.quote(self.item.get("name")) or "file_name.vid"
        self.constructed["behaviorHints"]["proxyHeaders"] = {
            "request": {"Authorization": f"Bearer {self.acc_token}"}
        }
        return f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media&file_name={file_name}"

    def construct_stream(self):
        self.constructed = {}
        self.constructed["behaviorHints"] = {}
        self.constructed["behaviorHints"]["notWebReady"] = True
        
        res_raw = self.parsed.sortkeys.get("res", "")
        
        # Mapeamento de nomes de resolução
        res_map = {
            "2160p": "2160p (4k)",
            "1080p": "1080p (Full HD)",
            "720p": "720p (HD)"
        }
        res_display = res_map.get(res_raw.lower(), res_raw)

        self.constructed["url"] = self.get_url()
        self.constructed["name"] = f"[L1 GDrive] {res_display}"
        self.constructed["title"] = self.get_title()
        self.constructed["sortkeys"] = self.parsed.sortkeys

        return self.constructed

    def best_res(self, item):
        MAX_RES = 2160
        sortkeys = item.get("sortkeys").copy() # Usando copy para não afetar o original
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
            sort_int = res_map.get(resolution.lower()) or int(resolution[:-1])
        except (TypeError, AttributeError):
            sort_int = 1

        ptn_name = sanitize(sortkeys.get("title", ""), "")
        name_match = any(
            ptn_name.endswith(sanitize(title, "")) for title in self.strm_meta.titles
        )
        if not name_match:
            sort_int -= MAX_RES

        if self.strm_meta.type == "series":
            listify = lambda x: [x] if isinstance(x, int) or not x else x

            se_list = listify(sortkeys.get("se"))
            ep_list = listify(sortkeys.get("ep"))
            invalid_se = int(self.strm_meta.se) not in se_list
            invalid_ep = int(self.strm_meta.ep) not in ep_list

            if invalid_se or invalid_ep:
                sort_int -= MAX_RES * 2

        return sort_int
