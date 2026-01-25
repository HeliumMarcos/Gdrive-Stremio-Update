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
            try:
                self.item = item
                self.parsed = parse_title(item.get("name"))
                
                # Garante que sortkeys existe
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
                # Se um arquivo der erro, ele pula para o próximo sem quebrar tudo
                print(f"Erro ao processar item: {e}")
                continue

        self.results.sort(key=self.best_res, reverse=True)

    def is_valid_year(self, movie):
        # Acessa sortkeys com segurança
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
        # 1. Coleta de dados brutos
        file_name = self.item.get("name", "Unknown")
        
        try:
            file_size = hr_size(int(self.item.get("size", 0)))
        except:
            file_size = "0B"

        # 2. Extração segura dos metadados (tudo via sortkeys)
        # Se self.parsed falhar, usa um dicionário vazio
        data = getattr(self.parsed, 'sortkeys', {})

        # HDR e DV
        hdr_raw = data.get("hdr", [])
        if isinstance(hdr_raw, str):
            hdr_raw = [hdr_raw]
        elif not isinstance(hdr_raw, list):
            hdr_raw = []
        
        # Converte para string uppercase para comparação
        hdr_list = [str(x).upper() for x in hdr_raw]

        # Força detecção de DV se estiver no nome do arquivo
        if "DV" in file_name.upper() and "DV" not in hdr_list:
            hdr_list.append("DV")
        
        hdr_dv = " ".join(hdr_list) if hdr_list else "SDR"

        # Demais dados com valores padrão (Fallback)
        audio = data.get("audio", "Audio")
        channels = data.get("channels", "")
        # Se channels estiver vazio, não mostra o traço extra
        audio_str = f"{audio} - {channels}" if channels else audio
        
        quality = data.get("quality", "WEB-DL")
        codec = data.get("codec", "Code?")

        # 3. Formatação Visual
        # Linha 1: 📺 HDR DV | 🔊 Atmos - 5.1 | 💾 18.4 GB
        line1 = f"📺 {hdr_dv} | 🔊 {audio_str} | 💾 {file_size}"
        
        # Linha 2: 🎥 WEB-DL | 🎞️ H.265 | 🇧🇷
        line2 = f"🎥 {quality} | 🎞️ {codec} | 🇧🇷"
        
        # Linha 3: Limpeza do nome
        try:
            clean_name = file_name.rsplit('.', 1)[0].replace('.', ' ')
        except:
            clean_name = file_name
        
        line3 = f"📄 {clean_name}"

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
        
        # Acesso seguro a sortkeys
        keys = getattr(self.parsed, 'sortkeys', {})
        res_raw = str(keys.get("res", ""))
        
        self.constructed["behaviorHints"]["bingeGroup"] = f"gdrive-{res_raw}"

        # Mapeamento
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
        self.constructed["name"] = f"[L1 GDrive] {res_display}"
        self.constructed["title"] = self.get_title()
        self.constructed["sortkeys"] = keys # Guarda keys para uso no best_res

        return self.constructed

    def best_res(self, item):
        MAX_RES = 2160
        # Usa pop com padrão vazio para evitar KeyError
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
            # Conversão segura
            if resolution and isinstance(resolution, str):
                sort_int = res_map.get(resolution.lower()) 
                if not sort_int:
                     # Tenta pegar apenas os números (ex: 720p -> 720)
                     import re
                     nums = re.findall(r'\d+', resolution)
                     sort_int = int(nums[0]) if nums else 1
            else:
                sort_int = 1
                
        except (TypeError, AttributeError, ValueError, ImportError):
            sort_int = 1

        ptn_name = sanitize(sortkeys.get("title", ""), "")
        
        # Verificação segura de títulos
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
                
                # Verifica se as listas existem e contêm os números
                invalid_se = True
                if se_list:
                     invalid_se = meta_se not in [int(x) for x in se_list if str(x).isdigit()]
                
                invalid_ep = True
                if ep_list:
                     invalid_ep = meta_ep not in [int(x) for x in ep_list if str(x).isdigit()]

                if invalid_se or invalid_ep:
                    sort_int -= MAX_RES * 2
            except:
                # Se falhar a conversão de temporada/episódio, penaliza por segurança
                sort_int -= MAX_RES * 2

        return sort_int
