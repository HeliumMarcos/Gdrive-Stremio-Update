import requests
from datetime import datetime, timedelta
from sgd.cache import Pickle, Json
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials


class GoogleDrive:
    def __init__(self, token):
        self.token = token
        self.page_size = 1000
        self.acc_token = Pickle("acctoken.pickle")
        self.drive_names = Json("drivenames.json")

        creds = Credentials.from_authorized_user_info(self.token)
        self.drive_instance = build("drive", "v3", credentials=creds)

    @staticmethod
    def qgen(string, chain="and", splitter=" ", method=None):
        out = ""
        get_method = lambda _: method
        if not method:
            get_method = lambda w: "fullText" if w.isdigit() else "name"

        # Limpeza e Tokenização
        cleaned_string = " ".join(string.split())
        words = cleaned_string.split(splitter)
        
        # Filtro Inteligente: Remove palavras curtas (The, Of, At) se houver outras palavras
        # Isso evita que "The Pitt" falhe se o arquivo for só "Pitt"
        valid_words = [w for w in words if len(w) > 2 or w.isdigit()]
        
        # Se só sobrou palavras curtas (ex: filme "The End"), usa tudo.
        if not valid_words:
            valid_words = words

        for word in valid_words:
            if not word: continue
            if out: out += f" {chain} "
            
            # Escapa apóstrofos
            word_escaped = word.replace("'", "\\'")
            out += f"{get_method(word)} contains '{word_escaped}'"
            
        return out

    def get_query(self, sm):
        out = []
        
        def clean_title(t):
            # Remove caracteres que confundem a busca
            return t.replace(":", " ").replace("-", " ").replace(".", " ").strip()

        if sm.stream_type == "series":
            # GERA TODAS AS VARIAÇÕES POSSÍVEIS DE TEMPORADA/EPISÓDIO
            seep_q = self.qgen(
                f"S{sm.se}E{sm.ep}, "      # S01E01 (Junto - FALTAVA ISSO)
                f"S{sm.se} E{sm.ep}, "     # S01 E01
                f"s{sm.se} e{sm.ep}, "     # s01 e01
                f"Season {int(sm.se)}, "   # Season 1 (Pega pasta da temporada)
                f"{int(sm.se)}x{sm.ep}, "  # 1x01
                f"{sm.se}.{sm.ep}",        # 01.01
                chain="or",
                splitter=", ",
                method="name", # Foca no nome do arquivo para SxxExx
            )
            
            for title in sm.titles:
                clean_t = clean_title(title)
                # Busca: (Nome contém Título) E (Nome contém SxxExx)
                out.append(f"({self.qgen(clean_t)}) and ({seep_q})")
                
        else:
            # LÓGICA DE FILMES
            for title in sm.titles:
                clean_t = clean_title(title)
                # Removemos a obrigatoriedade do ANO na busca do Drive.
                # Isso acha filmes onde o ano do arquivo difere do IMDb.
                out.append(self.qgen(clean_t))
                
        return out

    def file_list(self, file_fields):
        def callb(request_id, response, exception):
            if exception:
                print(f"Erro GDrive Search: {exception}")
            if response:
                output.extend(response.get("files", []))

        output = []
        if self.query:
            files = self.drive_instance.files()
            batch = self.drive_instance.new_batch_http_request()
            for q in self.query:
                # print(f"Query GDrive: {q}") # Debug
                batch_inst = files.list(
                    q=f"{q} and trashed=false and mimeType contains 'video/'",
                    fields=f"files({file_fields})",
                    pageSize=self.page_size,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                    corpora="allDrives",
                )
                batch.add(batch_inst, callback=callb)
            try:
                batch.execute()
            except Exception as e:
                print(f"Erro Batch Execute: {e}")
            return output
        return output

    def get_drive_names(self):
        def callb(request_id, response, exception):
            if response:
                self.drive_names.contents[response.get("id")] = response.get("name")

        batch = self.drive_instance.new_batch_http_request()
        drives = self.drive_instance.drives()
        
        drive_ids = set(item.get("driveId") for item in self.results if item.get("driveId"))
        if not drive_ids: return {}

        for drive_id in drive_ids:
            if not self.drive_names.contents.get(drive_id):
                self.drive_names.contents[drive_id] = None
                batch.add(drives.get(driveId=drive_id, fields="name, id"), callback=callb)

        try:
            batch.execute()
        except:
            pass
            
        self.drive_names.save()
        return self.drive_names.contents

    def search(self, stream_meta):
        self.results = []
        self.query = self.get_query(stream_meta)

        # Adiciona 'createdTime' para ajudar em desempate se necessário
        response = self.file_list("id, name, size, driveId, md5Checksum, createdTime")
        
        if response:
            uids = set()
            def check_dupe(item):
                uid = item.get("driveId", "MyD") + item.get("md5Checksum", item.get("id"))
                if uid in uids: return False
                uids.add(uid)
                return True

            self.results = sorted(
                filter(check_dupe, response),
                key=lambda item: int(item.get("size", 0)),
                reverse=True,
            )

        self.get_drive_names()
        return self.results

    def get_acc_token(self):
        if not self.acc_token.contents: self.acc_token.contents = {}
        
        expires = self.acc_token.contents.get("expires_in")
        is_expired = True
        
        if expires:
            try:
                if isinstance(expires, str): expires = datetime.fromisoformat(expires)
                is_expired = expires <= datetime.now()
            except: pass

        if is_expired:
            try:
                body = {
                    "client_id": self.token["client_id"],
                    "client_secret": self.token["client_secret"],
                    "refresh_token": self.token["refresh_token"],
                    "grant_type": "refresh_token",
                }
                res = requests.post("https://www.googleapis.com/oauth2/v4/token", json=body).json()
                
                if "access_token" in res:
                    res["expires_in"] = timedelta(seconds=res["expires_in"]) + datetime.now()
                    self.acc_token.contents = res
                    self.acc_token.save()
                else:
                    print(f"Erro Token: {res}")
            except Exception as e:
                print(f"Erro fatal Token: {e}")

        return self.acc_token.contents.get("access_token")
