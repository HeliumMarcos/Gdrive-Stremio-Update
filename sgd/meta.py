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
        
        # --- MUDANÇA 1: Prioriza Cinemeta (Mais estável e correto) ---
        if self.get_meta_from_cinemeta():
            self.fetch_dest = "CINEMETA"
        
        # Se Cinemeta falhar, tenta a API de sugestões do IMDb
        if not self.titles and self.get_meta_from_imdb_sg():
            self.fetch_dest = "IMDB_SG_API"

        # --- MUDANÇA 2: HTML roda sempre como COMPLEMENTO (para pegar AKAs/Traduções) ---
        # Não substitui o principal, apenas adiciona variações para ajudar na busca
        try:
            self.get_meta_from_imdb_html()
            if self.fetch_dest == "None" and self.titles:
                self.fetch_dest = "IMDB_HTML"
        except Exception as e:
            print(f"Aviso: Falha ao ler HTML do IMDb ({e}) - Usando dados básicos.")

        # Se no final de tudo não tiver título...
        if not self.titles:
            self.fetch_dest = "NULL"
            raise MetadataNotFound(
                f"Couldn't find metadata for {self.type} {self.id}!"
            )
            
        # Remove duplicatas mantendo a ordem
        self.titles = list(dict.fromkeys(self.titles))

    def get_meta_from_imdb_html(self):
        """
        Scrape metadata from imdb aka page. Includes local
        names to get more results
        """
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
                    # --- FILTRO DE SEGURANÇA ---
                    if "golden globe" not in t_text.lower():
                        title += t_text
                        self.titles.append(title)

                    # Tenta extrair ano apenas se ainda não temos (Cinemeta já deve ter preenchido)
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
                    
                    # --- FILTRO DE SEGURANÇA ---
                    if "golden globe" in title.lower():
                        continue

                    if title and title != first_title:
                        # Ignora títulos que são só números curtos
                        if not (title.isdigit() and len(title) < 3):
                            titles.add(title)

                limit = 100 
                self.titles += list(titles)[:limit]

            return True
        except Exception:
            return False

    def get_meta_from_imdb_sg(self):
        """Obtain metadata from imdb suggestions api"""
        try:
            meta = ut.req_api(self.imdb_sg_url, key="d")
            if meta:
                self.set_meta(meta[0], year="y", title="l")
                return True
        except: pass
        return False

    def get_meta_from_cinemeta(self):
        """Obtain metadata from cinemeta v3 api"""
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
            
        # Pega o ano, lidando com formatos "2022–" ou "2022"
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
            # Proteção contra IDs mal formatados
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
            # Refresh se:ep to prevent series' from searching last cached
            cached.contents["se"] = self.se
            cached.contents["ep"] = self.ep
            self.__dict__.update(cached.contents)
            self.fetch_dest = "CACHE"

        # Logs úteis para debug
        print(f"METADATA ({self.fetch_dest}): {self.titles} | Ano: {self.year}")
