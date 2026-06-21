import os
import json
import lxml
import cchardet
import sgd.utils as ut
from bs4 import BeautifulSoup
from sgd.cache import Json

class MetadataNotFound(Exception):
    pass

class IMDb:
    def __init__(self):
        self.imdb_sg_url = f"v2.sg.media-imdb.com/suggests/t/{self.id}.json"
        self.cinemeta_url = f"v3-cinemeta.strem.io/meta/{self.type}/{self.id}.json"
        self.imdb_html_url = f"imdb.com/title/{self.id}/releaseinfo?ref_=tt_dt_aka"

        self.fetch_dest = "None"
        
        # --- 1. TENTA TMDB PRIMEIRO (Para pegar PT-BR, Inglês e Original) ---
        if self.get_meta_from_tmdb():
            self.fetch_dest = "TMDB_API"
            
        # --- 2. FALLBACK PARA CINEMETA (Se o TMDB falhar ou não tiver API Key) ---
        if self.get_meta_from_cinemeta():
            if self.fetch_dest == "None":
                self.fetch_dest = "CINEMETA"
        
        # --- 3. FALLBACK PARA IMDB SUGGEST ---
        if not self.titles and self.get_meta_from_imdb_sg():
            if self.fetch_dest == "None":
                self.fetch_dest = "IMDB_SG_API"

        # --- 4. COMPLEMENTO HTML IMDB ---
        try:
            self.get_meta_from_imdb_html()
            if self.fetch_dest == "None" and self.titles:
                self.fetch_dest = "IMDB_HTML"
        except Exception as e:
            print(f"Aviso: Falha ao ler HTML do IMDb ({e})")

        if not self.titles:
            self.fetch_dest = "NULL"
            raise MetadataNotFound(
                f"Couldn't find metadata for {self.type} {self.id}!"
            )
            
        # Remove nomes duplicados e vazios para não fazer buscas repetidas
        cleaned_titles = []
        for t in self.titles:
            if t and isinstance(t, str) and len(t) > 1:
                clean_t = t.lower().strip()
                if clean_t not in cleaned_titles:
                    cleaned_titles.append(clean_t)
        self.titles = cleaned_titles

    def get_meta_from_tmdb(self):
        """Busca títulos no TMDB (Inglês, PT-BR e Original) usando a API Key do Vercel"""
        tmdb_key = os.environ.get("TMDB_API_KEY")
        if not tmdb_key:
            print("AVISO: TMDB_API_KEY não configurada no Vercel. Usando metadados básicos (Apenas Inglês).")
            return False
            
        try:
            # 1. Busca o ID do TMDB usando o ID do IMDb
            find_url = f"api.themoviedb.org/3/find/{self.id}?api_key={tmdb_key}&external_source=imdb_id"
            find_resp = ut.req_wrapper(find_url)
            if not find_resp: return False
            
            find_data = json.loads(find_resp)
            media_type = "movie" if self.type == "movie" else "tv"
            
            results = find_data.get(f"{media_type}_results", [])
            if not results: return False
            
            item = results[0]
            tmdb_id = item.get("id")
            
            # Adiciona Título Original
            original_title = item.get("original_title") or item.get("original_name")
            if original_title: self.titles.append(ut.sanitize(original_title))
            
            # Adiciona Título em Inglês
            eng_title = item.get("title") or item.get("name")
            if eng_title: self.titles.append(ut.sanitize(eng_title))
            
            # Pega o Ano
            date_str = item.get("release_date") or item.get("first_air_date")
            if date_str and len(date_str) >= 4 and ut.is_year(date_str[:4]):
                self.year = date_str[:4]
                
            # 2. Faz uma segunda requisição para pegar o título traduzido em PT-BR
            pt_url = f"api.themoviedb.org/3/{media_type}/{tmdb_id}?api_key={tmdb_key}&language=pt-BR"
            pt_resp = ut.req_wrapper(pt_url)
            if pt_resp:
                pt_data = json.loads(pt_resp)
                pt_title = pt_data.get("title") or pt_data.get("name")
                if pt_title: self.titles.append(ut.sanitize(pt_title))
                
            return True
            
        except Exception as e:
            print(f"Erro ao consultar TMDB: {e}")
            return False

    def get_meta_from_imdb_html(self):
        try:
            imdb_html = ut.req_wrapper(self.imdb_html_url, time_out=5)
            if not imdb_html: return False
            
            soup = BeautifulSoup(imdb_html, "lxml")
            table = soup.find("table", attrs={"class": "akas-table-test-only"})
            r_title_block = soup.find(
                "div", attrs={"class": "subpage_title_block__right-column"}
            )

            if r_title_block:
                h3_itemprop = r_title_block.find("h3", attrs={"itemprop": "name"})
                h4_itemprop = r_title_block.find("h4", attrs={"itemprop": "name"})

                title = ""
                if h4_itemprop:
                    t_text = ut.sanitize(h4_itemprop.find("a").text) + " "
                    if "golden globe" not in t_text.lower():
                        title = t_text

                if h3_itemprop:
                    t_text = ut.sanitize(h3_itemprop.find("a").text)
                    if "golden globe" not in t_text.lower():
                        title += t_text
                        self.titles.append(title)

                    if not self.year:
                        try:
                            span_text = h3_itemprop.find("span").text.strip()
                            years = list(filter(ut.is_year, ut.num_extract(span_text)))
                            self.year = min(years) if years else None
                        except: pass

            if table:
                table_rows = table.find_all("tr")
                table_data = [tr.find_all("td") for tr in table_rows]

                titles = set()
                first_title = ut.safe_get(self.titles, 0)

                for td in table_data:
                    title_text = ut.safe_get(td, 1).text
                    if not title_text: continue
                    
                    title = ut.sanitize(title_text)
                    if "golden globe" in title.lower():
                        continue

                    if title and title != first_title:
                        if not (title.isdigit() and len(title) < 3):
                            titles.add(title)

                limit = 100 
                self.titles += list(titles)[:limit]

            return True
        except Exception:
            return False

    def get_meta_from_imdb_sg(self):
        try:
            meta = ut.req_api(self.imdb_sg_url, key="d")
            if meta:
                self.set_meta(meta[0], year="y", title="l")
                return True
        except: pass
        return False

    def get_meta_from_cinemeta(self):
        try:
            meta = ut.req_api(self.cinemeta_url)
            if meta:
                self.set_meta(meta)
                return True
        except: pass
        return False

    def set_meta(self, meta, year="year", title="name"):
        clean_title = ut.sanitize(meta.get(title, ""))
        if "golden globe" not in clean_title.lower():
            self.titles.append(clean_title)
            
        y = str(meta.get(year, "")).split("–")[0]
        if y and ut.is_year(y):
            self.year = y


class Meta(IMDb):
    def __init__(self, stream_type, stream_id):
        self.titles = []
        self.year = None
        self.ep = 0
        self.se = 0

        self.id_split = stream_id.split("%3A")
        self.type = stream_type
        self.stream_type = stream_type

        self.id = self.id_split[0]
        if stream_type == "series":
            try:
                self.ep = str(self.id_split[-1]).zfill(2)
                self.se = str(self.id_split[-2]).zfill(2)
            except:
                pass

        cached = Json(f"{self.id}.json")
        if not cached.contents:
            IMDb.__init__(self)
            cached.contents.update(self.__dict__)
            cached.save()
        else:
            cached.contents["se"] = self.se
            cached.contents["ep"] = self.ep
            self.__dict__.update(cached.contents)
            self.fetch_dest = "CACHE"

        print(f"METADATA ({self.fetch_dest}): {self.titles} | Ano: {self.year}")
